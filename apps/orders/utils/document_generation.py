"""Adjunta PDFs generados al pedido (hoja negociación, carta municipio, factura)."""

from __future__ import annotations

import logging

from django.core.files.base import ContentFile

from apps.orders.models import Order

logger = logging.getLogger(__name__)


def _delete_field_file(order: Order, field: str) -> None:
    f = getattr(order, field, None)
    if f:
        try:
            f.delete(save=False)
        except Exception as exc:  # pragma: no cover
            logger.warning("No se pudo borrar archivo %s del pedido %s: %s", field, order.pk, exc)
    setattr(order, field, None)


def generate_negotiation_and_municipality_pdfs(order: Order) -> None:
    """Genera y guarda hoja de negociación + carta de autorización alcaldía."""
    from apps.orders.utils.pdf_documents import (
        build_municipality_authorization_pdf_bytes,
        build_negotiation_sheet_pdf_bytes,
    )

    order.refresh_from_db()
    neg = build_negotiation_sheet_pdf_bytes(order=order)
    auth = build_municipality_authorization_pdf_bytes(order=order)
    _delete_field_file(order, "negotiation_sheet_pdf")
    _delete_field_file(order, "municipality_authorization_pdf")
    order.negotiation_sheet_pdf.save(
        f"negociacion_pedido_{order.pk}.pdf",
        ContentFile(neg),
        save=False,
    )
    order.municipality_authorization_pdf.save(
        f"carta_municipio_pedido_{order.pk}.pdf",
        ContentFile(auth),
        save=False,
    )
    order.save(
        update_fields=[
            "negotiation_sheet_pdf",
            "municipality_authorization_pdf",
            "updated_at",
        ]
    )


def generate_invoice_pdf_for_order(order: Order) -> None:
    from apps.orders.utils.pdf_documents import build_invoice_pdf_bytes

    order.refresh_from_db()
    pdf = build_invoice_pdf_bytes(order=order)
    _delete_field_file(order, "invoice_pdf")
    order.invoice_pdf.save(
        f"factura_pedido_{order.pk}.pdf",
        ContentFile(pdf),
        save=False,
    )
    order.save(update_fields=["invoice_pdf", "updated_at"])
