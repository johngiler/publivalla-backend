"""
Vence órdenes en estado «activa» cuando la última línea del pedido ya pasó su end_date.

Las líneas (OrderItem) no tienen estado en BD; al pasar la orden a «vencida» dejan de
entrar en PIPELINE_STATUSES y el calendario de disponibilidad deja de contarlas.

Programación sugerida (cron, una vez al día, tras medianoche local)::

    cd /ruta/al/backend && python manage.py expire_active_orders

Dry-run::

    python manage.py expire_active_orders --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.orders.utils.jobs import run_expire_active_orders_job


class Command(BaseCommand):
    help = "Marca como vencidas las órdenes activas cuyo contrato (última línea) ya finalizó."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo lista IDs que se vencerían, sin escribir en la base de datos.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        result = run_expire_active_orders_job(dry_run=dry)
        if dry:
            n = result.get("would_expire", 0)
            ids = result.get("order_ids", [])
            self.stdout.write(self.style.WARNING(f"Dry-run: se vencerían {n} orden(es)."))
            if ids and self.verbosity >= 2:
                self.stdout.write(f"IDs: {ids}")
        else:
            n = result.get("expired", 0)
            self.stdout.write(self.style.SUCCESS(f"Órdenes pasadas a vencida: {n}."))
