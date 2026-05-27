"""Temporada alta del canon de arrendamiento por centro comercial."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

# +30 % sobre el canon mensual en meses de temporada alta (requisito de negocio fijo).
HIGH_SEASON_LEASE_SURCHARGE = Decimal("1.30")

# Sambil Margarita: julio, agosto, noviembre, diciembre.
MARGARITA_HIGH_SEASON_MONTHS = [7, 8, 11, 12]
# Resto de centros comerciales: noviembre y diciembre.
DEFAULT_HIGH_SEASON_MONTHS = [11, 12]


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


def is_sambil_margarita_center(center) -> bool:
    """Centro Sambil Margarita (slug histórico smg o nombre/slug con «margarita»)."""
    slug = (getattr(center, "slug", None) or "").strip().lower()
    name = (getattr(center, "name", None) or "").strip().lower()
    if slug in ("smg", "sambil-margarita", "margarita"):
        return True
    if "margarita" in slug or "margarita" in name:
        return True
    return name == "sambil margarita"


def lease_high_season_months_for_center(center) -> list[int]:
    """Meses de temporada alta del canon según reglas por mall."""
    if is_sambil_margarita_center(center):
        return list(MARGARITA_HIGH_SEASON_MONTHS)
    return list(DEFAULT_HIGH_SEASON_MONTHS)


def apply_lease_high_season_on_center(center) -> None:
    """Aplica meses y recargo fijo (+30 %) antes de persistir."""
    center.high_season_months = lease_high_season_months_for_center(center)
    center.high_season_multiplier = HIGH_SEASON_LEASE_SURCHARGE


def is_high_season_month(center, month: int) -> bool:
    months = normalize_high_season_months(getattr(center, "high_season_months", None))
    return month in months


def high_season_multiplier(center) -> Decimal:
    """Factor de recargo en temporada alta (1.30 = +30 %); 1 si no hay meses configurados."""
    months = normalize_high_season_months(getattr(center, "high_season_months", None))
    if not months:
        return Decimal("1")
    return HIGH_SEASON_LEASE_SURCHARGE


def effective_monthly_price_for_month(
    base_monthly: Decimal,
    center,
    month: int,
) -> Decimal:
    """Precio mensual aplicable a un mes calendario concreto."""
    if is_high_season_month(center, month):
        return (base_monthly * HIGH_SEASON_LEASE_SURCHARGE).quantize(Decimal("0.01"))
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
