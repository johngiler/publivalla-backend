import re

_ORDER_REF_PAD = 6


def format_order_public_reference(order_id, workspace_slug: str = "") -> str:
    """
    Referencia legible del pedido para listados y UI (no es número de factura fiscal).

    Formato: #<SLUG_WORKSPACE>-ORDER-<id con ceros a la izquierda>, p. ej. #ACME-ORDER-000001.
    Si no hay slug, se usa el segmento OWNER.
    """
    slug = (workspace_slug or "").strip().upper()
    slug = re.sub(r"[^A-Z0-9_-]", "", slug)
    if not slug:
        slug = "OWNER"
    slug = slug[:32]

    try:
        n = int(order_id)
    except (TypeError, ValueError):
        suffix = re.sub(r"\s+", "", str(order_id or "")) or "0"
        return f"#{slug}-ORDER-{suffix}"

    if n < 0:
        n = 0
    suffix = str(n).zfill(_ORDER_REF_PAD)
    return f"#{slug}-ORDER-{suffix}"
