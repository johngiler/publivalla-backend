"""Tareas Celery de usuarios (correos de alta admin y recuperación de contraseña)."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.orders.tasks.order_tasks import _has_celery_broker

logger = logging.getLogger(__name__)


def notify_marketplace_admin_user_created_work(user_id: int) -> None:
    from apps.users.utils.notifications import notify_marketplace_admin_user_created

    notify_marketplace_admin_user_created(user_id)


@shared_task(
    bind=True,
    ignore_result=True,
    name="apps.users.tasks.notify_marketplace_admin_user_created_task",
)
def notify_marketplace_admin_user_created_task(self, user_id: int) -> None:
    notify_marketplace_admin_user_created_work(user_id)


def schedule_notify_marketplace_admin_user_created(user_id: int) -> None:
    if not _has_celery_broker():
        notify_marketplace_admin_user_created_work(user_id)
        return
    try:
        notify_marketplace_admin_user_created_task.delay(user_id)
    except Exception:
        logger.exception(
            "No se pudo encolar el correo de alta admin (usuario %s).",
            user_id,
        )


def notify_marketplace_client_user_created_work(user_id: int) -> None:
    from apps.users.utils.notifications import notify_marketplace_client_user_created

    notify_marketplace_client_user_created(user_id)


@shared_task(
    bind=True,
    ignore_result=True,
    name="apps.users.tasks.notify_marketplace_client_user_created_task",
)
def notify_marketplace_client_user_created_task(self, user_id: int) -> None:
    notify_marketplace_client_user_created_work(user_id)


def schedule_notify_marketplace_client_user_created(user_id: int) -> None:
    if not _has_celery_broker():
        notify_marketplace_client_user_created_work(user_id)
        return
    try:
        notify_marketplace_client_user_created_task.delay(user_id)
    except Exception:
        logger.exception(
            "No se pudo encolar el correo de alta cliente (usuario %s).",
            user_id,
        )


def send_password_reset_email_work(user_id: int) -> None:
    from apps.users.utils.notifications import send_password_reset_email

    send_password_reset_email(user_id)


@shared_task(
    bind=True,
    ignore_result=True,
    name="apps.users.tasks.send_password_reset_email_task",
)
def send_password_reset_email_task(self, user_id: int) -> None:
    send_password_reset_email_work(user_id)


def schedule_send_password_reset_email(user_id: int) -> None:
    if not _has_celery_broker():
        send_password_reset_email_work(user_id)
        return
    try:
        send_password_reset_email_task.delay(user_id)
    except Exception:
        logger.exception(
            "No se pudo encolar el correo de restablecimiento (usuario %s).",
            user_id,
        )
