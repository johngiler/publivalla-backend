"""
Tareas programables para órdenes.

Sin Celery en el proyecto: ejecutar vía cron o supervisor, por ejemplo::

    python manage.py expire_active_orders   # diario, órdenes activas vencidas
    python manage.py expire_order_holds     # cada hora, holds de 72 h vencidos

Si más adelante añades Celery beat, las tareas pueden llamar a
:func:`run_expire_active_orders_job` y :func:`run_expire_order_holds_job`.
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
