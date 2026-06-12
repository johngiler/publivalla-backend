"""
Recordatorios por correo de cuotas de pago por partes (2 y 1 día antes del vencimiento).

Independiente de la generación automática de notas de cobro
(``invoice_due_payment_installments``).

Programación sugerida (cron, una vez al día, p. ej. 07:00)::

    cd /ruta/al/backend && python manage.py notify_payment_installments_due

Dry-run::

    python manage.py notify_payment_installments_due --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.orders.utils.jobs import run_notify_payment_installments_due_job


class Command(BaseCommand):
    help = (
        "Envía correos de recordatorio de cuotas que vencen en 2 o 1 día(s) "
        "(plan de pago por partes)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo lista cuotas que se notificarían, sin enviar correos ni escribir en BD.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        result = run_notify_payment_installments_due_job(dry_run=dry)
        if dry:
            n = result.get("would_notify", 0)
            rows = result.get("installments") or []
            self.stdout.write(
                self.style.WARNING(f"Dry-run: se notificarían {n} cuota(s).")
            )
            if rows and self.verbosity >= 2:
                for row in rows:
                    self.stdout.write(
                        f"  cuota {row.get('installment_id')} "
                        f"(pedido {row.get('order_id')}, "
                        f"{row.get('days_before')} día(s) antes, "
                        f"vence {row.get('due_date')})"
                    )
        else:
            n = result.get("notified", 0)
            errs = result.get("errors") or []
            self.stdout.write(self.style.SUCCESS(f"Cuotas notificadas: {n}."))
            if errs and self.verbosity >= 1:
                for row in errs:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  cuota {row.get('installment_id')} "
                            f"(pedido {row.get('order_id')}, "
                            f"{row.get('days_before')} día(s) antes): "
                            f"{row.get('error')}"
                        )
                    )
