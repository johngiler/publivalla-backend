"""
Disponibilidad marketplace por mes: la toma admite nuevas reservas si queda al menos
un mes futuro libre en la ventana del calendario (salvo estado «bloqueado» manual en ficha).
"""

from __future__ import annotations

from datetime import date

from apps.ad_spaces.models import AdSpace, AdSpaceAvailability
from apps.ad_spaces.utils.availability_calendar import (
    availability_calendar_years,
    calendar_ref_date,
    year_months_occupied,
)
def month_selectable_for_marketplace(
    year: int,
    month: int,
    occupied: list[bool],
    *,
    ref: date | None = None,
) -> bool:
    """Mes elegible: libre y no pasado; el mes en curso solo hasta el día 15."""
    from apps.orders.utils.rental_month_eligibility import calendar_month_not_selectable

    ref = ref if ref is not None else calendar_ref_date()
    if month < 1 or month > 12 or len(occupied) != 12:
        return False
    if occupied[month - 1]:
        return False
    if calendar_month_not_selectable(year, month, ref):
        return False
    return True


def ad_space_has_selectable_future_month(
    ad_space_id: int,
    *,
    ref: date | None = None,
) -> bool:
    ref = ref if ref is not None else calendar_ref_date()
    for year in availability_calendar_years(ref=ref):
        occupied = year_months_occupied(ad_space_id, year)
        for month in range(1, 13):
            if month_selectable_for_marketplace(year, month, occupied, ref=ref):
                return True
    return False


def sync_ad_space_commercial_status(
    ad_space: AdSpace | int,
    *,
    ref: date | None = None,
    force_calendar: bool = False,
) -> str | None:
    """
    Alinea estado comercial según meses futuros reservables (pedidos + bloqueos en calendario).
    Disponible si queda al menos un mes libre; Ocupado si no.
    «Bloqueado» manual en ficha se conserva salvo force_calendar.
    """
    if isinstance(ad_space, int):
        row = AdSpace.objects.filter(pk=ad_space).first()
        if row is None:
            return None
        ad_space = row

    ref = ref if ref is not None else calendar_ref_date()

    if ad_space.availability == AdSpaceAvailability.BLOCKED and not force_calendar:
        return ad_space.availability

    has_months = ad_space_has_selectable_future_month(ad_space.pk, ref=ref)
    new_availability = (
        AdSpaceAvailability.AVAILABLE if has_months else AdSpaceAvailability.OCCUPIED
    )
    if ad_space.availability != new_availability:
        AdSpace.objects.filter(pk=ad_space.pk).update(availability=new_availability)
        ad_space.availability = new_availability
    return new_availability


def sync_ad_spaces_for_order(order) -> list[int]:
    """Tras cambios de pedido/bloqueos, alinea estado de las tomas afectadas."""
    from apps.orders.models import OrderItem

    ids = (
        OrderItem.objects.filter(order_id=order.pk)
        .values_list("ad_space_id", flat=True)
        .distinct()
    )
    updated: list[int] = []
    for ad_space_id in ids:
        prev = (
            AdSpace.objects.filter(pk=ad_space_id)
            .values_list("availability", flat=True)
            .first()
        )
        sync_ad_space_commercial_status(ad_space_id)
        curr = (
            AdSpace.objects.filter(pk=ad_space_id)
            .values_list("availability", flat=True)
            .first()
        )
        if prev != curr:
            updated.append(ad_space_id)
    return updated
