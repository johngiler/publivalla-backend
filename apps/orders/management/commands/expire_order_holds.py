"""
Cancela pedidos «enviados» cuyo plazo de reserva (72 h) venció y libera las tomas.

Programación sugerida (cron, cada hora o cada 15 min)::

    cd /ruta/al/backend && python manage.py expire_order_holds

Dry-run::

    python manage.py expire_order_holds --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.orders.utils.jobs import run_expire_order_holds_job


class Command(BaseCommand):
    help = (
        "Cancela pedidos enviados con hold vencido y devuelve las tomas a disponible."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo lista IDs que se cancelarían, sin escribir en la base de datos.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        result = run_expire_order_holds_job(dry_run=dry)
        if dry:
            n = result.get("would_expire", 0)
            ids = result.get("order_ids", [])
            self.stdout.write(
                self.style.WARNING(f"Dry-run: se cancelarían {n} pedido(s) por hold vencido.")
            )
            if ids and self.verbosity >= 2:
                self.stdout.write(f"IDs: {ids}")
        else:
            n = result.get("expired", 0)
            self.stdout.write(
                self.style.SUCCESS(f"Pedidos cancelados por hold vencido: {n}.")
            )
