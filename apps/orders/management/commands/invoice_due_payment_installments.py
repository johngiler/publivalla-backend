"""
Genera notas de cobro para cuotas 2+ cuyo vencimiento ya llegó (plan de pago por partes).

La cuota 1 se emite al facturar el pedido; el resto se factura al llegar su ``due_date``
si el contrato ya está en curso (pagada o estados posteriores).

Programación sugerida (cron, una vez al día, p. ej. 06:05)::

    cd /ruta/al/backend && python manage.py invoice_due_payment_installments

Dry-run::

    python manage.py invoice_due_payment_installments --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.orders.utils.jobs import run_invoice_due_payment_installments_job


class Command(BaseCommand):
    help = (
        "Genera facturas de cuotas 2+ con vencimiento cumplido en pedidos con pago por partes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo lista cuotas que se facturarían, sin escribir en la base de datos.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        result = run_invoice_due_payment_installments_job(dry_run=dry)
        if dry:
            n = result.get("would_invoice", 0)
            ids = result.get("installment_ids", [])
            self.stdout.write(
                self.style.WARNING(f"Dry-run: se facturarían {n} cuota(s).")
            )
            if ids and self.verbosity >= 2:
                self.stdout.write(f"IDs de cuota: {ids}")
        else:
            n = result.get("invoiced", 0)
            errs = result.get("errors") or []
            self.stdout.write(self.style.SUCCESS(f"Cuotas facturadas: {n}."))
            if errs and self.verbosity >= 1:
                for row in errs:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  cuota {row.get('installment_id')} "
                            f"(pedido {row.get('order_id')}): {row.get('error')}"
                        )
                    )
