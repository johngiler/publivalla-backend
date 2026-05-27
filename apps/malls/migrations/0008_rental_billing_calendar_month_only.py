"""Reservas solo por meses de calendario (sin cotización por día)."""

from django.db import migrations, models


def forwards(apps, schema_editor):
    ShoppingCenter = apps.get_model("malls", "ShoppingCenter")
    ShoppingCenter.objects.exclude(rental_billing_unit="calendar_month").update(
        rental_billing_unit="calendar_month"
    )


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0007_remove_shoppingcenter_legacy_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="shoppingcenter",
            name="rental_billing_unit",
            field=models.CharField(
                choices=[
                    ("calendar_month", "Por mes de calendario"),
                    ("calendar_day", "Por día de calendario"),
                ],
                default="calendar_month",
                help_text="Cotización en marketplace: solo meses de calendario.",
                max_length=20,
            ),
        ),
    ]
