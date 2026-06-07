from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone

from apps.orders.models import Order, OrderStatus, OrderStatusEvent, OrderItem
from apps.orders.services.order_hold_services import (
    NOTE_HOLD_ON_SUBMIT,
    apply_hold_on_order_submit,
)
from apps.orders.utils.validators import (
    MIN_RESERVATION_CALENDAR_MONTHS,
    ad_space_allows_marketplace_reservation,
    contract_meets_min_months,
    line_subtotal,
    order_item_conflicts,
    rental_start_allowed_for_marketplace,
)

AUTO_EXPIRE_NOTE = (
    "Vencimiento automático: la última línea del contrato ya superó su fecha de fin."
)

logger = logging.getLogger(__name__)


def log_order_status_transition(
    order: Order,
    from_status: str,
    to_status: str,
    *,
    actor: AbstractBaseUser | None = None,
    note: str = "",
    created_at=None,
) -> OrderStatusEvent:
    """Registra un paso en la línea de tiempo de la orden."""
    ev = OrderStatusEvent.objects.create(
        order=order,
        from_status=from_status or "",
        to_status=to_status,
        actor=actor,
        note=note or "",
        created_at=created_at if created_at is not None else timezone.now(),
    )
    order_id = order.pk
    from_s = from_status or ""
    actor_id = getattr(actor, "pk", None) if actor is not None else None

    def enqueue_status_emails() -> None:
        to_s = (to_status or "").strip()
        if to_s == OrderStatus.DRAFT or from_s == to_s:
            return
        from apps.clients.utils.marketplace_user import client_has_marketplace_user
        from apps.orders.tasks import schedule_send_order_status_emails

        skip_client = to_s == OrderStatus.CLIENT_APPROVED and not client_has_marketplace_user(
            order.client
        )
        schedule_send_order_status_emails(
            order_id,
            from_s,
            to_status,
            actor_id=actor_id,
            skip_client_status_email=skip_client,
        )

    transaction.on_commit(enqueue_status_emails)
    return ev


def submit_draft_order(order: Order, *, actor: AbstractBaseUser | None = None) -> Order:
    """
    Pasa una orden de borrador a enviada (misma lógica que POST .../submit/).
    Lanza ValidationError de DRF si no aplica.
    """
    from rest_framework import serializers

    if order.status != OrderStatus.DRAFT:
        raise serializers.ValidationError({"detail": "Solo se pueden enviar órdenes en borrador."})

    from apps.clients.validators import client_has_representative_fields

    order = Order.objects.select_related("client").get(pk=order.pk)
    if not client_has_representative_fields(order.client):
        raise serializers.ValidationError(
            {
                "detail": (
                    "Completa el representante legal y su cédula en Mi empresa "
                    "antes de enviar la solicitud."
                ),
            }
        )

    if not (
        (order.promotion_brand or "").strip()
        and (order.campaign_concept or "").strip()
        and (order.activity_description or "").strip()
    ):
        raise serializers.ValidationError(
            {
                "detail": (
                    "Completa la información adicional de la reserva "
                    "(marca, campaña y descripción de la actividad) antes de enviar."
                ),
            }
        )

    from apps.orders.utils.rental_billing import (
        contract_meets_minimum,
        line_subtotal_for_center,
        min_units_label,
        rental_start_allowed,
    )

    for item in order.items.select_related("ad_space", "ad_space__shopping_center"):
        center = item.ad_space.shopping_center
        unit = center.rental_billing_unit
        if not rental_start_allowed(unit, item.start_date):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "La fecha de inicio no puede ser hoy ni un día pasado."
                        if unit == "calendar_day"
                        else (
                            "La fecha de inicio no puede caer en un mes pasado. "
                            "El mes en curso solo está disponible hasta el día 15."
                        )
                    ),
                }
            )
        if not contract_meets_minimum(unit, item.start_date, item.end_date):
            n, label = min_units_label(unit)
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"La línea {item.ad_space.code} no cumple el mínimo de {n} {label}."
                    ),
                }
            )
        if not ad_space_allows_marketplace_reservation(item.ad_space):
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"La toma {item.ad_space.code} no admite enviar la solicitud "
                        f"(estado: {item.ad_space.get_status_display()}). "
                        "Quítala del carrito o elige otra toma."
                    ),
                }
            )
        if order_item_conflicts(
            item.ad_space_id,
            item.start_date,
            item.end_date,
            exclude_order_id=order.id,
        ):
            title = (item.ad_space.name or "").strip() or "esta toma"
            raise serializers.ValidationError(
                {
                    "detail": (f'Las fechas de «{title}» chocan con otra reserva o bloqueo.'),
                }
            )

    total = Decimal("0")

    for item in order.items.select_related("ad_space", "ad_space__shopping_center"):
        monthly = item.ad_space.monthly_price_usd
        sub = line_subtotal_for_center(
            monthly,
            item.ad_space.shopping_center,
            item.start_date,
            item.end_date,
        )
        item.monthly_price = monthly
        item.subtotal = sub
        item.original_subtotal = sub
        item.save(update_fields=["monthly_price", "subtotal", "original_subtotal"])
        total += sub
    order.total_amount = total.quantize(Decimal("0.01"))
    order.status = OrderStatus.SUBMITTED
    order.submitted_at = timezone.now()
    order.save(
        update_fields=[
            "total_amount",
            "status",
            "submitted_at",
        ]
    )
    apply_hold_on_order_submit(order)

    log_order_status_transition(
        order,
        OrderStatus.DRAFT,
        OrderStatus.SUBMITTED,
        actor=actor,
        note=NOTE_HOLD_ON_SUBMIT,
    )
    order.refresh_from_db()
    return order


def order_line_pricing_totals(order: Order) -> tuple[Decimal, Decimal]:
    """(catalog_subtotal, discount_total) sin IVA."""
    catalog = Decimal("0")
    discount = Decimal("0")
    for item in order.items.all():
        orig = item.original_subtotal if item.original_subtotal is not None else item.subtotal
        catalog += orig
        diff = (orig - item.subtotal).quantize(Decimal("0.01"))
        if diff > 0:
            discount += diff
    return catalog.quantize(Decimal("0.01")), discount.quantize(Decimal("0.01"))


@transaction.atomic
def update_order_line_pricing(
    order: Order,
    *,
    items: list[dict],
    actor: AbstractBaseUser | None = None,
) -> Order:
    """Actualiza subtotales acordados por toma (solo descuentos, antes de facturar)."""
    from rest_framework import serializers

    from apps.orders.utils.validators import (
        order_line_pricing_editable,
        order_should_regenerate_negotiation_pdf,
    )

    if not order_line_pricing_editable(order):
        raise serializers.ValidationError(
            {
                "detail": (
                    "Solo puedes ajustar precios e inicio de alquiler tras aprobar la solicitud "
                    "y antes de facturar."
                )
            }
        )

    order = (
        Order.objects.select_for_update()
        .prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.select_related("ad_space"),
            )
        )
        .get(pk=order.pk)
    )
    by_id = {it.pk: it for it in order.items.all()}
    if not by_id:
        raise serializers.ValidationError({"detail": "El pedido no tiene líneas."})

    from apps.orders.utils.custom_rental_start import (
        agreed_subtotal_with_custom_start,
        catalog_subtotal_with_custom_start,
        reservation_month_anchor,
        validate_custom_rental_start_date,
    )
    from apps.orders.utils.rental_billing import line_subtotal_for_center

    seen: set[int] = set()
    total = Decimal("0")
    ref_today = timezone.localdate()

    for row in items:
        item_id = row["id"]
        if item_id in seen:
            raise serializers.ValidationError(
                {"items": "Hay líneas duplicadas en la solicitud."}
            )
        seen.add(item_id)
        item = by_id.get(item_id)
        if item is None:
            raise serializers.ValidationError(
                {"items": f"La línea {item_id} no pertenece a este pedido."}
            )

        center = item.ad_space.shopping_center
        rental_start_in_payload = "custom_rental_start_enabled" in row
        custom_enabled = (
            bool(row["custom_rental_start_enabled"])
            if rental_start_in_payload
            else item.custom_rental_start_enabled
        )
        update_fields = ["subtotal", "updated_at"]

        if rental_start_in_payload and custom_enabled:
            custom_date = row.get("custom_rental_start_date")
            first_month = row.get("first_month_agreed_subtotal")
            if custom_date is None:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"Indica la fecha de inicio de alquiler para {item.ad_space.code}."
                        )
                    }
                )
            if first_month is None:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"Indica el importe del mes inicial para {item.ad_space.code}."
                        )
                    }
                )
            anchor = reservation_month_anchor(item.start_date)
            try:
                validate_custom_rental_start_date(anchor, custom_date, ref=ref_today)
            except ValueError as exc:
                raise serializers.ValidationError({"items": str(exc)}) from exc

            catalog = catalog_subtotal_with_custom_start(
                item.monthly_price,
                center,
                custom_date,
                item.end_date,
            )
            computed_sub = agreed_subtotal_with_custom_start(
                first_month,
                item.monthly_price,
                center,
                custom_date,
                item.end_date,
            )
            sub = row.get("subtotal", computed_sub)
            if sub > catalog:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"El importe acordado de {item.ad_space.code} no puede superar "
                            f"el subtotal de catálogo (${catalog:,.2f})."
                        )
                    }
                )
            item.custom_rental_start_enabled = True
            item.custom_rental_start_date = custom_date
            item.first_month_agreed_subtotal = first_month
            item.start_date = custom_date
            item.original_subtotal = catalog
            item.subtotal = sub
            update_fields.extend(
                [
                    "custom_rental_start_enabled",
                    "custom_rental_start_date",
                    "first_month_agreed_subtotal",
                    "start_date",
                    "original_subtotal",
                ]
            )
        elif rental_start_in_payload and not custom_enabled:
            if item.custom_rental_start_enabled:
                item.start_date = reservation_month_anchor(item.start_date)
                item.custom_rental_start_enabled = False
                item.custom_rental_start_date = None
                item.first_month_agreed_subtotal = None
                item.original_subtotal = line_subtotal_for_center(
                    item.monthly_price,
                    center,
                    item.start_date,
                    item.end_date,
                )
                update_fields.extend(
                    [
                        "custom_rental_start_enabled",
                        "custom_rental_start_date",
                        "first_month_agreed_subtotal",
                        "start_date",
                        "original_subtotal",
                    ]
                )
            if "subtotal" not in row:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"Indica el subtotal acordado de {item.ad_space.code}."
                        )
                    }
                )
            sub = row["subtotal"]
            orig = (
                item.original_subtotal
                if item.original_subtotal is not None
                else item.subtotal
            )
            if sub > orig:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"El importe acordado de {item.ad_space.code} no puede superar "
                            f"el subtotal de catálogo (${orig:,.2f})."
                        )
                    }
                )
            item.subtotal = sub
        else:
            if "subtotal" not in row:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"Indica el subtotal acordado de {item.ad_space.code}."
                        )
                    }
                )
            sub = row["subtotal"]
            orig = (
                item.original_subtotal
                if item.original_subtotal is not None
                else item.subtotal
            )
            if sub > orig:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"El importe acordado de {item.ad_space.code} no puede superar "
                            f"el subtotal de catálogo (${orig:,.2f})."
                        )
                    }
                )
            item.subtotal = sub

        item.save(update_fields=update_fields)
        total += item.subtotal

    if seen != set(by_id.keys()):
        raise serializers.ValidationError(
            {"items": "Debes indicar el subtotal acordado de todas las líneas del pedido."}
        )

    order.total_amount = total.quantize(Decimal("0.01"))
    order.save(update_fields=["total_amount", "updated_at"])

    # Recargar sin caché de prefetch (los ítems ya se guardaron en BD).
    order = (
        Order.objects.prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.select_related("ad_space"),
            )
        )
        .get(pk=order.pk)
    )

    _, discount = order_line_pricing_totals(order)
    note = "Precios acordados actualizados."
    if discount > 0:
        note = f"Precios acordados actualizados (descuento total ${discount:,.2f} sin IVA)."
    else:
        note = "Precios acordados actualizados (sin descuento)."

    if order_should_regenerate_negotiation_pdf(order):
        from apps.orders.utils.document_generation import (
            generate_negotiation_and_municipality_pdfs,
        )

        generate_negotiation_and_municipality_pdfs(order)
        note = (
            f"{note} Hoja de negociación regenerada; el cliente debe descargarla y firmarla de nuevo."
        )

    log_order_status_transition(
        order,
        order.status,
        order.status,
        actor=actor,
        note=note,
    )
    order.refresh_from_db()
    return order


def expire_active_orders_after_contract_end(
    *,
    today: date | None = None,
    dry_run: bool = False,
    actor: AbstractBaseUser | None = None,
) -> dict:
    """
    Pasa a ``expired`` las órdenes en ``active`` cuya fecha de fin más tardía (entre ítems)
    es anterior a ``today``. Las líneas no tienen estado propio: al vencer la orden dejan de
    contar en ``PIPELINE_STATUSES`` y el calendario deja de reservar esas fechas.

    Idempotente: órdenes ya ``expired`` no se tocan.

    :param today: Fecha de corte (por defecto ``timezone.localdate()``).
    :param dry_run: Si True, no escribe en BD; devuelve los IDs que se vencerían.
    :param actor: Usuario que dispara el cambio (None = tarea automática).
    :return: ``{"expired": int, "order_ids": list[int]}`` o en dry_run ``{"would_expire": int, "order_ids": ...}``.
    """
    ref = today if today is not None else timezone.localdate()
    candidate_ids = list(
        Order.objects.filter(status=OrderStatus.ACTIVE)
        .annotate(last_end=Max("items__end_date"))
        .filter(last_end__isnull=False, last_end__lt=ref)
        .values_list("pk", flat=True)
        .order_by("pk")
    )
    if dry_run:
        return {"would_expire": len(candidate_ids), "order_ids": candidate_ids}

    expired_n = 0
    for pk in candidate_ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(pk=pk).first()
            if order is None or order.status != OrderStatus.ACTIVE:
                continue
            agg = order.items.aggregate(m=Max("end_date"))
            last_end = agg["m"]
            if last_end is None or last_end >= ref:
                continue
            prev = order.status
            Order.objects.filter(pk=pk, status=OrderStatus.ACTIVE).update(status=OrderStatus.EXPIRED)
            order.refresh_from_db()
            log_order_status_transition(
                order,
                prev,
                OrderStatus.EXPIRED,
                actor=actor,
                note=AUTO_EXPIRE_NOTE,
            )
            expired_n += 1
    return {"expired": expired_n, "order_ids": candidate_ids}
