"""Rellena municipal_authority_line en centros conocidos cuando el campo está vacío."""

import unicodedata

from django.db import migrations

# Mapa histórico Sambil / aliados — solo para backfill; la fuente de verdad es el campo en BD.
_MUNICIPAL_AUTHORITY_BY_CENTER_NAME = {
    "sambil paraguana": "Sres. Alcaldía Municipio Carirubana",
    "sambil maracaibo": "Sres. Alcaldía Municipio Maracaibo",
    "sambil barquisimeto": "Sres. Alcaldía Municipio Iribarren",
    "sambil valencia": "Sres. Alcaldía Municipio Naguanagua",
    "sambil margarita": "Sres. Alcaldía Municipio Maneiro",
    "sambil san cristobal": "Sres. Alcaldía Municipio San Cristóbal",
    "sambil chacao": "Sres. Alcaldía Municipio Chacao",
    "sambil la candelaria": "Sres. Alcaldía Municipio Libertador",
    "centro lido": "Sres. Alcaldía Municipio Chacao",
    "caracas outlet": "Sres. Alcaldía Municipio Sucre",
    "super centro petare": "Sres. Alcaldía Municipio Sucre",
}


def _normalize_center_name(name: str) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        return ""
    decomposed = unicodedata.normalize("NFD", raw)
    without_marks = "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )
    return " ".join(without_marks.split())


def forwards(apps, schema_editor):
    ShoppingCenter = apps.get_model("malls", "ShoppingCenter")
    for center in ShoppingCenter.objects.all().only(
        "id", "name", "municipal_authority_line"
    ):
        if (center.municipal_authority_line or "").strip():
            continue
        key = _normalize_center_name(center.name)
        line = _MUNICIPAL_AUTHORITY_BY_CENTER_NAME.get(key)
        if not line:
            continue
        center.municipal_authority_line = line
        center.save(update_fields=["municipal_authority_line"])


def backwards(apps, schema_editor):
    ShoppingCenter = apps.get_model("malls", "ShoppingCenter")
    mapped_values = set(_MUNICIPAL_AUTHORITY_BY_CENTER_NAME.values())
    ShoppingCenter.objects.filter(
        municipal_authority_line__in=mapped_values
    ).update(municipal_authority_line="")


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0004_shoppingcenter_rental_billing_unit"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
