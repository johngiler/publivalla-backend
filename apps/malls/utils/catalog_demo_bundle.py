"""
Catálogo de demostración (centro + tomas) sin PDF, para previsualizar el marketplace.

Usado por ``seed_production_catalog`` cuando no se pasa ``--pdf``.
"""

from __future__ import annotations

from decimal import Decimal

from apps.malls.utils.catalog_pdf_parser import ParsedCatalog, code_prefix_for_center_slug
from apps.workspaces.models import Workspace


def _display_brand(ws: Workspace) -> str:
    title = (getattr(ws, "marketplace_title", None) or "").strip()
    if title:
        return title
    name = (getattr(ws, "name", None) or "").strip()
    if name:
        return name
    return (getattr(ws, "slug", None) or "Marketplace").strip().title()


def build_demo_catalog_bundle(
    ws: Workspace,
    *,
    center_slug: str = "",
    code_prefix: str = "",
    toma_count: int = 12,
) -> ParsedCatalog:
    """
    Centro y tomas ficticios con todos los campos de catálogo rellenados.
    Los códigos de toma son únicos globalmente: ``{prefix}-T1`` … ``{prefix}-Tn``.
    """
    brand = _display_brand(ws)
    slug = (center_slug or "demo").strip().lower() or "demo"
    center_name = f"{brand} — Centro demostración"
    city = "Caracas"
    prefix = (code_prefix or "").strip().upper()
    if not prefix:
        prefix = code_prefix_for_center_slug(slug, center_name)
    if not prefix:
        slug_part = (ws.slug or "demo").upper().replace("-", "")[:6]
        prefix = f"{slug_part}-DEMO"

    n_tomas = max(4, min(int(toma_count), 24))

    toma_types = [
        "valla_vertical",
        "valla_horizontal",
        "pendon_balcon",
        "pendon_atrio",
        "pendon_pasillo",
        "gigantografia_fachada",
        "pendon_plaza",
        "pendon_columna",
    ]

    center = {
        "slug": slug,
        "name": center_name,
        "city": city,
        "address": f"Av. Principal de demostración, {city}.",
        "country": "Venezuela",
        "description": (
            f"Centro comercial de demostración para {brand}. "
            "Los datos son ficticios hasta recibir el catálogo oficial en PDF."
        ),
        "municipal_authority_line": f"Sres. Alcaldía — permiso demo ({city})",
        "municipal_permit_notice": (
            "Datos de demostración: el anunciante debe gestionar el permiso municipal "
            "correspondiente antes de la instalación."
        ),
        "advertising_regulations": (
            "<p>Normativa demo del centro:</p>"
            "<ul>"
            "<li>Artes en alta resolución y medidas según ficha de cada toma.</li>"
            "<li>Prohibido contenido que vulnere la ley o la convivencia del centro.</li>"
            "<li>Montaje solo por proveedores autorizados en el marketplace.</li>"
            "</ul>"
        ),
        "authorization_letter_city": city,
        "is_active": True,
        "code_prefix": prefix,
        "catalog_pdf_path": "",
    }

    ad_spaces: list[dict] = []
    for i in range(1, n_tomas + 1):
        type_slug = toma_types[(i - 1) % len(toma_types)]
        w = Decimal("4.00") + Decimal(i) * Decimal("0.25")
        h = Decimal("3.00") + Decimal((i % 3)) * Decimal("0.50")
        canon = Decimal("450") + Decimal(i) * Decimal("75")
        zone = ["Plaza central", "Pasillo norte", "Food court", "Entrada principal"][(i - 1) % 4]
        type_labels = {
            "valla_vertical": "Valla vertical",
            "valla_horizontal": "Valla horizontal",
            "pendon_balcon": "Pendón de balcón",
            "pendon_atrio": "Pendón de atrio",
            "pendon_pasillo": "Pendón de pasillo",
            "gigantografia_fachada": "Gigantografía en fachada",
            "pendon_plaza": "Pendón de plaza",
            "pendon_columna": "Pendón de columna",
        }
        ad_spaces.append(
            {
                "code": f"{prefix}-T{i}",
                "name": f"Toma demo {i} — {zone}",
                "description": (
                    f"Espacio publicitario de demostración ({type_labels.get(type_slug, type_slug)}). "
                    f"Medidas {w} × {h} m. Ubicación: {zone}, nivel {1 + (i % 3)}."
                ),
                "monthly_price_usd": str(canon),
                "availability": "available",
                "formats": [
                    {
                        "product_type_name": type_labels.get(type_slug, type_slug.replace("_", " ").title()),
                        "width": str(w),
                        "height": str(h),
                        "quantity": 1 + (i % 2),
                        "location": f"{zone}, nivel {1 + (i % 3)}, referencia demo {i}.",
                        "double_sided": i % 3 == 0,
                    }
                ],
            }
        )

    raw_meta = {
        "source": "demo_bundle",
        "workspace_slug": (ws.slug or "").strip().lower(),
        "tomas_detected": len(ad_spaces),
        "demo": True,
    }
    return ParsedCatalog(center=center, ad_spaces=ad_spaces, raw_meta=raw_meta)
