"""Meses ocupados por toma (órdenes en pipeline + bloqueos) para catálogo público."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.conf import settings
from django.utils import timezone

from apps.ad_spaces.models import AdSpace
from apps.availability.services.availability_block_services import (
    calendar_blocking_availability_blocks,
)
from apps.orders.models import OrderItem, OrderStatus
from apps.orders.utils.competing_reservations import pipeline_statuses_blocking_marketplace
from apps.orders.utils.validators import date_ranges_overlap

# Meses del cliente en catálogo: enviada → instalación (reservado) y activa (verde).
CLIENT_RESERVED_ORDER_STATUSES: tuple[str, ...] = (
    OrderStatus.SUBMITTED,
    OrderStatus.CLIENT_APPROVED,
    OrderStatus.INVOICED,
    OrderStatus.PAID,
    OrderStatus.ART_APPROVED,
    OrderStatus.PERMIT_PENDING,
    OrderStatus.INSTALLATION,
)
CLIENT_ACTIVE_ORDER_STATUSES: tuple[str, ...] = (OrderStatus.ACTIVE,)
CLIENT_HIGHLIGHT_ORDER_STATUSES: tuple[str, ...] = (
    CLIENT_RESERVED_ORDER_STATUSES + CLIENT_ACTIVE_ORDER_STATUSES
)

DEFAULT_CALENDAR_YEARS = 3


def calendar_ref_date() -> date:
    return timezone.localdate()


def active_availability_block_ranges(
    ad_space_id: int,
    *,
    ref: date | None = None,
) -> list[tuple[date, date]]:
    """Rangos de bloqueos ocupados vigentes (mantenimiento / reserva manual)."""
    ref = ref if ref is not None else calendar_ref_date()
    return list(
        calendar_blocking_availability_blocks(ad_space_id, ref=ref).values_list(
            "start_date", "end_date"
        )
    )


def availability_calendar_years(*, ref: date | None = None) -> list[int]:
    """Años mostrados en catálogo: año de referencia + los siguientes (p. ej. 3 años)."""
    y0 = (ref if ref is not None else calendar_ref_date()).year
    n = int(getattr(settings, "AVAILABILITY_CALENDAR_YEARS", DEFAULT_CALENDAR_YEARS))
    n = max(1, min(n, 6))
    return list(range(y0, y0 + n))


def _mark_year_months_from_ranges(
    flags: list[bool],
    ranges: list[tuple[date, date]],
    year: int,
) -> None:
    for m in range(1, 13):
        if flags[m - 1]:
            continue
        first = date(year, m, 1)
        last = date(year, m, monthrange(year, m)[1])
        for s, e in ranges:
            if date_ranges_overlap(first, last, s, e):
                flags[m - 1] = True
                break


def year_months_occupied(ad_space_id: int, year: int) -> list[bool]:
    """
    12 posiciones (índice 0 = enero). True = mes con solapamiento de reserva/bloqueo
    (segmento «ocupado» en UI).
    """
    flags = [False] * 12
    ad = (
        AdSpace.objects.filter(pk=ad_space_id)
        .select_related("shopping_center__workspace")
        .first()
    )
    workspace = ad.shopping_center.workspace if ad else None
    statuses = pipeline_statuses_blocking_marketplace(workspace)
    items = OrderItem.objects.filter(
        ad_space_id=ad_space_id,
        order__status__in=statuses,
    ).values_list("start_date", "end_date")
    ranges = list(items) + active_availability_block_ranges(ad_space_id)

    _mark_year_months_from_ranges(flags, ranges, year)
    return flags


def _year_flags_for_client_statuses(
    ad_space_id: int,
    client_id: int,
    year: int,
    statuses: tuple[str, ...],
) -> list[bool]:
    flags = [False] * 12
    items = OrderItem.objects.filter(
        ad_space_id=ad_space_id,
        order__client_id=client_id,
        order__status__in=statuses,
    ).values_list("start_date", "end_date")
    _mark_year_months_from_ranges(flags, list(items), year)
    return flags


def year_months_client_reserved(ad_space_id: int, client_id: int, year: int) -> list[bool]:
    """Meses con pedido enviado o en flujo previo a activa (chip «Reservado» / pipeline)."""
    return _year_flags_for_client_statuses(
        ad_space_id, client_id, year, CLIENT_RESERVED_ORDER_STATUSES
    )


def year_months_client_active(ad_space_id: int, client_id: int, year: int) -> list[bool]:
    """Meses con pedido o contrato activo (chip verde «Activa»)."""
    return _year_flags_for_client_statuses(
        ad_space_id, client_id, year, CLIENT_ACTIVE_ORDER_STATUSES
    )


def client_months_highlight_by_year(
    ad_space_id: int,
    client_id: int,
    *,
    ref: date | None = None,
) -> dict[str, dict[int, list[bool]]]:
    years = availability_calendar_years(ref=ref)
    return {
        "reserved": {
            y: year_months_client_reserved(ad_space_id, client_id, y) for y in years
        },
        "active": {
            y: year_months_client_active(ad_space_id, client_id, y) for y in years
        },
    }


def _empty_year_maps(
    ad_space_ids: list[int],
    years: list[int],
) -> dict[int, dict[int, list[bool]]]:
    return {aid: {y: [False] * 12 for y in years} for aid in ad_space_ids}


def client_months_highlight_by_year_bulk(
    ad_space_ids: list[int],
    client_id: int,
    *,
    ref: date | None = None,
) -> dict[str, dict[int, dict[int, list[bool]]]]:
    """``reserved`` y ``active``: ad_space_id → año → 12 banderas."""
    if not ad_space_ids:
        return {"reserved": {}, "active": {}}
    years = availability_calendar_years(ref=ref)
    out_reserved = _empty_year_maps(ad_space_ids, years)
    out_active = _empty_year_maps(ad_space_ids, years)
    rows = OrderItem.objects.filter(
        ad_space_id__in=ad_space_ids,
        order__client_id=client_id,
        order__status__in=CLIENT_HIGHLIGHT_ORDER_STATUSES,
    ).values_list("ad_space_id", "start_date", "end_date", "order__status")
    reserved_by_space: dict[int, list[tuple[date, date]]] = {}
    active_by_space: dict[int, list[tuple[date, date]]] = {}
    for ad_space_id, start, end, status in rows:
        if status == OrderStatus.ACTIVE:
            active_by_space.setdefault(ad_space_id, []).append((start, end))
        else:
            reserved_by_space.setdefault(ad_space_id, []).append((start, end))
    for aid in ad_space_ids:
        for y in years:
            _mark_year_months_from_ranges(
                out_reserved[aid][y], reserved_by_space.get(aid, []), y
            )
            _mark_year_months_from_ranges(
                out_active[aid][y], active_by_space.get(aid, []), y
            )
    return {"reserved": out_reserved, "active": out_active}


def months_occupied_by_year(
    ad_space_id: int,
    *,
    ref: date | None = None,
) -> dict[int, list[bool]]:
    """Mapa año → 12 banderas de mes ocupado/no disponible en catálogo."""
    return {y: year_months_occupied(ad_space_id, y) for y in availability_calendar_years(ref=ref)}
