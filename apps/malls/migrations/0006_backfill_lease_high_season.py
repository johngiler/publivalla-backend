"""Aplica meses de temporada alta del canon y recargo fijo +30 % por reglas de mall."""

from decimal import Decimal

from django.db import migrations, models


def _is_margarita(slug: str, name: str) -> bool:
    slug = (slug or "").strip().lower()
    name = (name or "").strip().lower()
    if slug in ("smg", "sambil-margarita", "margarita"):
        return True
    if "margarita" in slug or "margarita" in name:
        return True
    return name == "sambil margarita"


def forwards(apps, schema_editor):
    ShoppingCenter = apps.get_model("malls", "ShoppingCenter")
    margarita_months = [7, 8, 11, 12]
    default_months = [11, 12]
    surcharge = Decimal("1.30")
    for center in ShoppingCenter.objects.all().only("id", "slug", "name"):
        months = margarita_months if _is_margarita(center.slug, center.name) else default_months
        ShoppingCenter.objects.filter(pk=center.pk).update(
            high_season_months=months,
            high_season_multiplier=surcharge,
        )


def backwards(apps, schema_editor):
    ShoppingCenter = apps.get_model("malls", "ShoppingCenter")
    ShoppingCenter.objects.all().update(
        high_season_months=[],
        high_season_multiplier=Decimal("1.00"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0005_backfill_municipal_authority_lines"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="shoppingcenter",
            name="high_season_multiplier",
            field=models.DecimalField(
                max_digits=5,
                decimal_places=2,
                default=Decimal("1.30"),
                help_text="Recargo fijo en temporada alta (+30 %).",
            ),
        ),
        migrations.AlterField(
            model_name="shoppingcenter",
            name="high_season_months",
            field=models.JSONField(
                default=list,
                blank=True,
                help_text=(
                    "Meses de calendario (1–12) con canon +30 %: Margarita jul–ago y nov–dic; "
                    "resto nov–dic. Se asignan automáticamente al guardar."
                ),
            ),
        ),
    ]
