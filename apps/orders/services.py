from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.orders.models import Order, OrderStatus, OrderStatusEvent
from apps.orders.validators import (
    MIN_RESERVATION_CALENDAR_MONTHS,
    ad_space_allows_marketplace_reservation,
    contract_meets_min_months,
    hold_expires_at_from_now,
    line_subtotal,
    order_item_conflicts,
    rental_start_allowed_for_marketplace,
)

AUTO_EXPIRE_NOTE = (
    "Vencimiento automático: la última línea del contrato ya superó su fecha de fin."
)

logger = logging.getLogger(__name__)


def default_invoice_number_for_order(order: Order) -> str:
    """
    Número de factura sugerido al pasar a «Facturada» si no se indicó uno.
    Basado en el código de pedido (#SLUG-ORDER-…) o en el id; recortado a 64 caracteres (campo BD).
    """
    code = (order.code or "").strip().replace("#", "").replace("/", "-").replace(" ", "")
    if code:
        base = f"FAC-{code}"
    else:
        base = f"FAC-{order.pk:06d}"
    return base[:64]


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
    try:
        from apps.orders.email_notifications import try_send_order_status_emails

        try_send_order_status_emails(order, from_status or "", to_status)
    except Exception:
        logger.exception(
            "Notificación por correo omitida (pedido %s → %s).",
            order.pk,
            to_status,
        )
    return ev


def submit_draft_order(order: Order, *, actor: AbstractBaseUser | None = None) -> Order:
    """
    Pasa una orden de borrador a enviada (misma lógica que POST .../submit/).
    Lanza ValidationError de DRF si no aplica.
    """
    from rest_framework import serializers

    if order.status != OrderStatus.DRAFT:
        raise serializers.ValidationError({"detail": "Solo se pueden enviar órdenes en borrador."})

    for item in order.items.select_related("ad_space"):
        if not rental_start_allowed_for_marketplace(item.start_date):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "La fecha de inicio no puede caer en un mes pasado ni en el mes en curso. "
                        "Elige un período que comience desde el próximo mes."
                    ),
                }
            )
        if not contract_meets_min_months(item.start_date, item.end_date):
            m = MIN_RESERVATION_CALENDAR_MONTHS
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"La línea {item.ad_space.code} no cumple el mínimo de "
                        f"{m} {'mes' if m == 1 else 'meses'} de calendario."
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
            title = (item.ad_space.title or "").strip() or "esta toma"
            raise serializers.ValidationError(
                {
                    "detail": (f'Las fechas de «{title}» chocan con otra reserva o bloqueo.'),
                }
            )

    total = Decimal("0")
    for item in order.items.select_related("ad_space"):
        monthly = item.ad_space.monthly_price_usd
        sub = line_subtotal(monthly, item.start_date, item.end_date)
        item.monthly_price = monthly
        item.subtotal = sub
        item.save(update_fields=["monthly_price", "subtotal"])
        total += sub
    order.total_amount = total.quantize(Decimal("0.01"))
    order.status = OrderStatus.SUBMITTED
    order.submitted_at = timezone.now()
    order.hold_expires_at = hold_expires_at_from_now(72)
    order.save(
        update_fields=[
            "total_amount",
            "status",
            "submitted_at",
            "hold_expires_at",
        ]
    )

    log_order_status_transition(
        order,
        OrderStatus.DRAFT,
        OrderStatus.SUBMITTED,
        actor=actor,
        note="Solicitud enviada por el cliente.",
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
