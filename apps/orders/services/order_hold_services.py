"""Reserva temporal (hold 72 h) al enviar pedido y liberación al vencer o cancelar."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from apps.ad_spaces.models import AdSpace, AdSpaceStatus
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.orders.utils.validators import PIPELINE_STATUSES, hold_expires_at_from_now

HOLD_DURATION_HOURS = int(getattr(settings, "ORDER_HOLD_DURATION_HOURS", 72))

NOTE_HOLD_ON_SUBMIT = (
    "Solicitud enviada. Las tomas quedan reservadas durante 72 horas mientras el equipo revisa."
)
NOTE_CANCELLED_BY_TEAM = "Pedido cancelado. Se liberó la reserva de las tomas."
NOTE_HOLD_EXPIRED = (
    "Plazo de reserva de 72 horas vencido sin respuesta del equipo. "
    "El pedido se canceló y las tomas volvieron a estar disponibles."
)


def order_hold_is_active(order: Order, *, ref=None) -> bool:
    """True si el pedido sigue en ventana de hold (estado API «enviada» + fecha futura)."""
    if order.status != OrderStatus.SUBMITTED:
        return False
    exp = order.hold_expires_at
    if exp is None:
        return False
    now = ref if ref is not None else timezone.now()
    return exp > now


def order_display_status_label(order: Order, *, ref=None) -> str:
    if order_hold_is_active(order, ref=ref):
        return "Reservado"
    return order.get_status_display()


def _other_pipeline_orders_for_space(ad_space_id: int, *, exclude_order_id: int) -> bool:
    return (
        OrderItem.objects.filter(
            ad_space_id=ad_space_id,
            order__status__in=PIPELINE_STATUSES,
        )
        .exclude(order_id=exclude_order_id)
        .exists()
    )


def reserve_ad_spaces_for_order(order: Order) -> list[int]:
    """Marca tomas disponibles como «reservado» mientras dura el hold."""
    updated: list[int] = []
    for item in order.items.select_related("ad_space"):
        ad = item.ad_space
        if ad.status != AdSpaceStatus.AVAILABLE:
            continue
        AdSpace.objects.filter(pk=ad.pk, status=AdSpaceStatus.AVAILABLE).update(
            status=AdSpaceStatus.RESERVED
        )
        updated.append(ad.pk)
    return updated


def release_reserved_ad_spaces_for_order(order: Order) -> list[int]:
    """Devuelve a «disponible» las tomas reservadas por este pedido si no hay otro pipeline."""
    released: list[int] = []
    for item in order.items.select_related("ad_space"):
        ad = item.ad_space
        if ad.status != AdSpaceStatus.RESERVED:
            continue
        if _other_pipeline_orders_for_space(ad.pk, exclude_order_id=order.pk):
            continue
        AdSpace.objects.filter(pk=ad.pk, status=AdSpaceStatus.RESERVED).update(
            status=AdSpaceStatus.AVAILABLE
        )
        released.append(ad.pk)
    return released


@transaction.atomic
def apply_hold_on_order_submit(order: Order) -> None:
    order.hold_expires_at = hold_expires_at_from_now(HOLD_DURATION_HOURS)
    order.save(update_fields=["hold_expires_at", "updated_at"])
    reserve_ad_spaces_for_order(order)


@transaction.atomic
def cancel_order_releasing_hold(
    order: Order,
    *,
    actor: AbstractBaseUser | None = None,
    note: str,
) -> Order:
    if order.status == OrderStatus.CANCELLED:
        return order
    prev = order.status
    order.status = OrderStatus.CANCELLED
    order.hold_expires_at = None
    order.save(update_fields=["status", "hold_expires_at", "updated_at"])
    release_reserved_ad_spaces_for_order(order)
    from apps.orders.services.order_services import log_order_status_transition

    log_order_status_transition(
        order,
        prev,
        OrderStatus.CANCELLED,
        actor=actor,
        note=note,
    )
    order.refresh_from_db()
    return order


def on_order_status_changed(
    order: Order,
    prev_status: str,
    new_status: str,
    *,
    actor: AbstractBaseUser | None = None,
) -> None:
    """Efectos colaterales al cambiar estado (p. ej. liberar hold al cancelar)."""
    if new_status == OrderStatus.CANCELLED and prev_status != OrderStatus.CANCELLED:
        release_reserved_ad_spaces_for_order(order)
        if order.hold_expires_at is not None:
            Order.objects.filter(pk=order.pk).update(hold_expires_at=None)
            order.hold_expires_at = None


def expire_submitted_order_holds(
    *,
    ref=None,
    dry_run: bool = False,
    actor: AbstractBaseUser | None = None,
) -> dict:
    """
    Cancela pedidos «enviados» cuyo hold venció y libera las tomas.
    """
    now = ref if ref is not None else timezone.now()
    qs = Order.objects.filter(
        status=OrderStatus.SUBMITTED,
        hold_expires_at__isnull=False,
        hold_expires_at__lt=now,
    ).order_by("pk")
    ids = list(qs.values_list("pk", flat=True))
    if dry_run:
        return {"would_expire": len(ids), "order_ids": ids}

    expired = 0
    for pk in ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(pk=pk).first()
            if order is None or order.status != OrderStatus.SUBMITTED:
                continue
            if order.hold_expires_at is None or order.hold_expires_at >= now:
                continue
            cancel_order_releasing_hold(
                order,
                actor=actor,
                note=NOTE_HOLD_EXPIRED,
            )
            expired += 1
    return {"expired": expired, "order_ids": ids[:expired]}
