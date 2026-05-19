"""Filtros de catálogo por relación del cliente (favoritos, reservas, activos, carrito)."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.ad_spaces.utils.availability_calendar import (
    CLIENT_ACTIVE_ORDER_STATUSES,
    CLIENT_RESERVED_ORDER_STATUSES,
)
from apps.clients.models import ClientAdSpaceFavorite
from apps.orders.models import OrderItem

MINE_FAVORITES = "favorites"
MINE_ACTIVE = "active"
MINE_RESERVED = "reserved"
MINE_CART = "cart"

VALID_MINE_SCOPES = frozenset(
    {MINE_FAVORITES, MINE_ACTIVE, MINE_RESERVED, MINE_CART},
)


def parse_cart_ad_space_ids(raw: str) -> list[int]:
    """IDs de tomas en carrito (query `cart_ids`, separados por coma)."""
    if not raw or not str(raw).strip():
        return []
    out: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
        if len(out) >= 80:
            break
    return out


def ad_space_ids_client_favorites(client_id: int) -> QuerySet:
    return ClientAdSpaceFavorite.objects.filter(client_id=client_id).values_list(
        "ad_space_id", flat=True
    )


def ad_space_ids_client_reserved(client_id: int) -> QuerySet:
    return (
        OrderItem.objects.filter(
            order__client_id=client_id,
            order__status__in=CLIENT_RESERVED_ORDER_STATUSES,
        )
        .values_list("ad_space_id", flat=True)
        .distinct()
    )


def ad_space_ids_client_active(client_id: int) -> QuerySet:
    return (
        OrderItem.objects.filter(
            order__client_id=client_id,
            order__status__in=CLIENT_ACTIVE_ORDER_STATUSES,
        )
        .values_list("ad_space_id", flat=True)
        .distinct()
    )


def apply_catalog_mine_filter(
    qs: QuerySet,
    *,
    mine: str,
    client_id: int | None,
    cart_ad_space_ids: list[int] | None = None,
) -> QuerySet:
    """Restringe el queryset de catálogo según `mine` (requiere cliente salvo carrito por IDs)."""
    scope = (mine or "").strip().lower()
    if scope not in VALID_MINE_SCOPES:
        return qs
    if scope == MINE_CART:
        ids = cart_ad_space_ids or []
        if not ids:
            return qs.none()
        return qs.filter(pk__in=ids)
    if client_id is None:
        return qs.none()
    if scope == MINE_FAVORITES:
        return qs.filter(pk__in=ad_space_ids_client_favorites(client_id))
    if scope == MINE_RESERVED:
        return qs.filter(pk__in=ad_space_ids_client_reserved(client_id))
    if scope == MINE_ACTIVE:
        return qs.filter(pk__in=ad_space_ids_client_active(client_id))
    return qs


def count_catalog_scope(
    base_qs: QuerySet,
    scope: str,
    *,
    client_id: int | None,
    cart_ad_space_ids: list[int] | None = None,
) -> int:
    return apply_catalog_mine_filter(
        base_qs,
        mine=scope,
        client_id=client_id,
        cart_ad_space_ids=cart_ad_space_ids,
    ).count()
