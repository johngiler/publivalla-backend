"""Unidad de facturación de reservas: solo meses de calendario."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.malls.utils.high_season import (
    high_season_multiplier,
    is_high_season_month,
    line_subtotal_with_high_season,
    normalize_high_season_months,
)
from apps.orders.utils.validators import (
    MIN_RESERVATION_CALENDAR_MONTHS,
    contract_meets_min_months,
    contract_months_inclusive,
)

MIN_RESERVATION_CALENDAR_DAYS = 1
DAYS_PER_MONTH_COMMERCIAL = Decimal("30")

CALENDAR_MONTH = "calendar_month"
CALENDAR_DAY = "calendar_day"


def normalize_rental_billing_unit(raw) -> str:
    """Siempre mes de calendario (cotización por día deshabilitada)."""
    return CALENDAR_MONTH


def is_daily_billing(unit: str) -> bool:
    return False


def contract_days_inclusive(start: date, end: date) -> int:
    if end < start:
        return 0
    return (end - start).days + 1


def daily_rate_from_monthly(monthly: Decimal) -> Decimal:
    m = Decimal(str(monthly))
    return (m / DAYS_PER_MONTH_COMMERCIAL).quantize(Decimal("0.01"))


def iter_days_in_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def line_subtotal_daily(
    base_monthly: Decimal,
    center,
    start: date,
    end: date,
) -> Decimal:
    """Canon diario = mensual / 30; temporada alta aplica por mes del día."""
    base = Decimal(str(base_monthly))
    day_base = daily_rate_from_monthly(base)
    mult = high_season_multiplier(center)
    hs = set(normalize_high_season_months(getattr(center, "high_season_months", None)))
    total = Decimal("0")
    for d in iter_days_in_range(start, end):
        rate = day_base
        if d.month in hs:
            rate = (day_base * mult).quantize(Decimal("0.01"))
        total += rate
    return total.quantize(Decimal("0.01"))


def line_subtotal_for_center(
    base_monthly: Decimal,
    center,
    start: date,
    end: date,
) -> Decimal:
    unit = normalize_rental_billing_unit(getattr(center, "rental_billing_unit", None))
    if is_daily_billing(unit):
        return line_subtotal_daily(base_monthly, center, start, end)
    return line_subtotal_with_high_season(base_monthly, center, start, end)


def contract_meets_minimum(unit: str, start: date, end: date) -> bool:
    if is_daily_billing(unit):
        return contract_days_inclusive(start, end) >= MIN_RESERVATION_CALENDAR_DAYS
    return contract_meets_min_months(start, end, MIN_RESERVATION_CALENDAR_MONTHS)


def min_units_label(unit: str) -> tuple[int, str]:
    if is_daily_billing(unit):
        n = MIN_RESERVATION_CALENDAR_DAYS
        return n, "día" if n == 1 else "días"
    n = MIN_RESERVATION_CALENDAR_MONTHS
    return n, "mes" if n == 1 else "meses"


def first_allowed_rental_start_date(
    unit: str,
    ref: date | None = None,
) -> date:
    """Primer día reservable: mes → día 1 del próximo mes; día → mañana."""
    r = ref if ref is not None else timezone.localdate()
    if is_daily_billing(unit):
        return r + timedelta(days=1)
    y, m = r.year, r.month
    if m == 12:
        return date(y + 1, 1, 1)
    return date(y, m + 1, 1)


def rental_start_allowed(unit: str, start: date, ref: date | None = None) -> bool:
    return start >= first_allowed_rental_start_date(unit, ref)


def total_billed_units(unit: str, start: date, end: date) -> int:
    if is_daily_billing(unit):
        return contract_days_inclusive(start, end)
    return contract_months_inclusive(start, end)
