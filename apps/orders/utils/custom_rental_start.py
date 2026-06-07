"""Fecha de inicio de alquiler personalizada (admin, post-negociación)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from apps.orders.utils.rental_billing import line_subtotal_for_center


def reservation_month_anchor(start: date) -> date:
    """Primer día del mes inicial de la reserva (mes de inicio del período)."""
    return date(start.year, start.month, 1)


def first_day_of_next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def custom_rental_start_day_bounds(
    reservation_anchor: date,
    *,
    ref: date,
) -> tuple[date, date]:
    """
    Rango permitido para elegir el día de inicio dentro del mes inicial.
    - Mes en curso: desde hoy hasta fin de mes.
    - Mes futuro: todos los días del mes.
    """
    year, month = reservation_anchor.year, reservation_anchor.month
    last = date(year, month, monthrange(year, month)[1])
    if year < ref.year or (year == ref.year and month < ref.month):
        raise ValueError("El mes inicial de la reserva ya no admite ajuste de inicio.")
    if year == ref.year and month == ref.month:
        return ref, last
    return date(year, month, 1), last


def validate_custom_rental_start_date(
    reservation_anchor: date,
    custom_start: date,
    *,
    ref: date,
) -> None:
    if custom_start.year != reservation_anchor.year or custom_start.month != reservation_anchor.month:
        raise ValueError(
            "La fecha de inicio debe caer dentro del mes inicial de la reserva."
        )
    min_d, max_d = custom_rental_start_day_bounds(reservation_anchor, ref=ref)
    if custom_start < min_d or custom_start > max_d:
        raise ValueError(
            f"Elige un día entre el {min_d.strftime('%d/%m/%Y')} y el {max_d.strftime('%d/%m/%Y')}."
        )


def catalog_subtotal_with_custom_start(
    monthly_price: Decimal,
    center,
    custom_start: date,
    end: date,
) -> Decimal:
    """Subtotal de catálogo con primer mes parcial y meses completos restantes."""
    year, month = custom_start.year, custom_start.month
    last = date(year, month, monthrange(year, month)[1])
    first_part = line_subtotal_for_center(monthly_price, center, custom_start, last)
    rem_start = first_day_of_next_month(custom_start)
    if rem_start > end:
        return first_part.quantize(Decimal("0.01"))
    rest = line_subtotal_for_center(monthly_price, center, rem_start, end)
    return (first_part + rest).quantize(Decimal("0.01"))


def agreed_subtotal_with_custom_start(
    first_month_agreed: Decimal,
    monthly_price: Decimal,
    center,
    custom_start: date,
    end: date,
) -> Decimal:
    """Subtotal acordado: importe del mes inicial + catálogo de meses completos restantes."""
    rem_start = first_day_of_next_month(custom_start)
    if rem_start > end:
        return first_month_agreed.quantize(Decimal("0.01"))
    rest = line_subtotal_for_center(monthly_price, center, rem_start, end)
    return (first_month_agreed + rest).quantize(Decimal("0.01"))
