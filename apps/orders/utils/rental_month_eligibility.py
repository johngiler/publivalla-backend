"""Elegibilidad de meses calendario para reservas en marketplace."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

CURRENT_MONTH_SELECTABLE_UNTIL_DAY = 15


def current_month_selectable(ref: date) -> bool:
    return ref.day <= CURRENT_MONTH_SELECTABLE_UNTIL_DAY


def is_past_calendar_month(year: int, month: int, ref: date) -> bool:
    if year < ref.year:
        return True
    if year > ref.year:
        return False
    return month < ref.month


def is_current_month_blocked(year: int, month: int, ref: date) -> bool:
    if year != ref.year or month != ref.month:
        return False
    return ref.day > CURRENT_MONTH_SELECTABLE_UNTIL_DAY


def calendar_month_not_selectable(year: int, month: int, ref: date) -> bool:
    """True si el mes no admite nueva reserva (pasado o mes actual tras el día 15)."""
    return is_past_calendar_month(year, month, ref) or is_current_month_blocked(
        year, month, ref
    )


def first_allowed_monthly_rental_start_date(ref: date) -> date:
    """
    Primer día del primer mes reservable.
    El mes en curso es válido solo hasta el día 15 inclusive.
    """
    if current_month_selectable(ref):
        return date(ref.year, ref.month, 1)
    y, m = ref.year, ref.month
    if m == 12:
        return date(y + 1, 1, 1)
    return date(y, m + 1, 1)


def rental_start_allowed_for_marketplace(start: date, ref: date) -> bool:
    """True si la fecha de inicio no cae en un mes bloqueado para marketplace."""
    if start < first_allowed_monthly_rental_start_date(ref):
        return False
    if start.year == ref.year and start.month == ref.month:
        return start.day >= ref.day
    return True


def future_selectable_months_in_year(year: int, ref: date) -> int:
    """Meses aún elegibles en el año (incluye el mes actual si aplica la regla del día 15)."""
    if year < ref.year:
        return 0
    if year > ref.year:
        return 12
    if current_month_selectable(ref):
        return max(0, 12 - ref.month + 1)
    return max(0, 12 - ref.month)


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])
