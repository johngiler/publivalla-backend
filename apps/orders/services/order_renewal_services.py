"""Renovación de contrato: solicitud del cliente y extensión del periodo al aprobar."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework import serializers

from apps.ad_spaces.utils.availability_calendar import year_months_occupied
from apps.ad_spaces.utils.marketplace_availability import sync_ad_space_commercial_status
from apps.orders.models import (
    OrderItem,
    OrderPaymentInstallment,
    OrderPaymentInstallmentMonth,
    OrderPaymentInstallmentStatus,
    OrderPaymentPlan,
    OrderRenewal,
    OrderRenewalMonth,
    OrderRenewalStatus,
    OrderStatus,
)
from apps.orders.services.order_services import log_order_status_transition
from apps.orders.services.payment_plan_services import (
    format_month_label,
    installment_due_date,
    order_uses_split_payment,
)
from apps.orders.utils.rental_billing import line_subtotal_for_center

_OPEN_RENEWAL_STATUSES = frozenset(
    {
        OrderRenewalStatus.PENDING,
    }
)


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def first_renewal_month_after(end_date: date) -> tuple[int, int]:
    return _next_month(end_date.year, end_date.month)


def _validate_months_contiguous_from(
    months: list[tuple[int, int]],
    *,
    start_after: date,
) -> list[tuple[int, int]]:
    if not months:
        raise serializers.ValidationError(
            {"months": "Selecciona al menos un mes para renovar."}
        )
    months = sorted(set(months))
    expected = first_renewal_month_after(start_after)
    if months[0] != expected:
        raise serializers.ValidationError(
            {
                "months": (
                    "La renovación debe empezar el mes siguiente al fin del contrato "
                    f"({format_month_label(*expected)})."
                )
            }
        )
    y, m = months[0]
    for y2, m2 in months[1:]:
        y, m = _next_month(y, m)
        if (y2, m2) != (y, m):
            raise serializers.ValidationError(
                {"months": "Los meses de renovación deben ser consecutivos."}
            )
    return months


def _month_is_free(
    ad_space_id: int,
    year: int,
    month: int,
    *,
    exclude_renewal_id: int | None = None,
) -> bool:
    """Libre en calendario (pedidos + bloqueos) y sin otra renovación pendiente."""
    if month < 1 or month > 12:
        return False
    occupied = year_months_occupied(
        ad_space_id, year, include_pending_renewals=False
    )
    if occupied[month - 1]:
        return False
    qs = OrderRenewalMonth.objects.filter(
        renewal__status=OrderRenewalStatus.PENDING,
        renewal__order_item__ad_space_id=ad_space_id,
        year=year,
        month=month,
    )
    if exclude_renewal_id is not None:
        qs = qs.exclude(renewal_id=exclude_renewal_id)
    return not qs.exists()


def count_consecutive_free_renewal_months(
    ad_space_id: int,
    *,
    start_after: date,
    max_months: int = 12,
) -> int:
    """Cuántos meses consecutivos libres hay desde el mes siguiente al fin del contrato."""
    y, m = first_renewal_month_after(start_after)
    n = 0
    for _ in range(max(0, max_months)):
        if not _month_is_free(ad_space_id, y, m):
            break
        n += 1
        y, m = _next_month(y, m)
    return n


def amount_for_renewal_months(item: OrderItem, months: list[tuple[int, int]]) -> Decimal:
    center = item.ad_space.shopping_center
    total = Decimal("0")
    for year, month in months:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        total += line_subtotal_for_center(item.monthly_price, center, start, end)
    return total.quantize(Decimal("0.01"))


def renewal_payload(renewal: OrderRenewal) -> dict:
    months = sorted((m.year, m.month) for m in renewal.months.all())
    return {
        "id": renewal.id,
        "order_item_id": renewal.order_item_id,
        "order_id": renewal.order_item.order_id,
        "status": renewal.status,
        "status_label": renewal.get_status_display(),
        "amount": str(renewal.amount),
        "months": [{"year": y, "month": m} for y, m in months],
        "months_label": ", ".join(format_month_label(y, m) for y, m in months),
        "client_note": renewal.client_note or "",
        "admin_note": renewal.admin_note or "",
        "payment_receipt_url": (
            renewal.payment_receipt.url if renewal.payment_receipt else None
        ),
        "permit_file_url": renewal.permit_file.url if renewal.permit_file else None,
        "payment_confirmed": bool(renewal.payment_confirmed_at),
        "created_at": renewal.created_at.isoformat() if renewal.created_at else None,
        "reviewed_at": renewal.reviewed_at.isoformat() if renewal.reviewed_at else None,
        "applied_at": renewal.applied_at.isoformat() if renewal.applied_at else None,
    }


def latest_open_renewal(order_item_id: int) -> OrderRenewal | None:
    return (
        OrderRenewal.objects.filter(
            order_item_id=order_item_id,
            status__in=_OPEN_RENEWAL_STATUSES,
        )
        .prefetch_related("months")
        .order_by("-created_at")
        .first()
    )


def latest_completed_renewal(order_item_id: int) -> OrderRenewal | None:
    return (
        OrderRenewal.objects.filter(
            order_item_id=order_item_id,
            status=OrderRenewalStatus.COMPLETED,
        )
        .prefetch_related("months")
        .order_by("-applied_at", "-id")
        .first()
    )


def completed_renewal_has_started(
    renewal: OrderRenewal | None,
    *,
    today: date | None = None,
) -> bool:
    """True si no hay renovación aplicada, o si su primer mes ya comenzó."""
    if renewal is None:
        return True
    today = today or timezone.localdate()
    months = sorted((m.year, m.month) for m in renewal.months.all())
    if not months:
        return True
    y, m = months[0]
    return date(y, m, 1) <= today


def item_allows_renewal_request(
    order_item: OrderItem,
    *,
    today: date | None = None,
) -> bool:
    """
    Cliente solo puede pedir renovación si el contrato está en curso (no próximo),
    sin solicitud pendiente, y sin una extensión ya aplicada que aún no arranca.
    """
    today = today or timezone.localdate()
    order = order_item.order
    if order.status != OrderStatus.ACTIVE or order.ended_early:
        return False
    if order_item.start_date > today or order_item.end_date < today:
        return False
    if latest_open_renewal(order_item.pk):
        return False
    return completed_renewal_has_started(
        latest_completed_renewal(order_item.pk), today=today
    )


def assert_item_allows_renewal_request(
    order_item: OrderItem,
    *,
    today: date | None = None,
) -> None:
    today = today or timezone.localdate()
    order = order_item.order
    if order.status != OrderStatus.ACTIVE:
        raise serializers.ValidationError(
            {"detail": "Solo puedes renovar un contrato que está activo."}
        )
    if order.ended_early:
        raise serializers.ValidationError(
            {"detail": "Este contrato tuvo cierre anticipado y no admite renovación."}
        )
    if order_item.start_date > today:
        raise serializers.ValidationError(
            {
                "detail": (
                    "Solo puedes solicitar renovación cuando el contrato ya está en curso."
                )
            }
        )
    if order_item.end_date < today:
        raise serializers.ValidationError(
            {"detail": "Este contrato ya finalizó y no admite renovación."}
        )
    if latest_open_renewal(order_item.pk):
        raise serializers.ValidationError(
            {"detail": "Ya hay una solicitud de renovación pendiente para esta toma."}
        )
    completed = latest_completed_renewal(order_item.pk)
    if not completed_renewal_has_started(completed, today=today):
        raise serializers.ValidationError(
            {
                "detail": (
                    "Ya hay una extensión aplicada que aún no comienza. "
                    "Podrás solicitar otra cuando ese periodo arranque."
                )
            }
        )


@transaction.atomic
def create_renewal_request(
    order_item: OrderItem,
    *,
    months: list[tuple[int, int]],
    actor: AbstractBaseUser | None,
    client_note: str = "",
) -> OrderRenewal:
    order_item = (
        OrderItem.objects.select_for_update()
        .select_related("order", "ad_space__shopping_center")
        .get(pk=order_item.pk)
    )
    assert_item_allows_renewal_request(order_item)
    order = order_item.order

    months = _validate_months_contiguous_from(months, start_after=order_item.end_date)
    for year, month in months:
        if not _month_is_free(order_item.ad_space_id, year, month):
            raise serializers.ValidationError(
                {
                    "months": (
                        f"El mes {format_month_label(year, month)} no está disponible."
                    )
                }
            )

    amount = amount_for_renewal_months(order_item, months)
    renewal = OrderRenewal.objects.create(
        order_item=order_item,
        status=OrderRenewalStatus.PENDING,
        amount=amount,
        client_note=(client_note or "").strip()[:500],
        requested_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    OrderRenewalMonth.objects.bulk_create(
        [
            OrderRenewalMonth(renewal=renewal, year=y, month=m)
            for y, m in months
        ]
    )
    log_order_status_transition(
        order,
        order.status,
        order.status,
        actor=actor,
        note=(
            f"Solicitud de renovación #{renewal.pk}: "
            f"{', '.join(format_month_label(y, m) for y, m in months)} "
            f"(${amount:,.2f} sin IVA)."
        ),
    )
    renewal = (
        OrderRenewal.objects.select_related(
            "order_item__order__client__workspace",
            "order_item__ad_space",
        )
        .prefetch_related("months")
        .get(pk=renewal.pk)
    )
    from apps.orders.tasks import schedule_notify_contract_renewal_requested

    schedule_notify_contract_renewal_requested(
        renewal.pk,
        actor_id=getattr(actor, "pk", None),
    )
    return renewal


def _append_split_installments(
    order,
    item: OrderItem,
    months: list[tuple[int, int]],
) -> None:
    plan, _ = OrderPaymentPlan.objects.get_or_create(order=order)
    if not plan.enabled:
        plan.enabled = True
        plan.save(update_fields=["enabled", "updated_at"])

    last_seq = plan.installments.aggregate(m=Max("sequence")).get("m") or 0
    for offset, (year, month) in enumerate(months):
        month_amount = amount_for_renewal_months(item, [(year, month)])
        inst = OrderPaymentInstallment.objects.create(
            plan=plan,
            sequence=last_seq + offset + 1,
            due_date=installment_due_date([(year, month)]),
            amount=month_amount,
            status=OrderPaymentInstallmentStatus.PENDING,
        )
        OrderPaymentInstallmentMonth.objects.create(
            installment=inst, year=year, month=month
        )


@transaction.atomic
def approve_and_apply_renewal(
    renewal: OrderRenewal,
    *,
    actor: AbstractBaseUser | None,
    admin_note: str = "",
) -> OrderRenewal:
    renewal = (
        OrderRenewal.objects.select_for_update()
        .select_related("order_item__order", "order_item__ad_space__shopping_center")
        .prefetch_related("months")
        .get(pk=renewal.pk)
    )
    if renewal.status != OrderRenewalStatus.PENDING:
        raise serializers.ValidationError(
            {"detail": "Solo puedes aprobar una renovación pendiente."}
        )

    item = (
        OrderItem.objects.select_for_update()
        .select_related("order", "ad_space__shopping_center")
        .get(pk=renewal.order_item_id)
    )
    order = item.order
    if order.status != OrderStatus.ACTIVE:
        raise serializers.ValidationError(
            {"detail": "El pedido ya no está activo; no se puede aplicar la renovación."}
        )

    months = sorted((m.year, m.month) for m in renewal.months.all())
    months = _validate_months_contiguous_from(months, start_after=item.end_date)
    for year, month in months:
        if not _month_is_free(
            item.ad_space_id,
            year,
            month,
            exclude_renewal_id=renewal.pk,
        ):
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"El mes {format_month_label(year, month)} ya no está disponible."
                    )
                }
            )

    amount = amount_for_renewal_months(item, months)
    last_y, last_m = months[-1]
    new_end = date(last_y, last_m, monthrange(last_y, last_m)[1])

    item.end_date = new_end
    item.subtotal = (Decimal(item.subtotal) + amount).quantize(Decimal("0.01"))
    if item.original_subtotal is not None:
        item.original_subtotal = (
            Decimal(item.original_subtotal) + amount
        ).quantize(Decimal("0.01"))
    item.save(
        update_fields=["end_date", "subtotal", "original_subtotal", "updated_at"]
    )

    order.total_amount = (
        Decimal(order.total_amount or 0) + amount
    ).quantize(Decimal("0.01"))
    order.save(update_fields=["total_amount", "updated_at"])

    if order_uses_split_payment(order):
        _append_split_installments(order, item, months)

    now = timezone.now()
    renewal.status = OrderRenewalStatus.COMPLETED
    renewal.amount = amount
    renewal.admin_note = (admin_note or "").strip()[:500]
    renewal.reviewed_by = actor if getattr(actor, "is_authenticated", False) else None
    renewal.reviewed_at = now
    renewal.applied_at = now
    renewal.save(
        update_fields=[
            "status",
            "amount",
            "admin_note",
            "reviewed_by",
            "reviewed_at",
            "applied_at",
            "updated_at",
        ]
    )

    log_order_status_transition(
        order,
        order.status,
        order.status,
        actor=actor,
        note=(
            f"Renovación #{renewal.pk} aplicada: periodo hasta {new_end.isoformat()}, "
            f"+${amount:,.2f} sin IVA "
            f"({', '.join(format_month_label(y, m) for y, m in months)})."
        ),
    )
    sync_ad_space_commercial_status(item.ad_space_id, force_calendar=True)
    return (
        OrderRenewal.objects.select_related("order_item__order")
        .prefetch_related("months")
        .get(pk=renewal.pk)
    )


@transaction.atomic
def reject_renewal(
    renewal: OrderRenewal,
    *,
    actor: AbstractBaseUser | None,
    admin_note: str = "",
) -> OrderRenewal:
    renewal = OrderRenewal.objects.select_for_update().select_related(
        "order_item__order"
    ).get(pk=renewal.pk)
    if renewal.status != OrderRenewalStatus.PENDING:
        raise serializers.ValidationError(
            {"detail": "Solo puedes rechazar una renovación pendiente."}
        )
    renewal.status = OrderRenewalStatus.REJECTED
    renewal.admin_note = (admin_note or "").strip()[:500]
    renewal.reviewed_by = actor if getattr(actor, "is_authenticated", False) else None
    renewal.reviewed_at = timezone.now()
    renewal.save(
        update_fields=[
            "status",
            "admin_note",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    order = renewal.order_item.order
    log_order_status_transition(
        order,
        order.status,
        order.status,
        actor=actor,
        note=f"Renovación #{renewal.pk} rechazada.",
    )
    return renewal


@transaction.atomic
def confirm_renewal_payment(
    renewal: OrderRenewal,
    *,
    actor: AbstractBaseUser | None,
) -> OrderRenewal:
    renewal = OrderRenewal.objects.select_for_update().get(pk=renewal.pk)
    if renewal.status != OrderRenewalStatus.COMPLETED:
        raise serializers.ValidationError(
            {"detail": "Solo puedes confirmar el pago de una renovación ya aplicada."}
        )
    if not renewal.payment_receipt:
        raise serializers.ValidationError(
            {"detail": "Falta el comprobante de la renovación."}
        )
    if renewal.payment_confirmed_at:
        return renewal
    renewal.payment_confirmed_at = timezone.now()
    renewal.save(update_fields=["payment_confirmed_at", "updated_at"])
    order = renewal.order_item.order
    log_order_status_transition(
        order,
        order.status,
        order.status,
        actor=actor,
        note=f"Pago de renovación #{renewal.pk} confirmado.",
    )
    return renewal
