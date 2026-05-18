import re

_ORDER_REF_PAD = 6


def format_order_public_reference(sequence_number, workspace_slug: str = "") -> str:
    """
    Referencia legible del pedido para listados y UI (no es número de factura fiscal).

    Formato: #<SLUG_WORKSPACE>-ORDER-<secuencia con ceros>, p. ej. #SAMBIL-ORDER-000001.
    La secuencia es por workspace (1.º pedido del tenant = 000001), no el id global de BD.
    Si no hay slug, se usa el segmento OWNER.
    """
    slug = (workspace_slug or "").strip().upper()
    slug = re.sub(r"[^A-Z0-9_-]", "", slug)
    if not slug:
        slug = "OWNER"
    slug = slug[:32]

    try:
        n = int(sequence_number)
    except (TypeError, ValueError):
        suffix = re.sub(r"\s+", "", str(sequence_number or "")) or "0"
        return f"#{slug}-ORDER-{suffix}"

    if n < 0:
        n = 0
    suffix = str(n).zfill(_ORDER_REF_PAD)
    return f"#{slug}-ORDER-{suffix}"


def workspace_order_sequence(order_pk: int, workspace_id: int) -> int:
    """Ordinal del pedido dentro del workspace (por orden de creación, pk)."""
    from apps.orders.models import Order

    return Order.objects.filter(
        client__workspace_id=workspace_id,
        pk__lte=order_pk,
    ).count()
