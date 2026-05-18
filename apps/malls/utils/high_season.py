"""Temporada alta por centro comercial (meses recurrentes + multiplicador)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal



def normalize_high_season_months(raw) -> list[int]:
    """Meses 1–12 únicos y ordenados."""
    if not raw:
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[int] = []
    for x in raw:
        try:
            m = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= m <= 12 and m not in out:
            out.append(m)
    return sorted(out)


def is_high_season_month(center, month: int) -> bool:
    months = normalize_high_season_months(getattr(center, "high_season_months", None))
    return month in months


def high_season_multiplier(center) -> Decimal:
    raw = getattr(center, "high_season_multiplier", None)
    if raw is None:
        return Decimal("1")
    try:
        m = Decimal(str(raw))
    except Exception:
        return Decimal("1")
    if m < Decimal("1"):
        return Decimal("1")
    return m.quantize(Decimal("0.01"))


def effective_monthly_price_for_month(
    base_monthly: Decimal,
    center,
    month: int,
) -> Decimal:
    """Precio mensual aplicable a un mes calendario concreto."""
    if is_high_season_month(center, month):
        return (base_monthly * high_season_multiplier(center)).quantize(Decimal("0.01"))
    return base_monthly.quantize(Decimal("0.01"))


def iter_calendar_months_in_range(start: date, end: date):
    """(year, month) inclusivos entre start y end."""
    y, m = start.year, start.month
    end_y, end_m = end.year, end.month
    while (y, m) <= (end_y, end_m):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def line_subtotal_with_high_season(
    base_monthly: Decimal,
    center,
    start: date,
    end: date,
) -> Decimal:
    """Suma el precio mensual efectivo de cada mes del rango."""
    total = Decimal("0")
    for _year, month in iter_calendar_months_in_range(start, end):
        total += effective_monthly_price_for_month(base_monthly, center, month)
    return total.quantize(Decimal("0.01"))


def high_season_months_in_range(center, start: date, end: date) -> list[int]:
    """Meses del rango (1–12) que caen en temporada alta (sin duplicar año)."""
    seen: set[int] = set()
    for _y, month in iter_calendar_months_in_range(start, end):
        if is_high_season_month(center, month):
            seen.add(month)
    return sorted(seen)
