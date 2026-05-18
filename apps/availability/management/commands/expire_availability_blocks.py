"""
Caduca bloqueos de disponibilidad con fecha fin pasada y recalcula tomas afectadas.

Programación sugerida (cron, diario)::

    cd /ruta/al/backend && python manage.py expire_availability_blocks

Dry-run::

    python manage.py expire_availability_blocks --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.availability.jobs import run_expire_availability_blocks_job


class Command(BaseCommand):
    help = (
        "Caduca bloqueos de disponibilidad vencidos y alinea el estado comercial de las tomas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo indica cuántos bloqueos caducarían, sin escribir en la base de datos.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        result = run_expire_availability_blocks_job(dry_run=dry)
        if dry:
            n = result.get("would_expire", 0)
            space_ids = result.get("ad_space_ids", [])
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run: caducarían {n} bloqueo(s) en {len(space_ids)} toma(s)."
                )
            )
            if space_ids and self.verbosity >= 2:
                self.stdout.write(f"Tomas: {space_ids}")
        else:
            n = result.get("expired", 0)
            synced = result.get("spaces_synced", 0)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Bloqueos caducados: {n}. Tomas recalculadas: {synced}."
                )
            )
