"""Elimina estado comercial «reservado» de espacios; migra registros según calendario."""

from django.db import migrations, models


def migrate_reserved_to_available_or_occupied(apps, schema_editor):
    AdSpace = apps.get_model("ad_spaces", "AdSpace")
    from apps.ad_spaces.utils.marketplace_availability import sync_ad_space_commercial_status

    for pk in AdSpace.objects.filter(status="reserved").values_list("pk", flat=True).iterator():
        sync_ad_space_commercial_status(pk)


class Migration(migrations.Migration):
    dependencies = [
        ("ad_spaces", "0003_sync_ad_space_status_from_calendar"),
    ]

    operations = [
        migrations.RunPython(migrate_reserved_to_available_or_occupied, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="adspace",
            name="status",
            field=models.CharField(
                choices=[
                    ("available", "Disponible"),
                    ("occupied", "Ocupado"),
                    ("blocked", "Bloqueado"),
                ],
                default="available",
                max_length=20,
            ),
        ),
    ]
