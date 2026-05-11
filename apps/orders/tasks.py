"""Tareas Celery del dominio de pedidos (correo fuera del ciclo request/response)."""

from __future__ import annotations

import logging
from celery import shared_task
from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)


def _has_celery_broker() -> bool:
    return bool((getattr(settings, "CELERY_BROKER_URL", None) or "").strip())


def send_order_status_emails_work(
    order_id: int,
    from_status: str,
    to_status: str,
    *,
    actor_id: int | None = None,
) -> None:
    from apps.orders.email_notifications import try_send_order_status_emails
    from apps.orders.models import Order

    try:
        order = Order.objects.select_related("client__workspace").get(pk=order_id)
    except Order.DoesNotExist:
        logger.warning("send_order_status_emails: pedido %s no encontrado.", order_id)
        return
    try_send_order_status_emails(
        order, from_status or "", to_status, actor_id=actor_id
    )


@shared_task(bind=True, ignore_result=True)
def send_order_status_emails_task(
    self,
    order_id: int,
    from_status: str,
    to_status: str,
    actor_id: int | None = None,
) -> None:
    send_order_status_emails_work(order_id, from_status, to_status, actor_id=actor_id)


def schedule_send_order_status_emails(
    order_id: int,
    from_status: str,
    to_status: str,
    *,
    actor_id: int | None = None,
) -> None:
    """Encola el envío en Celery (requiere broker)."""
    from_s = from_status or ""
    if not _has_celery_broker():
        logger.warning(
            "No se envió correo: falta CELERY_BROKER_URL (pedido %s → %s).",
            order_id,
            to_status,
        )
        return
    try:
        send_order_status_emails_task.delay(order_id, from_s, to_status, actor_id=actor_id)
    except Exception:
        logger.exception(
            "No se pudo encolar la notificación por correo (pedido %s → %s).",
            order_id,
            to_status,
        )


def notify_client_activation_after_approval_work(order_id: int) -> None:
    from apps.clients.notifications import notify_client_after_order_client_approved
    from apps.orders.models import Order

    try:
        order = Order.objects.select_related("client__workspace").get(pk=order_id)
    except Order.DoesNotExist:
        logger.warning("notify_client_activation: pedido %s no encontrado.", order_id)
        return
    notify_client_after_order_client_approved(order)


@shared_task(bind=True, ignore_result=True)
def notify_client_activation_after_approval_task(self, order_id: int) -> None:
    notify_client_activation_after_approval_work(order_id)


def schedule_notify_client_activation_after_approval(order_id: int) -> None:
    if not _has_celery_broker():
        logger.warning(
            "No se envió correo de activación: falta CELERY_BROKER_URL (pedido %s).",
            order_id,
        )
        return
    try:
        notify_client_activation_after_approval_task.delay(order_id)
    except Exception:
        logger.exception(
            "No se pudo encolar el correo de activación de cuenta (pedido %s).",
            order_id,
        )
