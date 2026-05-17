"""
Portada efectiva de una toma (AdSpace).

Estructura de almacenamiento
---------------------------
- ``spaces/gallery/%Y/%m/``: filas ``AdSpaceImage`` (galería ordenada). Es la **fuente principal**
  de imágenes en admin y catálogo.
- ``spaces/covers/%Y/%m/``: campo ``AdSpace.cover_image`` (copia de la primera de galería).

``sync_cover_from_gallery`` (tras guardar galería) hace ``ad_space.cover_image = first.image``.
En Django eso suele **copiar** el fichero al ``upload_to`` de ``cover_image`` (``spaces/covers/…``),
de modo que puede haber **dos copias** en disco (mismo píxel, prefijos distintos). El API público prioriza siempre
la **galería** en este módulo y en ``AdSpaceSerializer``; ``cover_image`` queda como respaldo para
datos antiguos o código que lea el campo directamente.

No compartimos una sola ruta física entre ``AdSpaceImage`` y ``AdSpace.cover_image``: al borrar
una fila de galería Django elimina el fichero y rompería la otra referencia si apuntaran al mismo path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.ad_spaces.models import AdSpace


def ad_space_effective_cover_url(ad: AdSpace) -> str | None:
    """
    URL de almacenamiento de la portada mostrada: primera imagen de galería (orden
    ``sort_order``, ``id``); si no hay galería, ``cover_image`` (legacy).
    """
    first = (
        ad.gallery_images.all()
        .order_by("sort_order", "id")
        .first()
    )
    if first and first.image:
        return first.image.url
    if ad.cover_image:
        return ad.cover_image.url
    return None
