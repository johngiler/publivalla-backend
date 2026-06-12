"""Plan de pago por partes: cuotas, montos por mes y persistencia."""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from rest_framework import serializers

from apps.orders.models import (
    Order,
    OrderPaymentInstallment,
    OrderPaymentInstallmentMonth,
    OrderPaymentInstallmentStatus,
    OrderPaymentPlan,
    OrderStatus,
)
from apps.orders.utils.custom_rental_start import (
    catalog_subtotal_with_custom_start,
    reservation_month_anchor,
)
from apps.orders.utils.rental_billing import line_subtotal_for_center

logger = logging.getLogger(__name__)

_MONTH_SHORT_ES = (
    "ENE",
    "FEB",
    "MAR",
    "ABR",
    "MAY",
    "JUN",
    "JUL",
    "AGO",
    "SEP",
    "OCT",
    "NOV",
    "DIC",
)

_ORDER_PAYMENT_PLAN_BLOCKED_STATUSES = frozenset(
    {
        OrderStatus.ACTIVE,
        OrderStatus.EXPIRED,
        OrderStatus.CANCELLED,
    }
)

_INSTALLMENT_AUTO_INVOICE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.PAID,
        OrderStatus.PERMIT_PENDING,
        OrderStatus.INSTALLATION,
        OrderStatus.ACTIVE,
    }
)


def order_payment_plan_editable(order: Order) -> bool:
    return order.status not in _ORDER_PAYMENT_PLAN_BLOCKED_STATUSES


def order_uses_split_payment(order: Order) -> bool:
    try:
        plan = order.payment_plan
    except OrderPaymentPlan.DoesNotExist:
        return False
    return bool(plan.enabled)


def payment_plan_pending_param_active(raw: str) -> bool:
    """Query ``payment_plan_pending=pending`` (u homólogos truthy)."""
    return (raw or "").strip().lower() in ("pending", "1", "true", "yes")


def _incomplete_payment_installment_subquery(*, order_outer_ref: str):
    return OrderPaymentInstallment.objects.filter(
        plan__order_id=OuterRef(order_outer_ref),
        plan__enabled=True,
    ).exclude(status=OrderPaymentInstallmentStatus.PAID)


def filter_orders_with_incomplete_payment_plan(qs):
    """Pedidos con plan activo y al menos una cuota sin pagar."""
    return qs.filter(payment_plan__enabled=True).filter(
        Exists(_incomplete_payment_installment_subquery(order_outer_ref="pk"))
    )


def filter_order_items_with_incomplete_payment_plan(qs):
    """Líneas cuyo pedido tiene plan activo con cuotas pendientes."""
    return qs.filter(order__payment_plan__enabled=True).filter(
        Exists(_incomplete_payment_installment_subquery(order_outer_ref="order_id"))
    )


def _iter_calendar_months(start: date, end: date):
    y, m = start.year, start.month
    end_y, end_m = end.year, end.month
    while (y, m) <= (end_y, end_m):
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def order_calendar_months(order: Order) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    months: list[tuple[int, int]] = []
    for item in order.items.all():
        for ym in _iter_calendar_months(item.start_date, item.end_date):
            if ym not in seen:
                seen.add(ym)
                months.append(ym)
    months.sort()
    return months


def _month_clip(item, year: int, month: int) -> tuple[date, date] | None:
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    clip_start = max(item.start_date, month_start)
    clip_end = min(item.end_date, month_end)
    if clip_start > clip_end:
        return None
    return clip_start, clip_end


def _item_catalog_month_weights(item) -> dict[tuple[int, int], Decimal]:
    center = item.ad_space.shopping_center
    weights: dict[tuple[int, int], Decimal] = {}
    if item.custom_rental_start_enabled and item.custom_rental_start_date:
        anchor = reservation_month_anchor(item.start_date)
        catalog_total = catalog_subtotal_with_custom_start(
            item.monthly_price,
            center,
            item.custom_rental_start_date,
            item.end_date,
        )
        if catalog_total <= 0:
            return weights
        y, m = anchor.year, anchor.month
        clip = _month_clip(item, y, m)
        if clip:
            first_w = line_subtotal_for_center(
                item.monthly_price, center, clip[0], clip[1]
            )
            if y == item.custom_rental_start_date.year and m == item.custom_rental_start_date.month:
                first_w = catalog_subtotal_with_custom_start(
                    item.monthly_price,
                    center,
                    item.custom_rental_start_date,
                    date(y, m, monthrange(y, m)[1]),
                )
            weights[(y, m)] = first_w
        for ym in _iter_calendar_months(item.start_date, item.end_date):
            if ym == (anchor.year, anchor.month):
                continue
            clip = _month_clip(item, ym[0], ym[1])
            if clip:
                weights[ym] = line_subtotal_for_center(
                    item.monthly_price, center, clip[0], clip[1]
                )
        total_w = sum(weights.values(), Decimal("0"))
        if total_w > 0:
            factor = catalog_total / total_w
            weights = {k: (v * factor).quantize(Decimal("0.01")) for k, v in weights.items()}
        return weights

    catalog_total = line_subtotal_for_center(
        item.monthly_price, center, item.start_date, item.end_date
    )
    if catalog_total <= 0:
        return weights
    for ym in _iter_calendar_months(item.start_date, item.end_date):
        clip = _month_clip(item, ym[0], ym[1])
        if clip:
            weights[ym] = line_subtotal_for_center(
                item.monthly_price, center, clip[0], clip[1]
            )
    total_w = sum(weights.values(), Decimal("0"))
    if total_w > 0:
        factor = catalog_total / total_w
        weights = {k: (v * factor).quantize(Decimal("0.01")) for k, v in weights.items()}
    return weights


def order_month_amount_usd(order: Order, year: int, month: int) -> Decimal:
    total = Decimal("0")
    for item in order.items.select_related("ad_space__shopping_center"):
        weights = _item_catalog_month_weights(item)
        w = weights.get((year, month))
        if not w:
            continue
        item_catalog = sum(_item_catalog_month_weights(item).values(), Decimal("0"))
        if item_catalog <= 0:
            continue
        share = (item.subtotal * w / item_catalog).quantize(Decimal("0.01"))
        total += share
    return total.quantize(Decimal("0.01"))


def format_month_label(year: int, month: int) -> str:
    if 1 <= month <= 12:
        return f"{_MONTH_SHORT_ES[month - 1]} {year}"
    return f"{month:02d}/{year}"


def format_months_label(months: list[tuple[int, int]]) -> str:
    return ", ".join(format_month_label(y, m) for y, m in months)


def installment_due_date(months: list[tuple[int, int]]) -> date:
    y, m = months[0]
    return date(y, m, 1)


def format_payment_plan_observation_text(plan: OrderPaymentPlan) -> str:
    installments = list(
        plan.installments.prefetch_related("months").order_by("sequence")
    )
    if not installments:
        return "Pago por partes acordado (sin cuotas configuradas)."

    lines = [
        "FORMA DE PAGO ACORDADA: pago por partes.",
        (
            "La primera cuota habilita la activación del contrato por el periodo "
            "completo reservado; las cuotas restantes se facturarán según el "
            "calendario indicado."
        ),
        "",
    ]
    total = len(installments)
    for inst in installments:
        months = [(m.year, m.month) for m in inst.months.all()]
        months.sort()
        period = format_months_label(months)
        lines.append(
            f"Cuota {inst.sequence} de {total}: {period} — "
            f"vence {inst.due_date.strftime('%d/%m/%Y')} — "
            f"${inst.amount:,.2f} USD sin IVA"
        )
    return "\n".join(lines)


def _validate_installment_months_contiguous(months: list[tuple[int, int]]) -> None:
    if not months:
        raise serializers.ValidationError("Cada cuota debe incluir al menos un mes.")
    months = sorted(months)
    y, m = months[0]
    for y2, m2 in months[1:]:
        if m == 12:
            y, m = y + 1, 1
        else:
            y, m = y, m + 1
        if (y2, m2) != (y, m):
            raise serializers.ValidationError(
                "Los meses de una misma cuota deben ser consecutivos."
            )


def installment_has_invoice(inst: OrderPaymentInstallment) -> bool:
    return bool(
        getattr(inst.invoice_digital, "name", "")
        or getattr(inst.invoice_pdf, "name", "")
    )


def sync_installment_status(inst: OrderPaymentInstallment) -> None:
    has_receipt = bool(getattr(inst.payment_receipt, "name", ""))
    has_invoice = bool(
        getattr(inst.invoice_digital, "name", "")
        or getattr(inst.invoice_pdf, "name", "")
    )
    if has_receipt:
        inst.status = OrderPaymentInstallmentStatus.PAID
    elif has_invoice:
        inst.status = OrderPaymentInstallmentStatus.INVOICED
    else:
        inst.status = OrderPaymentInstallmentStatus.PENDING


def get_payment_plan_payload(order: Order) -> dict:
    editable = order_payment_plan_editable(order)
    calendar_months = [
        {"year": y, "month": m, "label": format_month_label(y, m)}
        for y, m in order_calendar_months(order)
    ]
    try:
        plan = order.payment_plan
    except OrderPaymentPlan.DoesNotExist:
        return {
            "enabled": False,
            "editable": editable,
            "calendar_months": calendar_months,
            "installments": [],
            "observation_text": "",
        }
    installments = []
    for inst in plan.installments.prefetch_related("months").order_by("sequence"):
        months = sorted((m.year, m.month) for m in inst.months.all())
        installments.append(
            {
                "id": inst.id,
                "sequence": inst.sequence,
                "due_date": inst.due_date.isoformat(),
                "amount": str(inst.amount),
                "status": inst.status,
                "status_label": inst.get_status_display(),
                "months": [{"year": y, "month": m} for y, m in months],
                "months_label": format_months_label(months),
                "invoice_pdf_url": inst.invoice_pdf.url if inst.invoice_pdf else None,
                "invoice_digital_url": (
                    inst.invoice_digital.url if inst.invoice_digital else None
                ),
                "invoice_file_url": (
                    inst.invoice_digital.url
                    if inst.invoice_digital
                    else (inst.invoice_pdf.url if inst.invoice_pdf else None)
                ),
                "payment_receipt_url": (
                    inst.payment_receipt.url if inst.payment_receipt else None
                ),
                "activates_contract": inst.sequence == 1,
                "can_generate_invoice": (
                    inst.status == OrderPaymentInstallmentStatus.PENDING
                    and not installment_has_invoice(inst)
                ),
            }
        )
    return {
        "enabled": plan.enabled,
        "editable": editable,
        "calendar_months": calendar_months,
        "installments": installments,
        "observation_text": (
            format_payment_plan_observation_text(plan) if plan.enabled else ""
        ),
    }


def first_installment_has_receipt(order: Order) -> bool:
    try:
        plan = order.payment_plan
    except OrderPaymentPlan.DoesNotExist:
        return False
    if not plan.enabled:
        return False
    first = plan.installments.order_by("sequence").first()
    if first is None:
        return False
    return bool(getattr(first.payment_receipt, "name", ""))


@transaction.atomic
def update_order_payment_plan(
    order: Order,
    *,
    enabled: bool,
    installments: list[dict] | None,
    actor=None,
) -> Order:
    if not order_payment_plan_editable(order):
        raise serializers.ValidationError(
            {
                "detail": (
                    "No puedes modificar el plan de pago cuando el pedido ya está "
                    "activo, vencido o rechazado."
                )
            }
        )

    order = (
        Order.objects.select_for_update()
        .prefetch_related(
            "items__ad_space__shopping_center",
        )
        .get(pk=order.pk)
    )

    if not order.items.exists():
        raise serializers.ValidationError({"detail": "El pedido no tiene líneas."})

    plan, _ = OrderPaymentPlan.objects.get_or_create(order=order)

    if not enabled:
        plan.enabled = False
        plan.save(update_fields=["enabled", "updated_at"])
        _maybe_regenerate_negotiation_pdfs(order)
        return order

    if not installments:
        raise serializers.ValidationError(
            {"installments": "Indica al menos una cuota."}
        )

    expected_months = set(order_calendar_months(order))
    seen_months: set[tuple[int, int]] = set()
    parsed: list[list[tuple[int, int]]] = []

    for idx, row in enumerate(installments, start=1):
        raw_months = row.get("months") or []
        months: list[tuple[int, int]] = []
        for m in raw_months:
            y = int(m["year"])
            mo = int(m["month"])
            if (y, mo) in seen_months:
                raise serializers.ValidationError(
                    {"installments": f"El mes {format_month_label(y, mo)} está repetido."}
                )
            if (y, mo) not in expected_months:
                raise serializers.ValidationError(
                    {
                        "installments": (
                            f"El mes {format_month_label(y, mo)} no pertenece al pedido."
                        )
                    }
                )
            seen_months.add((y, mo))
            months.append((y, mo))
        months.sort()
        _validate_installment_months_contiguous(months)
        parsed.append(months)

    if seen_months != expected_months:
        missing = expected_months - seen_months
        extra = seen_months - expected_months
        if missing:
            labels = ", ".join(format_month_label(y, m) for y, m in sorted(missing))
            raise serializers.ValidationError(
                {"installments": f"Faltan meses por asignar: {labels}."}
            )
        if extra:
            raise serializers.ValidationError(
                {"installments": "Hay meses fuera del periodo del pedido."}
            )

    paid_inst = plan.installments.filter(
        status=OrderPaymentInstallmentStatus.PAID
    ).exists()
    if paid_inst:
        raise serializers.ValidationError(
            {
                "detail": (
                    "No puedes cambiar el plan mientras haya cuotas marcadas como pagadas."
                )
            }
        )

    plan.installments.all().delete()
    plan.enabled = True
    plan.save(update_fields=["enabled", "updated_at"])

    for seq, months in enumerate(parsed, start=1):
        amount = sum(order_month_amount_usd(order, y, m) for y, m in months)
        amount = amount.quantize(Decimal("0.01"))
        inst = OrderPaymentInstallment.objects.create(
            plan=plan,
            sequence=seq,
            due_date=installment_due_date(months),
            amount=amount,
            status=OrderPaymentInstallmentStatus.PENDING,
        )
        OrderPaymentInstallmentMonth.objects.bulk_create(
            [
                OrderPaymentInstallmentMonth(
                    installment=inst, year=y, month=m
                )
                for y, m in months
            ]
        )

    _maybe_regenerate_negotiation_pdfs(order)
    return order


def generate_installment_invoice_if_pending(
    installment: OrderPaymentInstallment,
) -> OrderPaymentInstallment:
    """Genera la nota de cobro del sistema para una cuota sin factura."""
    installment = (
        OrderPaymentInstallment.objects.select_related("plan__order")
        .prefetch_related("months")
        .get(pk=installment.pk)
    )
    if not installment.plan.enabled:
        raise serializers.ValidationError(
            {"detail": "El plan de pago no está activo."}
        )
    if installment.status == OrderPaymentInstallmentStatus.PAID:
        raise serializers.ValidationError(
            {"detail": "Esta cuota ya está pagada."}
        )
    if installment_has_invoice(installment):
        raise serializers.ValidationError(
            {"detail": "Esta cuota ya tiene factura."}
        )
    from apps.orders.utils.document_generation import generate_installment_invoice_pdf

    generate_installment_invoice_pdf(installment)
    installment.refresh_from_db()
    return installment


def invoice_due_payment_installments(
    *,
    reference_date: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Factura cuotas 2+ cuyo vencimiento ya llegó (cron diario).
    La cuota 1 se genera al pasar el pedido a «Facturada».
    """
    ref = reference_date or timezone.localdate()
    qs = (
        OrderPaymentInstallment.objects.filter(
            plan__enabled=True,
            plan__order__status__in=_INSTALLMENT_AUTO_INVOICE_ORDER_STATUSES,
            sequence__gt=1,
            due_date__lte=ref,
            status=OrderPaymentInstallmentStatus.PENDING,
        )
        .select_related("plan__order")
        .prefetch_related("months")
        .order_by("due_date", "sequence", "id")
    )
    pending = [inst for inst in qs if not installment_has_invoice(inst)]
    if dry_run:
        return {
            "would_invoice": len(pending),
            "installment_ids": [inst.pk for inst in pending],
            "reference_date": ref.isoformat(),
        }
    invoiced = 0
    errors: list[dict] = []
    for inst in pending:
        try:
            generate_installment_invoice_if_pending(inst)
            invoiced += 1
        except Exception as exc:
            logger.exception(
                "No se pudo facturar cuota %s del pedido %s",
                inst.pk,
                inst.plan.order_id,
            )
            errors.append(
                {
                    "installment_id": inst.pk,
                    "order_id": inst.plan.order_id,
                    "error": str(exc),
                }
            )
    return {
        "invoiced": invoiced,
        "reference_date": ref.isoformat(),
        "errors": errors,
    }


def _maybe_regenerate_negotiation_pdfs(order: Order) -> None:
    from apps.orders.utils.document_generation import (
        generate_negotiation_and_municipality_pdfs,
    )
    from apps.orders.utils.validators import order_should_regenerate_negotiation_pdf

    if order_should_regenerate_negotiation_pdf(order):
        generate_negotiation_and_municipality_pdfs(order)
