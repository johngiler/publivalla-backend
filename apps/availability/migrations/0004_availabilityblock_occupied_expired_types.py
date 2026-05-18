# Generated manually — tipos de bloqueo: solo ocupado / caducado

from django.db import migrations, models


def forwards_types_and_status(apps, schema_editor):
    AvailabilityBlock = apps.get_model("availability", "AvailabilityBlock")
    AdSpace = apps.get_model("ad_spaces", "AdSpace")

    AvailabilityBlock.objects.filter(type__in=("reserved", "blocked")).update(
        type="occupied"
    )
    AvailabilityBlock.objects.filter(is_active=False).update(
        type="expired", is_active=False
    )

    from django.utils import timezone

    today = timezone.localdate()
    AvailabilityBlock.objects.filter(is_active=True, end_date__lt=today).update(
        type="expired", is_active=False
    )

    # Recalcular tomas que quedaron «bloqueado» por la lógica antigua (tipo blocked en bloqueo).
    try:
        from apps.ad_spaces.utils.marketplace_availability import (
            sync_ad_space_commercial_status,
        )

        stuck_ids = (
            AdSpace.objects.filter(status="blocked")
            .filter(availability_blocks__isnull=False)
            .distinct()
            .values_list("pk", flat=True)
        )
        for pk in stuck_ids:
            sync_ad_space_commercial_status(pk, force_calendar=True)
    except Exception:
        pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0003_alter_availabilityblock_type"),
        ("ad_spaces", "0004_remove_reserved_ad_space_status"),
    ]

    operations = [
        migrations.RunPython(forwards_types_and_status, noop_reverse),
        migrations.AlterField(
            model_name="availabilityblock",
            name="type",
            field=models.CharField(
                choices=[
                    ("occupied", "Ocupado"),
                    ("expired", "Caducado"),
                ],
                max_length=20,
            ),
        ),
    ]
