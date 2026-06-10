"""Reglas de negocio Fase 1: duración mínima, solapamiento, hold 72h."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.ad_spaces.models import AdSpaceAvailability
from apps.availability.models import AvailabilityBlock, AvailabilityBlockType
from apps.orders.models import OrderItem, OrderStatus


# Órdenes que reservan el espacio en el calendario (no borrador / cancelada / vencida)
MIN_RESERVATION_CALENDAR_MONTHS = 1

PIPELINE_STATUSES: tuple[str, ...] = (
    OrderStatus.SUBMITTED,
    OrderStatus.CLIENT_APPROVED,
    OrderStatus.ART_APPROVED,
    OrderStatus.INVOICED,
    OrderStatus.PAID,
    OrderStatus.PERMIT_PENDING,
    OrderStatus.INSTALLATION,
    OrderStatus.ACTIVE,
)

ORDER_LINE_PRICING_EDITABLE_STATUSES: frozenset[str] = frozenset(
    {
        OrderStatus.CLIENT_APPROVED,
        OrderStatus.ART_APPROVED,
    }
)

ORDER_STATUSES_WITH_NEGOTIATION_PDF: frozenset[str] = frozenset(
    {
        OrderStatus.CLIENT_APPROVED,
        OrderStatus.ART_APPROVED,
    }
)


def order_has_negotiation_sheet_pdf(order) -> bool:
    f = getattr(order, "negotiation_sheet_pdf", None)
    return bool(f and getattr(f, "name", ""))


def order_has_negotiation_sheet_signed(order) -> bool:
    f = getattr(order, "negotiation_sheet_signed", None)
    return bool(f and getattr(f, "name", ""))


def order_should_regenerate_negotiation_pdf(order) -> bool:
    """True si el pedido ya tiene (o debería tener) PDF de negociación generado."""
    if order.status in ORDER_STATUSES_WITH_NEGOTIATION_PDF:
        return True
    if order_has_negotiation_sheet_pdf(order):
        return True
    return order_has_negotiation_sheet_signed(order)


def order_line_pricing_editable(order) -> bool:
    """Precios, inicio de alquiler y archivos comerciales: solo tras aprobar la solicitud."""
    return order.status in ORDER_LINE_PRICING_EDITABLE_STATUSES


def order_admin_commercial_editable(order) -> bool:
    """Alias de ``order_line_pricing_editable`` para validaciones de admin."""
    return order_line_pricing_editable(order)


def ad_space_allows_marketplace_reservation(ad_space) -> bool:
    """
    Admite nuevas líneas si no está bloqueada manualmente y queda al menos
    un mes futuro libre en el calendario (aunque el estado guardado sea reservado/ocupado).
    """
    if getattr(ad_space, "availability", None) == AdSpaceAvailability.BLOCKED:
        return False
    from apps.ad_spaces.utils.marketplace_availability import ad_space_has_selectable_future_month

    return ad_space_has_selectable_future_month(ad_space.pk)


def contract_months_inclusive(start: date, end: date) -> int:
    """Meses de calendario cubiertos de forma inclusiva (regla comercial simple)."""
    if end < start:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def contract_meets_min_months(
    start: date, end: date, min_months: int = MIN_RESERVATION_CALENDAR_MONTHS
) -> bool:
    return contract_months_inclusive(start, end) >= min_months


def date_ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def order_request_items_have_internal_overlap(items: list) -> bool:
    """True si dos líneas del mismo pedido para la misma toma se solapan."""
    by_space: dict[int, list[tuple[date, date]]] = {}
    for row in items:
        aid = row["ad_space"].id
        by_space.setdefault(aid, []).append((row["start_date"], row["end_date"]))
    for ranges in by_space.values():
        for i, (a0, a1) in enumerate(ranges):
            for b0, b1 in ranges[i + 1 :]:
                if date_ranges_overlap(a0, a1, b0, b1):
                    return True
    return False


def order_item_conflicts(
    ad_space_id: int,
    start: date,
    end: date,
    *,
    exclude_order_id: int | None = None,
) -> bool:
    """True si ya hay una orden en pipeline u otro bloqueo que choque con [start, end]."""
    from apps.orders.utils.competing_reservations import order_item_conflicts_with_workspace

    return order_item_conflicts_with_workspace(
        ad_space_id,
        start,
        end,
        exclude_order_id=exclude_order_id,
    )


def line_subtotal(monthly_price: Decimal, start: date, end: date) -> Decimal:
    months = contract_months_inclusive(start, end)
    return (monthly_price * months).quantize(Decimal("0.01"))


def hold_expires_at_from_now(hours: int = 72) -> datetime:
    return timezone.now() + timedelta(hours=hours)


def first_allowed_monthly_rental_start_date(ref: date | None = None) -> date:
    from apps.orders.utils.rental_month_eligibility import (
        first_allowed_monthly_rental_start_date as _first_allowed,
    )

    r = ref if ref is not None else timezone.localdate()
    return _first_allowed(r)


def rental_start_allowed_for_marketplace(start: date, ref: date | None = None) -> bool:
    from apps.orders.utils.rental_month_eligibility import (
        rental_start_allowed_for_marketplace as _allowed,
    )

    r = ref if ref is not None else timezone.localdate()
    return _allowed(start, r)
