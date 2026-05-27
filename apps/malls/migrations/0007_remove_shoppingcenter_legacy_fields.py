"""Elimina campos de contacto, listado y catálogo duplicados (visibilidad = is_active)."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0006_backfill_lease_high_season"),
    ]

    operations = [
        migrations.RemoveField(model_name="shoppingcenter", name="phone"),
        migrations.RemoveField(model_name="shoppingcenter", name="contact_email"),
        migrations.RemoveField(model_name="shoppingcenter", name="website"),
        migrations.RemoveField(model_name="shoppingcenter", name="district"),
        migrations.RemoveField(model_name="shoppingcenter", name="on_homepage"),
        migrations.RemoveField(model_name="shoppingcenter", name="listing_order"),
        migrations.RemoveField(model_name="shoppingcenter", name="marketplace_catalog_enabled"),
        migrations.AlterModelOptions(
            name="shoppingcenter",
            options={"ordering": ["slug"]},
        ),
    ]
