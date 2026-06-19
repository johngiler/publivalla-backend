"""Aplicar galerías multipart (``*_plan`` + ``*_add``) sobre una toma."""

from __future__ import annotations

import json
from typing import Any, Type

from django.db import transaction
from django.db.models import Model

from rest_framework.exceptions import ValidationError

from apps.ad_spaces.models import (
    AdSpaceImage,
    AdSpaceLocationImage,
    AdSpaceProductionImage,
)

_MAX_IMAGES = 20
_MAX_BYTES = 10 * 1024 * 1024
_ALLOWED_CT = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


def _validate_uploaded_image(f, *, add_key: str) -> None:
    if getattr(f, "size", 0) > _MAX_BYTES:
        raise ValidationError({add_key: "Cada imagen no puede superar 10 MB."})
    ct = (getattr(f, "content_type", None) or "").strip().lower()
    if ct and ct not in _ALLOWED_CT:
        raise ValidationError({add_key: "Formato no permitido. Usa JPG, PNG, WebP o GIF."})


def sync_cover_from_gallery(ad_space) -> None:
    """
    Mantiene ``AdSpace.cover_image`` alineado con la primera imagen de la galería.

    La asignación ``cover_image = first.image`` hace que Django guarde una copia bajo
    ``spaces/covers/%Y/%m/`` (upload_to del campo), distinta de ``spaces/gallery/…``. Es
    redundante en disco pero evita compartir un único path entre dos ImageField (al borrar
    una fila de galería se borraría el fichero y la otra referencia quedaría rota). Ver
    ``apps.ad_spaces.utils.covers``.
    """
    first = ad_space.gallery_images.order_by("sort_order", "id").first()
    if first:
        ad_space.cover_image = first.image
    else:
        ad_space.cover_image = None
    ad_space.save(update_fields=["cover_image"])


def _apply_image_plan_from_request(
    ad_space,
    request,
    *,
    plan_key: str,
    add_key: str,
    image_model: Type[Model],
    related_name: str,
) -> None:
    if plan_key not in request.data:
        return

    raw = request.data.get(plan_key)
    if raw in (None, ""):
        return

    try:
        plan = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValidationError({plan_key: "Debe ser JSON válido."}) from exc

    if not isinstance(plan, list):
        raise ValidationError({plan_key: "Debe ser una lista."})

    files = request.FILES.getlist(add_key)
    for f in files:
        _validate_uploaded_image(f, add_key=add_key)

    with transaction.atomic():
        ad_space_locked = type(ad_space).objects.select_for_update().get(pk=ad_space.pk)
        existing = {
            img.id: img for img in getattr(ad_space_locked, related_name).all()
        }
        keep_ids: set[int] = set()
        steps: list[tuple[str, Any, int]] = []
        new_indices_used: list[int] = []

        for pos, step in enumerate(plan):
            if not isinstance(step, (list, tuple)) or len(step) != 2:
                raise ValidationError({plan_key: "Cada paso debe ser [tipo, valor]."})
            kind, val = step[0], step[1]
            if kind == "e":
                pk = int(val)
                if pk not in existing:
                    raise ValidationError(
                        {plan_key: "Una imagen no pertenece a esta toma."}
                    )
                keep_ids.add(pk)
                steps.append(("e", pk, pos))
            elif kind == "n":
                idx = int(val)
                if idx < 0 or idx >= len(files):
                    raise ValidationError(
                        {plan_key: "Índice de imagen nueva inválido."}
                    )
                new_indices_used.append(idx)
                steps.append(("n", idx, pos))
            else:
                raise ValidationError({plan_key: f'Tipo desconocido: "{kind}".'})

        if len(new_indices_used) != len(set(new_indices_used)):
            raise ValidationError(
                {plan_key: "No repitas el mismo archivo nuevo en el plan."}
            )

        if files:
            expected = set(range(len(files)))
            got = set(new_indices_used)
            if got != expected:
                raise ValidationError(
                    {
                        plan_key: (
                            "Debes referenciar cada archivo nuevo exactamente "
                            "una vez en el plan."
                        )
                    }
                )

        if len(steps) > _MAX_IMAGES:
            raise ValidationError(
                {plan_key: f"Máximo {_MAX_IMAGES} imágenes por toma."}
            )

        image_model.objects.filter(ad_space=ad_space_locked).exclude(
            pk__in=keep_ids
        ).delete()

        for kind, val, pos in steps:
            if kind == "e":
                image_model.objects.filter(pk=val, ad_space=ad_space_locked).update(
                    sort_order=pos
                )
            else:
                image_model.objects.create(
                    ad_space=ad_space_locked,
                    image=files[val],
                    sort_order=pos,
                )

    ad_space.refresh_from_db()


def apply_ad_space_gallery_from_request(ad_space, request) -> None:
    """
    Si el cuerpo incluye ``gallery_plan`` (JSON), aplica orden y archivos nuevos.

    ``gallery_plan``: lista de ``["e", id]`` (existente) o ``["n", índice]`` (índice en
    ``request.FILES.getlist("gallery_add")``). Lista vacía elimina todas las imágenes.
    """
    _apply_image_plan_from_request(
        ad_space,
        request,
        plan_key="gallery_plan",
        add_key="gallery_add",
        image_model=AdSpaceImage,
        related_name="gallery_images",
    )
    sync_cover_from_gallery(ad_space)


def apply_ad_space_location_images_from_request(ad_space, request) -> None:
    """``location_plan`` + ``location_add`` (mismo contrato que la galería de portada)."""
    _apply_image_plan_from_request(
        ad_space,
        request,
        plan_key="location_plan",
        add_key="location_add",
        image_model=AdSpaceLocationImage,
        related_name="location_images",
    )


def apply_ad_space_production_images_from_request(ad_space, request) -> None:
    """``production_plan`` + ``production_add`` (mismo contrato que la galería de portada)."""
    _apply_image_plan_from_request(
        ad_space,
        request,
        plan_key="production_plan",
        add_key="production_add",
        image_model=AdSpaceProductionImage,
        related_name="production_images",
    )
