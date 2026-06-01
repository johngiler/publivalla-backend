"""Helpers de lectura para espacios publicitarios (catálogo, PDF, pedidos)."""

from __future__ import annotations


def ad_space_formats_ordered(ad_space):
    if hasattr(ad_space, "_prefetched_objects_cache") and "formats" in getattr(
        ad_space, "_prefetched_objects_cache", {}
    ):
        rows = list(ad_space.formats.all())
        rows.sort(key=lambda r: (r.sort_order, r.pk))
        return rows
    return list(
        ad_space.formats.select_related("product_type").order_by("sort_order", "id")
    )


def ad_space_primary_format(ad_space):
    rows = ad_space_formats_ordered(ad_space)
    return rows[0] if rows else None


def ad_space_type_label(ad_space) -> str:
    row = ad_space_primary_format(ad_space)
    if row is None:
        return ""
    pt = getattr(row, "product_type", None)
    return (getattr(pt, "name", None) or "").strip()


def ad_space_location_text(ad_space) -> str:
    row = ad_space_primary_format(ad_space)
    if row is not None:
        loc = (row.location or "").strip()
        if loc:
            return loc
    return (getattr(ad_space, "name", None) or "").strip()
