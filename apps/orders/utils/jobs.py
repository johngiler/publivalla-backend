"""
Tareas programables para órdenes.

Sin Celery en el proyecto: ejecutar vía cron o supervisor, por ejemplo::

    python manage.py expire_active_orders   # diario, órdenes activas vencidas
    python manage.py expire_order_holds     # cada hora, holds de 72 h vencidos
    python manage.py invoice_due_payment_installments  # diario, cuotas 2+ al vencer
    python manage.py notify_payment_installments_due  # diario, avisos 2 y 1 día antes

Si más adelante añades Celery beat, las tareas pueden llamar a
:func:`run_expire_active_orders_job`, :func:`run_expire_order_holds_job`,
:func:`run_invoice_due_payment_installments_job` y
:func:`run_notify_payment_installments_due_job`.
"""

from __future__ import annotations


def run_expire_active_orders_job(*, dry_run: bool = False) -> dict:
    """Marca como vencidas las órdenes activas cuyo contrato ya terminó (ver servicio)."""
    from apps.orders.services import expire_active_orders_after_contract_end

    return expire_active_orders_after_contract_end(dry_run=dry_run)


def run_expire_order_holds_job(*, dry_run: bool = False) -> dict:
    """Cancela pedidos enviados con hold vencido y libera tomas reservadas."""
    from apps.orders.services import expire_submitted_order_holds

    return expire_submitted_order_holds(dry_run=dry_run)


def run_invoice_due_payment_installments_job(*, dry_run: bool = False) -> dict:
    """Genera notas de cobro de cuotas 2+ cuyo vencimiento ya llegó."""
    from apps.orders.services.payment_plan_services import invoice_due_payment_installments

    return invoice_due_payment_installments(dry_run=dry_run)


def run_notify_payment_installments_due_job(*, dry_run: bool = False) -> dict:
    """Envía recordatorios de cuotas que vencen en 2 o 1 día(s)."""
    from apps.orders.services.payment_plan_notification_services import (
        notify_payment_installments_due,
    )

    return notify_payment_installments_due(dry_run=dry_run)
