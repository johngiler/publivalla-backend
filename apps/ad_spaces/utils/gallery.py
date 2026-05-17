"""Aplicar galería multipart (`gallery_plan` + `gallery_add`) sobre una toma."""

import json
from typing import Any

from django.db import transaction

from rest_framework.exceptions import ValidationError

from apps.ad_spaces.models import AdSpaceImage

_MAX_IMAGES = 20
_MAX_BYTES = 10 * 1024 * 1024
_ALLOWED_CT = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


def _validate_uploaded_image(f) -> None:
    if getattr(f, "size", 0) > _MAX_BYTES:
        raise ValidationError({"gallery_add": "Cada imagen no puede superar 10 MB."})
    ct = (getattr(f, "content_type", None) or "").strip().lower()
    if ct and ct not in _ALLOWED_CT:
        raise ValidationError({"gallery_add": "Formato no permitido. Usa JPG, PNG, WebP o GIF."})


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


def apply_ad_space_gallery_from_request(ad_space, request) -> None:
    """
    Si el cuerpo incluye ``gallery_plan`` (JSON), aplica orden y archivos nuevos.

    ``gallery_plan``: lista de ``["e", id]`` (existente) o ``["n", índice]`` (índice en
    ``request.FILES.getlist("gallery_add")``). Lista vacía elimina todas las imágenes.
    """
    if "gallery_plan" not in request.data:
        return

    raw = request.data.get("gallery_plan")
    if raw in (None, ""):
        return

    try:
        plan = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValidationError({"gallery_plan": "Debe ser JSON válido."}) from exc

    if not isinstance(plan, list):
        raise ValidationError({"gallery_plan": "Debe ser una lista."})

    files = request.FILES.getlist("gallery_add")
    for f in files:
        _validate_uploaded_image(f)

    with transaction.atomic():
        ad_space_locked = type(ad_space).objects.select_for_update().get(pk=ad_space.pk)
        existing = {img.id: img for img in ad_space_locked.gallery_images.all()}
        keep_ids: set[int] = set()
        steps: list[tuple[str, Any, int]] = []
        new_indices_used: list[int] = []

        for pos, step in enumerate(plan):
            if not isinstance(step, (list, tuple)) or len(step) != 2:
                raise ValidationError({"gallery_plan": "Cada paso debe ser [tipo, valor]."})
            kind, val = step[0], step[1]
            if kind == "e":
                pk = int(val)
                if pk not in existing:
                    raise ValidationError({"gallery_plan": "Una imagen no pertenece a esta toma."})
                keep_ids.add(pk)
                steps.append(("e", pk, pos))
            elif kind == "n":
                idx = int(val)
                if idx < 0 or idx >= len(files):
                    raise ValidationError({"gallery_plan": "Índice de imagen nueva inválido."})
                new_indices_used.append(idx)
                steps.append(("n", idx, pos))
            else:
                raise ValidationError({"gallery_plan": f'Tipo desconocido: "{kind}".'})

        if len(new_indices_used) != len(set(new_indices_used)):
            raise ValidationError({"gallery_plan": "No repitas el mismo archivo nuevo en el plan."})

        if files:
            expected = set(range(len(files)))
            got = set(new_indices_used)
            if got != expected:
                raise ValidationError(
                    {"gallery_plan": "Debes referenciar cada archivo nuevo exactamente una vez en el plan."}
                )

        if len(steps) > _MAX_IMAGES:
            raise ValidationError({"gallery_plan": f"Máximo {_MAX_IMAGES} imágenes por toma."})

        AdSpaceImage.objects.filter(ad_space=ad_space_locked).exclude(pk__in=keep_ids).delete()

        for kind, val, pos in steps:
            if kind == "e":
                AdSpaceImage.objects.filter(pk=val, ad_space=ad_space_locked).update(sort_order=pos)
            else:
                AdSpaceImage.objects.create(
                    ad_space=ad_space_locked,
                    image=files[val],
                    sort_order=pos,
                )

    ad_space.refresh_from_db()
    sync_cover_from_gallery(ad_space)
