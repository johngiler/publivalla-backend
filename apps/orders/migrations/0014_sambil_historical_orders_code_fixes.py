"""Importa pedidos históricos Sambil con códigos de toma corregidos (SMR-T5C, SSN-T4B)."""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.orders.services.sambil_historical_orders_import import (
        import_sambil_historical_orders,
    )

    result = import_sambil_historical_orders()
    created = result.get("created", 0)
    skipped = result.get("skipped", 0)
    errors = result.get("errors") or []
    print(
        f"[sambil-historical-orders-0014] creados={created} omitidos={skipped} "
        f"errores={len(errors)}"
    )
    for err in errors:
        print(f"[sambil-historical-orders-0014] {err}")


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0013_import_sambil_historical_orders"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
