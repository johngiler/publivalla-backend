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


def ad_space_all_location_texts(ad_space) -> list[str]:
    """Ubicaciones distintas de las líneas de formato (orden de sort_order)."""
    seen: set[str] = set()
    out: list[str] = []
    for row in ad_space_formats_ordered(ad_space):
        loc = (row.location or "").strip()
        if loc and loc not in seen:
            seen.add(loc)
            out.append(loc)
    if not out:
        fallback = (getattr(ad_space, "name", None) or "").strip()
        if fallback:
            out.append(fallback)
    return out


def ad_space_element_summary(ad_space) -> str:
    """Código de toma con tipos de elemento, para PDFs de pedido."""
    code = (getattr(ad_space, "code", None) or "").strip()
    type_names: list[str] = []
    for row in ad_space_formats_ordered(ad_space):
        pt = getattr(row, "product_type", None)
        name = (getattr(pt, "name", None) or "").strip()
        if name and name not in type_names:
            type_names.append(name)
    if code and type_names:
        return f"{code} ({', '.join(type_names)})"
    return code or (getattr(ad_space, "name", None) or "").strip() or "—"


def format_type_name(fmt) -> str:
    if fmt is None:
        return "—"
    pt = getattr(fmt, "product_type", None)
    return (getattr(pt, "name", None) or "").strip() or "—"


def format_medidas_label(fmt) -> str:
    if fmt is None:
        return "—"
    w = fmt.width if fmt.width is not None else ""
    h = fmt.height if fmt.height is not None else ""
    if w != "" and h != "":
        return f"{w}×{h}"
    return "—"


def format_double_sided_observation(fmt) -> str:
    if fmt is None:
        return "—"
    return "Elemento a doble cara" if fmt.double_sided else "Elemento a una cara"
