"""Importa pedidos históricos del tenant Sambil (one-off)."""

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
        f"[sambil-historical-orders] creados={created} omitidos={skipped} "
        f"errores={len(errors)}"
    )
    for err in errors:
        print(f"[sambil-historical-orders] {err}")


def backwards(apps, schema_editor):
    from apps.orders.services.sambil_historical_orders_import import (
        revert_sambil_historical_orders,
    )

    revert_sambil_historical_orders()


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0012_alter_orderpaymentinstallment_is_active_and_more"),
        ("clients", "0005_seed_sambil_historical_clients"),
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
