"""Recalcula estado comercial (disponible/ocupado) según meses libres en calendario."""

from django.db import migrations


def sync_all_ad_space_statuses(apps, schema_editor):
    AdSpace = apps.get_model("ad_spaces", "AdSpace")
    from apps.ad_spaces.utils.marketplace_availability import sync_ad_space_commercial_status

    for pk in AdSpace.objects.values_list("pk", flat=True).iterator():
        sync_ad_space_commercial_status(pk)


class Migration(migrations.Migration):
    dependencies = [
        ("ad_spaces", "0002_alter_adspace_code"),
        ("orders", "0002_renumber_order_codes_per_workspace"),
        ("availability", "0003_alter_availabilityblock_type"),
    ]

    operations = [
        migrations.RunPython(sync_all_ad_space_statuses, migrations.RunPython.noop),
    ]
