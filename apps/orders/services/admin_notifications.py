"""Campanita del admin: persistencia y aviso en vivo por el channel layer."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.orders.models import (
    AdminNotification,
    AdminNotificationKind,
    Order,
    OrderItem,
    OrderStatus,
)
from apps.users.models import UserProfile

logger = logging.getLogger(__name__)

HOLD_EXPIRING_WITHIN = timedelta(hours=12)
CONTRACT_ENDING_IN_DAYS = 30


def admin_notify_group(user_id: int) -> str:
    return f"admin-notify-{user_id}"


def serialize_admin_notification(row: AdminNotification) -> dict:
    return {
        "id": row.pk,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "href": row.href,
        "read": row.read_at is not None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _order_ref(order: Order) -> str:
    code = (order.code or "").strip()
    return code or f"#{order.pk}"


def _company(order: Order) -> str:
    name = (getattr(order.client, "company_name", "") or "").strip()
    return name or "Una empresa"


def _pedidos_href(order: Order) -> str:
    from urllib.parse import quote

    return f"/dashboard/pedidos?q={quote(_order_ref(order))}"


def _contratos_href(order: Order) -> str:
    from urllib.parse import quote

    return f"/dashboard/contratos?q={quote(_order_ref(order))}"


def _pujas_href(ad_space_id: int) -> str:
    return f"/dashboard/pujas?space={ad_space_id}"


def _workspace_admins(workspace, *, exclude_user_id: int | None = None):
    User = get_user_model()
    qs = User.objects.filter(
        is_active=True,
        profile__role=UserProfile.Role.ADMIN,
        profile__workspace=workspace,
    )
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    return qs


def _broadcast(row: AdminNotification) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            admin_notify_group(row.recipient_id),
            {
                "type": "notification.created",
                "notification": serialize_admin_notification(row),
            },
        )
    except Exception:
        logger.exception(
            "No se pudo publicar la notificación %s al usuario %s.",
            row.pk,
            row.recipient_id,
        )


def notify_workspace_admins(
    *,
    workspace,
    kind: str,
    title: str,
    body: str,
    href: str,
    dedupe_key: str,
    order: Order | None = None,
    exclude_user_id: int | None = None,
) -> None:
    """Crea el aviso para cada admin del workspace y lo empuja al socket tras el commit."""
    if workspace is None or not dedupe_key:
        return
    pending: list[int] = []

    def _create() -> None:
        for admin in _workspace_admins(workspace, exclude_user_id=exclude_user_id):
            try:
                row, created = AdminNotification.objects.get_or_create(
                    recipient=admin,
                    dedupe_key=dedupe_key,
                    defaults={
                        "workspace": workspace,
                        "kind": kind,
                        "title": title,
                        "body": body[:280],
                        "href": href[:300],
                        "order": order,
                    },
                )
            except IntegrityError:
                continue
            if created:
                pending.append(row.pk)

    def _push() -> None:
        if not pending:
            return
        rows = AdminNotification.objects.filter(pk__in=pending)
        for row in rows:
            _broadcast(row)

    _create()
    transaction.on_commit(_push)


def _competing_space_id(order: Order) -> int | None:
    workspace_id = order.client.workspace_id
    for item in order.items.all():
        rivals = (
            OrderItem.objects.filter(
                ad_space_id=item.ad_space_id,
                order__status=OrderStatus.SUBMITTED,
                order__client__workspace_id=workspace_id,
            )
            .values("order_id")
            .distinct()
            .count()
        )
        if rivals >= 2:
            return item.ad_space_id
    return None


def notify_order_submitted(order: Order) -> None:
    order = Order.objects.select_related("client__workspace").prefetch_related("items").get(
        pk=order.pk
    )
    workspace = order.client.workspace
    company = _company(order)
    ref = _order_ref(order)
    space_id = _competing_space_id(order)
    if space_id is not None:
        space = order.items.filter(ad_space_id=space_id).select_related("ad_space").first()
        code = space.ad_space.code if space is not None else ""
        notify_workspace_admins(
            workspace=workspace,
            kind=AdminNotificationKind.COMPETING_BID,
            title="Puja",
            body=f"{company} compite por {code} en el pedido {ref}.".replace("  ", " "),
            href=_pujas_href(space_id),
            dedupe_key=f"competing_bid:{order.pk}",
            order=order,
        )
        return
    notify_workspace_admins(
        workspace=workspace,
        kind=AdminNotificationKind.ORDER_SUBMITTED,
        title="Pedido nuevo",
        body=f"{company} envió el pedido {ref}.",
        href=_pedidos_href(order),
        dedupe_key=f"order_submitted:{order.pk}",
        order=order,
    )


def notify_hold_expired(order: Order) -> None:
    order = Order.objects.select_related("client__workspace").get(pk=order.pk)
    ref = _order_ref(order)
    notify_workspace_admins(
        workspace=order.client.workspace,
        kind=AdminNotificationKind.HOLD_EXPIRED,
        title="Reserva vencida",
        body=f"Se rechazó el pedido {ref} al cumplirse el plazo de reserva.",
        href=_pedidos_href(order),
        dedupe_key=f"hold_expired:{order.pk}",
        order=order,
    )


def notify_contract_finished(order: Order, *, early: bool, exclude_user_id: int | None) -> None:
    order = Order.objects.select_related("client__workspace").get(pk=order.pk)
    ref = _order_ref(order)
    if early:
        notify_workspace_admins(
            workspace=order.client.workspace,
            kind=AdminNotificationKind.CONTRACT_ENDED_EARLY,
            title="Finalización anticipada",
            body=f"El pedido {ref} se cerró antes de la fecha de fin.",
            href=_contratos_href(order),
            dedupe_key=f"contract_ended_early:{order.pk}",
            order=order,
            exclude_user_id=exclude_user_id,
        )
        return
    notify_workspace_admins(
        workspace=order.client.workspace,
        kind=AdminNotificationKind.CONTRACT_FINISHED,
        title="Contrato finalizado",
        body=f"El pedido {ref} cerró su periodo.",
        href=_contratos_href(order),
        dedupe_key=f"contract_finished:{order.pk}",
        order=order,
    )


def notify_contract_lines_running(order: Order) -> None:
    """Líneas cuyo periodo ya incluye hoy, al pasar el pedido a activo."""
    today = timezone.localdate()
    order = (
        Order.objects.select_related("client__workspace")
        .prefetch_related("items__ad_space")
        .get(pk=order.pk)
    )
    if order.status != OrderStatus.ACTIVE:
        return
    ref = _order_ref(order)
    for item in order.items.all():
        if item.start_date <= today <= item.end_date:
            _notify_line_running(order, item, ref)


def _notify_line_running(order: Order, item: OrderItem, ref: str) -> None:
    code = item.ad_space.code
    notify_workspace_admins(
        workspace=order.client.workspace,
        kind=AdminNotificationKind.CONTRACT_RUNNING,
        title="Contrato en curso",
        body=f"{code} del pedido {ref} inició su periodo.",
        href=_contratos_href(order),
        dedupe_key=f"contract_running:{item.pk}",
        order=order,
    )


def notify_client_activity(order_id: int, activity: str, *, actor_id: int | None = None) -> None:
    """Aviso al cargar hoja, arte o comprobante. Independiente del correo."""
    kind_by_activity = {
        "negotiation_signed": (
            AdminNotificationKind.NEGOTIATION_SIGNED,
            "Hoja firmada",
            "cargó la hoja firmada del pedido",
        ),
        "art_upload": (
            AdminNotificationKind.ART_UPLOADED,
            "Arte cargado",
            "envió el arte del pedido",
        ),
        "payment_receipt": (
            AdminNotificationKind.PAYMENT_RECEIPT,
            "Comprobante de pago",
            "cargó un comprobante del pedido",
        ),
    }
    spec = kind_by_activity.get((activity or "").strip())
    if spec is None:
        return
    try:
        order = Order.objects.select_related("client__workspace").get(pk=order_id)
    except Order.DoesNotExist:
        return
    kind, title, verb = spec
    ref = _order_ref(order)
    notify_workspace_admins(
        workspace=order.client.workspace,
        kind=kind,
        title=title,
        body=f"{_company(order)} {verb} {ref}.",
        href=_pedidos_href(order),
        dedupe_key=f"{kind}:{order.pk}:{uuid.uuid4().hex}",
        order=order,
        exclude_user_id=actor_id,
    )


def notify_holds_expiring_soon(*, now=None) -> int:
    """Una vez por pedido enviado al que le quedan 12 horas o menos de reserva."""
    ref = now or timezone.now()
    horizon = ref + HOLD_EXPIRING_WITHIN
    orders = Order.objects.filter(
        status=OrderStatus.SUBMITTED,
        hold_expires_at__isnull=False,
        hold_expires_at__gt=ref,
        hold_expires_at__lte=horizon,
    ).select_related("client__workspace")
    count = 0
    for order in orders:
        before = AdminNotification.objects.filter(
            dedupe_key=f"hold_expiring:{order.pk}"
        ).exists()
        notify_workspace_admins(
            workspace=order.client.workspace,
            kind=AdminNotificationKind.HOLD_EXPIRING,
            title="Reserva por vencer",
            body=f"Al pedido {_order_ref(order)} le queda poco de las 72 horas de reserva.",
            href=_pedidos_href(order),
            dedupe_key=f"hold_expiring:{order.pk}",
            order=order,
        )
        if not before:
            count += 1
    return count


def notify_contracts_starting_today(*, today=None) -> int:
    """Líneas activas cuyo inicio es hoy. Una vez por línea."""
    day = today or timezone.localdate()
    items = (
        OrderItem.objects.filter(
            order__status=OrderStatus.ACTIVE,
            start_date=day,
            end_date__gte=day,
        )
        .select_related("order__client__workspace", "ad_space")
    )
    for item in items:
        _notify_line_running(item.order, item, _order_ref(item.order))
    return items.count()


def notify_contracts_ending_in_30_days(*, today=None) -> int:
    """Líneas en curso que terminan dentro de 30 días. Una vez por línea."""
    day = today or timezone.localdate()
    target = day + timedelta(days=CONTRACT_ENDING_IN_DAYS)
    items = OrderItem.objects.filter(
        order__status=OrderStatus.ACTIVE,
        start_date__lte=day,
        end_date=target,
    ).select_related("order__client__workspace", "ad_space")
    for item in items:
        ref = _order_ref(item.order)
        notify_workspace_admins(
            workspace=item.order.client.workspace,
            kind=AdminNotificationKind.CONTRACT_ENDING_SOON,
            title="Por finalizar",
            body=f"{item.ad_space.code} del pedido {ref} termina en 30 días.",
            href=_contratos_href(item.order),
            dedupe_key=f"contract_ending_soon:{item.pk}",
            order=item.order,
        )
    return items.count()
