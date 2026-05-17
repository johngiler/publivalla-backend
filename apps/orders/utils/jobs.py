"""
Tareas programables para órdenes.

Sin Celery en el proyecto: ejecutar vía cron o supervisor, por ejemplo diario::

    python manage.py expire_active_orders

Si más adelante añades Celery beat, la tarea puede llamar solo a
:func:`run_expire_active_orders_job`.
"""

from __future__ import annotations


def run_expire_active_orders_job(*, dry_run: bool = False) -> dict:
    """Marca como vencidas las órdenes activas cuyo contrato ya terminó (ver servicio)."""
    from apps.orders.services import expire_active_orders_after_contract_end

    return expire_active_orders_after_contract_end(dry_run=dry_run)
