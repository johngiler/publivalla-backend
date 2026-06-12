"""Adjunta PDFs generados al pedido (hoja negociación, carta municipio, factura)."""

from __future__ import annotations

import logging

from django.core.files.base import ContentFile
from django.utils import timezone

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
    had_signed = bool(
        getattr(order.negotiation_sheet_signed, "name", "")
        if order.negotiation_sheet_signed
        else ""
    )
    neg = build_negotiation_sheet_pdf_bytes(order=order)
    auth = build_municipality_authorization_pdf_bytes(order=order)
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    _delete_field_file(order, "negotiation_sheet_pdf")
    _delete_field_file(order, "municipality_authorization_pdf")
    if had_signed:
        _delete_field_file(order, "negotiation_sheet_signed")
    order.negotiation_sheet_pdf.save(
        f"negociacion_pedido_{order.pk}_{ts}.pdf",
        ContentFile(neg),
        save=False,
    )
    order.municipality_authorization_pdf.save(
        f"carta_municipio_pedido_{order.pk}_{ts}.pdf",
        ContentFile(auth),
        save=False,
    )
    update_fields = [
        "negotiation_sheet_pdf",
        "municipality_authorization_pdf",
        "updated_at",
    ]
    if had_signed:
        update_fields.append("negotiation_sheet_signed")
    order.save(update_fields=update_fields)


def save_negotiation_sheet_signed_with_digital_signature(
    order: Order,
    signature_png: bytes,
) -> None:
    """Genera la hoja de negociación con firma del inquilino y la guarda como documento firmado."""
    from apps.orders.utils.pdf_documents import build_negotiation_sheet_pdf_bytes

    order.refresh_from_db()
    pdf_bytes = build_negotiation_sheet_pdf_bytes(
        order=order,
        tenant_signature_png=signature_png,
    )
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    _delete_field_file(order, "negotiation_sheet_signed")
    order.negotiation_sheet_signed.save(
        f"hoja_negociacion_firmada_digital_{order.pk}_{ts}.pdf",
        ContentFile(pdf_bytes),
        save=False,
    )
    order.save(update_fields=["negotiation_sheet_signed", "updated_at"])


def generate_invoice_pdf_for_order(order: Order) -> None:
    from apps.orders.services.payment_plan_services import order_uses_split_payment
    from apps.orders.utils.pdf_documents import build_invoice_pdf_bytes

    order.refresh_from_db()
    if order_uses_split_payment(order):
        generate_first_installment_invoice_pdf(order)
        return
    pdf = build_invoice_pdf_bytes(order=order)
    _delete_field_file(order, "invoice_pdf")
    order.invoice_pdf.save(
        f"factura_pedido_{order.pk}.pdf",
        ContentFile(pdf),
        save=False,
    )
    order.save(update_fields=["invoice_pdf", "updated_at"])


def generate_first_installment_invoice_pdf(order: Order) -> None:
    from apps.orders.models import OrderPaymentInstallmentStatus

    order.refresh_from_db()
    plan = order.payment_plan
    inst = plan.installments.order_by("sequence").first()
    if inst is None:
        raise ValueError("El plan de pago no tiene cuotas.")
    generate_installment_invoice_pdf(inst)


def generate_installment_invoice_pdf(installment) -> None:
    from apps.orders.models import OrderPaymentInstallmentStatus
    from apps.orders.services.payment_plan_services import sync_installment_status
    from apps.orders.utils.pdf_documents import build_invoice_pdf_bytes

    order = installment.plan.order
    order.refresh_from_db()
    pdf = build_invoice_pdf_bytes(order=order, installment=installment)
    if installment.invoice_pdf:
        try:
            installment.invoice_pdf.delete(save=False)
        except Exception as exc:
            logger.warning(
                "No se pudo borrar factura previa de cuota %s: %s",
                installment.pk,
                exc,
            )
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    installment.invoice_pdf.save(
        f"factura_cuota_{installment.sequence}_pedido_{order.pk}_{ts}.pdf",
        ContentFile(pdf),
        save=False,
    )
    sync_installment_status(installment)
    installment.save(update_fields=["invoice_pdf", "status", "updated_at"])
