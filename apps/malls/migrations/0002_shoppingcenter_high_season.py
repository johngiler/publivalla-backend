from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="shoppingcenter",
            name="high_season_months",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Meses de calendario (1–12) en temporada alta cada año, p. ej. [11, 12, 1].",
            ),
        ),
        migrations.AddField(
            model_name="shoppingcenter",
            name="high_season_multiplier",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("1.00"),
                help_text="Factor sobre el canon mensual de la toma en meses de temporada alta (1.25 = +25 %).",
                max_digits=5,
            ),
        ),
    ]
