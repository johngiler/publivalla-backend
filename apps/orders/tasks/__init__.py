"""Paquete de tareas Celery; implementación en :mod:`apps.orders.tasks.order_tasks`."""

from apps.orders.tasks.order_tasks import (
    notify_client_activation_after_approval_task,
    schedule_notify_client_activation_after_approval,
    schedule_send_order_client_activity_admin_emails,
    schedule_send_order_status_emails,
    send_order_client_activity_admin_emails_task,
    send_order_status_emails_task,
)

__all__ = [
    "notify_client_activation_after_approval_task",
    "schedule_notify_client_activation_after_approval",
    "schedule_send_order_client_activity_admin_emails",
    "schedule_send_order_status_emails",
    "send_order_client_activity_admin_emails_task",
    "send_order_status_emails_task",
]
