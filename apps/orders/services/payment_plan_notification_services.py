"""Recordatorios por correo de cuotas próximas a vencer (pago por partes)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.orders.models import (
    OrderPaymentInstallment,
    OrderPaymentInstallmentStatus,
    OrderStatus,
)
from apps.orders.utils.email_notifications import (
    try_send_payment_installment_due_reminder_emails,
)

logger = logging.getLogger(__name__)

INSTALLMENT_DUE_NOTIFY_DAYS_BEFORE = (2, 1)

_INSTALLMENT_NOTIFY_ORDER_STATUSES = frozenset(
    {
        OrderStatus.INVOICED,
        OrderStatus.PAID,
        OrderStatus.PERMIT_PENDING,
        OrderStatus.INSTALLATION,
        OrderStatus.ACTIVE,
    }
)


def _installments_due_in_days(
    reference_date: date,
    *,
    days_before: int,
) -> list[OrderPaymentInstallment]:
    target_due = reference_date + timedelta(days=days_before)
    notified_field = (
        "notified_2d_at" if days_before == 2 else "notified_1d_at"
    )
    qs = (
        OrderPaymentInstallment.objects.filter(
            plan__enabled=True,
            plan__order__status__in=_INSTALLMENT_NOTIFY_ORDER_STATUSES,
            due_date=target_due,
        )
        .exclude(status=OrderPaymentInstallmentStatus.PAID)
        .filter(**{f"{notified_field}__isnull": True})
        .select_related("plan__order__client__workspace")
        .prefetch_related("months", "plan__installments")
        .order_by("due_date", "sequence", "id")
    )
    return list(qs)


def _notify_installment(
    installment: OrderPaymentInstallment,
    *,
    days_before: int,
    dry_run: bool,
) -> bool:
    notified_field = (
        "notified_2d_at" if days_before == 2 else "notified_1d_at"
    )
    if getattr(installment, notified_field):
        return False

    if dry_run:
        return True

    with transaction.atomic():
        locked = (
            OrderPaymentInstallment.objects.select_for_update()
            .select_related("plan__order__client__workspace")
            .prefetch_related("months", "plan__installments")
            .get(pk=installment.pk)
        )
        if getattr(locked, notified_field):
            return False
        sent = try_send_payment_installment_due_reminder_emails(
            locked,
            days_before=days_before,
        )
        if not sent:
            return False
        setattr(locked, notified_field, timezone.now())
        locked.save(update_fields=[notified_field, "updated_at"])
        return True


def notify_payment_installments_due(
    *,
    reference_date: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Envía recordatorios 2 y 1 día antes del vencimiento de cada cuota pendiente.

    Independiente de la generación de facturas (``invoice_due_payment_installments``).
    """
    ref = reference_date or timezone.localdate()
    notified = 0
    would_notify = 0
    errors: list[dict] = []
    pending: list[dict] = []

    for days_before in INSTALLMENT_DUE_NOTIFY_DAYS_BEFORE:
        for inst in _installments_due_in_days(ref, days_before=days_before):
            if dry_run:
                would_notify += 1
                pending.append(
                    {
                        "installment_id": inst.pk,
                        "order_id": inst.plan.order_id,
                        "days_before": days_before,
                        "due_date": inst.due_date.isoformat(),
                    }
                )
                continue
            try:
                if _notify_installment(inst, days_before=days_before, dry_run=False):
                    notified += 1
            except Exception as exc:
                logger.exception(
                    "No se pudo notificar cuota %s del pedido %s (%s días antes)",
                    inst.pk,
                    inst.plan.order_id,
                    days_before,
                )
                errors.append(
                    {
                        "installment_id": inst.pk,
                        "order_id": inst.plan.order_id,
                        "days_before": days_before,
                        "error": str(exc),
                    }
                )

    if dry_run:
        return {
            "would_notify": would_notify,
            "installments": pending,
            "reference_date": ref.isoformat(),
        }
    return {
        "notified": notified,
        "reference_date": ref.isoformat(),
        "errors": errors,
    }
