"""Sincroniza líneas de tipo (`formats`) desde JSON en la petición admin."""

from __future__ import annotations

import json

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.text import slugify

from rest_framework.exceptions import ValidationError

from apps.ad_spaces.models import AdSpaceFormat, AdSpaceProductType


def _slug_from_name(name: str) -> str:
    base = slugify(name) or "tipo"
    return base[:64]


def _resolve_product_type(*, workspace_id: int, row: dict) -> AdSpaceProductType:
    pt_id = row.get("product_type_id") or row.get("product_type")
    if pt_id is not None:
        try:
            pk = int(pt_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"formats": "Tipo inválido en una línea."}) from exc
        pt = AdSpaceProductType.objects.filter(pk=pk, workspace_id=workspace_id).first()
        if pt is None:
            raise ValidationError({"formats": "Un tipo indicado no existe en este workspace."})
        return pt

    name = (row.get("product_type_name") or row.get("type_name") or "").strip()
    if not name:
        raise ValidationError({"formats": "Indica el tipo en cada línea."})

    slug = _slug_from_name(name)
    pt, _ = AdSpaceProductType.objects.get_or_create(
        workspace_id=workspace_id,
        slug=slug,
        defaults={"name": name[:120]},
    )
    if pt.name != name and pt.name.lower() != name.lower():
        pt.name = name[:120]
        pt.save(update_fields=["name", "updated_at"])
    return pt


def _optional_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({"formats": "Medida numérica inválida."}) from exc


def _optional_int(value, *, default: int = 1) -> int:
    if value in (None, ""):
        return default
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"formats": "Cantidad inválida."}) from exc
    if n < 1:
        raise ValidationError({"formats": "La cantidad debe ser al menos 1."})
    return n


def apply_ad_space_formats_from_request(ad_space, request) -> None:
    raw = request.data.get("formats_json")
    if raw in (None, ""):
        return

    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValidationError({"formats_json": "Debe ser JSON válido."}) from exc

    if not isinstance(rows, list):
        raise ValidationError({"formats_json": "Debe ser una lista."})

    ws_id = ad_space.shopping_center.workspace_id
    if ws_id is None:
        raise ValidationError({"formats": "El centro comercial no tiene workspace asignado."})

    with transaction.atomic():
        ad_space.formats.all().delete()
        for pos, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValidationError({"formats_json": "Cada línea debe ser un objeto."})
            pt = _resolve_product_type(workspace_id=ws_id, row=row)
            AdSpaceFormat.objects.create(
                ad_space=ad_space,
                product_type=pt,
                width=_optional_decimal(row.get("width")),
                height=_optional_decimal(row.get("height")),
                quantity=_optional_int(row.get("quantity")),
                location=(row.get("location") or "").strip(),
                double_sided=bool(row.get("double_sided")),
                sort_order=pos,
            )


def sync_ad_space_formats_from_rows(ad_space, rows: list) -> None:
    """Reemplaza las líneas de tipo de un espacio (semilla / importación)."""
    if not isinstance(rows, list):
        return

    ws_id = ad_space.shopping_center.workspace_id
    if ws_id is None:
        return

    with transaction.atomic():
        ad_space.formats.all().delete()
        for pos, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            pt = _resolve_product_type(workspace_id=ws_id, row=row)
            AdSpaceFormat.objects.create(
                ad_space=ad_space,
                product_type=pt,
                width=_optional_decimal(row.get("width")),
                height=_optional_decimal(row.get("height")),
                quantity=_optional_int(row.get("quantity")),
                location=(row.get("location") or "").strip(),
                double_sided=bool(row.get("double_sided")),
                sort_order=pos,
            )


LEGACY_TYPE_LABELS = {
    "billboard": "Valla (genérico)",
    "banner": "Banner / pendón (genérico)",
    "elevator": "Ascensor",
    "other": "Otro",
    "valla_vertical": "Valla vertical / gigantografía vertical",
    "valla_horizontal": "Valla horizontal / gigantografía horizontal",
    "gigantografia_fachada": "Gigantografía en fachada",
    "pendon_balcon": "Pendón de balcón",
    "pendon_atrio": "Pendón de atrio / colgante central",
    "pendon_pasillo": "Pendón de pasillo",
    "pendon_plaza": "Pendón de plaza",
    "pendon_columna": "Pendón de columna",
}


def legacy_catalog_spec_to_format_rows(spec: dict) -> list[dict]:
    """Convierte un dict de catálogo legacy (PDF/demo) a filas de formato."""
    if not isinstance(spec, dict):
        return []
    if isinstance(spec.get("formats"), list) and spec["formats"]:
        return spec["formats"]

    legacy_type = (spec.get("type") or spec.get("product_type_slug") or "").strip().lower()
    type_name = (spec.get("product_type_name") or "").strip()
    if not type_name and legacy_type:
        type_name = LEGACY_TYPE_LABELS.get(legacy_type, legacy_type.replace("_", " ").title())
    if not type_name:
        return []

    loc_parts = [
        spec.get("location") or spec.get("location_description") or "",
        spec.get("venue_zone") or "",
        spec.get("level") or "",
    ]
    location = " · ".join(p.strip() for p in loc_parts if p and str(p).strip())

    return [
        {
            "product_type_name": type_name,
            "width": spec.get("width"),
            "height": spec.get("height"),
            "quantity": spec.get("quantity", 1),
            "location": location,
            "double_sided": bool(spec.get("double_sided")),
        }
    ]
