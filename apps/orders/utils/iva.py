"""IVA de marketplace: 16 % salvo que el centro comercial no cobre impuesto."""

from decimal import Decimal

STANDARD_IVA_RATE = Decimal("0.16")


def iva_rate_for_center(center) -> Decimal:
    if center is None or getattr(center, "charges_iva", True):
        return STANDARD_IVA_RATE
    return Decimal("0")


def quantize_money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def iva_for_subtotal(subtotal, rate) -> Decimal:
    return quantize_money(Decimal(subtotal or 0) * Decimal(rate or 0))


def order_tax_breakdown(order) -> dict:
    """IVA por línea (tasa congelada). El subtotal comercial es ``order.total_amount``."""
    items = list(order.items.all())
    iva = Decimal("0")
    rates = []
    for item in items:
        rate = item.iva_rate if item.iva_rate is not None else STANDARD_IVA_RATE
        rates.append(Decimal(rate))
        iva += iva_for_subtotal(item.subtotal, rate)
    subtotal = quantize_money(order.total_amount)
    iva = quantize_money(iva)
    uniform = rates[0] if rates and all(rate == rates[0] for rate in rates) else None
    return {
        "subtotal": subtotal,
        "iva_amount": iva,
        "total_with_iva": quantize_money(subtotal + iva),
        "iva_percent": None if uniform is None else int(uniform * 100),
    }


def iva_on_base(order, base) -> Decimal:
    """IVA proporcional a una porción del subtotal (cuota)."""
    summary = order_tax_breakdown(order)
    subtotal = summary["subtotal"]
    if subtotal == 0:
        return Decimal("0.00")
    return quantize_money(Decimal(base or 0) * summary["iva_amount"] / subtotal)


def iva_label(order) -> str:
    percent = order_tax_breakdown(order)["iva_percent"]
    if percent is None:
        return "IVA"
    return f"IVA ({percent} %)"
