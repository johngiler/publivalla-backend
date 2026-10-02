"""Recalcula cuotas no pagadas con el mes inicial al importe acordado."""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.orders.services.payment_plan_services import (
        recalculate_unpaid_installment_amounts,
    )

    updated = recalculate_unpaid_installment_amounts()
    print("[cuotas] montos actualizados=%s" % updated)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0019_admin_notification"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
