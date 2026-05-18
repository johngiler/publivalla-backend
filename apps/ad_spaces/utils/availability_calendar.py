"""Meses ocupados por toma (órdenes en pipeline + bloques) para catálogo público."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.conf import settings

from apps.availability.models import AvailabilityBlock, AvailabilityBlockType
from apps.orders.models import OrderItem
from apps.orders.utils.validators import PIPELINE_STATUSES, date_ranges_overlap

DEFAULT_CALENDAR_YEARS = 3


def availability_calendar_years(*, ref: date | None = None) -> list[int]:
    """Años mostrados en catálogo: año de referencia + los siguientes (p. ej. 3 años)."""
    y0 = (ref if ref is not None else date.today()).year
    n = int(getattr(settings, "AVAILABILITY_CALENDAR_YEARS", DEFAULT_CALENDAR_YEARS))
    n = max(1, min(n, 6))
    return list(range(y0, y0 + n))


def year_months_occupied(ad_space_id: int, year: int) -> list[bool]:
    """
    12 posiciones (índice 0 = enero). True = mes con solapamiento de reserva/bloqueo
    (segmento «ocupado» en UI).
    """
    flags = [False] * 12
    items = OrderItem.objects.filter(
        ad_space_id=ad_space_id,
        order__status__in=PIPELINE_STATUSES,
    ).values_list("start_date", "end_date")
    blocks = AvailabilityBlock.objects.filter(
        ad_space_id=ad_space_id,
        is_active=True,
        type__in=(
            AvailabilityBlockType.OCCUPIED,
            AvailabilityBlockType.BLOCKED,
            AvailabilityBlockType.RESERVED,
        ),
    ).values_list("start_date", "end_date")

    ranges = list(items) + list(blocks)

    for m in range(1, 13):
        first = date(year, m, 1)
        last = date(year, m, monthrange(year, m)[1])
        for s, e in ranges:
            if date_ranges_overlap(first, last, s, e):
                flags[m - 1] = True
                break

    return flags


def months_occupied_by_year(
    ad_space_id: int,
    *,
    ref: date | None = None,
) -> dict[int, list[bool]]:
    """Mapa año → 12 banderas de mes ocupado/no disponible en catálogo."""
    return {y: year_months_occupied(ad_space_id, y) for y in availability_calendar_years(ref=ref)}
