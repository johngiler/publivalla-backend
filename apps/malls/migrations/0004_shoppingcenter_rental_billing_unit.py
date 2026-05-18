from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0003_alter_shoppingcenter_high_season_multiplier"),
    ]

    operations = [
        migrations.AddField(
            model_name="shoppingcenter",
            name="rental_billing_unit",
            field=models.CharField(
                choices=[
                    ("calendar_month", "Por mes de calendario"),
                    ("calendar_day", "Por día de calendario"),
                ],
                default="calendar_month",
                help_text=(
                    "Cómo se cotiza y reserva en marketplace: meses de calendario o días "
                    "(canon diario = mensual ÷ 30)."
                ),
                max_length=20,
            ),
        ),
    ]
