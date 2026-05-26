"""Datos de proveedores de montaje para correos transaccionales del pedido."""

from __future__ import annotations

from apps.orders.models import Order, OrderItem
from apps.providers.models import MountingProvider


def order_mounting_provider_groups_by_center(
    order: Order,
) -> list[tuple[str, list[MountingProvider]]]:
    """
    Centros del pedido con sus proveedores de montaje activos (misma lógica que la API del pedido).

    Returns:
        Lista de (nombre del centro, proveedores) solo cuando hay al menos un proveedor.
    """
    center_ids = list(
        OrderItem.objects.filter(order_id=order.pk)
        .values_list("ad_space__shopping_center_id", flat=True)
        .distinct()
    )
    center_ids = sorted({cid for cid in center_ids if cid is not None})
    if not center_ids:
        return []

    from apps.malls.models import ShoppingCenter

    providers = list(
        MountingProvider.objects.filter(
            shopping_centers__in=center_ids,
            is_active=True,
        )
        .prefetch_related("shopping_centers")
        .order_by("sort_order", "company_name", "id")
        .distinct()
    )
    if not providers:
        return []

    centers = ShoppingCenter.objects.filter(pk__in=center_ids).order_by("name", "id")
    provider_center_ids: dict[int, set[int]] = {}
    for p in providers:
        provider_center_ids[p.pk] = {sc.pk for sc in p.shopping_centers.all()}

    groups: list[tuple[str, list[MountingProvider]]] = []
    for center in centers:
        center_providers = [
            p for p in providers if center.pk in provider_center_ids.get(p.pk, set())
        ]
        if center_providers:
            groups.append((center.name or "Centro comercial", center_providers))
    return groups


def format_mounting_provider_contact_line(provider: MountingProvider) -> str:
    """Una línea legible: empresa, contacto, teléfono y correo."""
    parts: list[str] = []
    company = (provider.company_name or "").strip()
    if company:
        parts.append(company)
    contact = (provider.contact_name or "").strip()
    if contact:
        parts.append(contact)
    phone = (provider.phone or "").strip()
    if phone:
        parts.append(phone)
    email = (provider.email or "").strip()
    if email:
        parts.append(email)
    return " · ".join(parts) if parts else "—"


def mounting_providers_plain_text(groups: list[tuple[str, list[MountingProvider]]]) -> str:
    if not groups:
        return ""
    lines = ["Empresas de montaje autorizadas", ""]
    for center_name, providers in groups:
        lines.append(f"{center_name}:")
        for p in providers:
            lines.append(f"  · {format_mounting_provider_contact_line(p)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def mounting_providers_html_block(groups: list[tuple[str, list[MountingProvider]]]) -> str:
    if not groups:
        return ""
    import html as html_module

    def esc(s: str) -> str:
        return html_module.escape((s or "").strip(), quote=True)

    blocks: list[str] = [
        '<p style="margin:0 0 10px;font:600 12px/1.4 system-ui,sans-serif;color:#71717a;">'
        "Empresas de montaje autorizadas</p>",
    ]
    for center_name, providers in groups:
        blocks.append(
            '<p style="margin:0 0 6px;font:600 13px/1.4 system-ui,sans-serif;color:#18181b;">'
            f"{esc(center_name)}</p>"
        )
        blocks.append('<ul style="margin:0 0 14px;padding:0 0 0 18px;font:14px/1.5 system-ui,sans-serif;color:#3f3f46;">')
        for p in providers:
            blocks.append(
                f"<li style=\"margin:0 0 4px;\">{esc(format_mounting_provider_contact_line(p))}</li>"
            )
        blocks.append("</ul>")
    return "".join(blocks)
