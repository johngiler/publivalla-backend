"""
Importación one-off de pedidos históricos del tenant Sambil.

Invocado desde la migración ``0013_import_sambil_historical_orders``.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

SAMBIL_WORKSPACE_SLUG = "sambil"
IMPORT_TAG = "[sambil-pedido-historico]"

_HISTORICAL_RESERVATION_DEFAULTS = {
    "promotion_brand": "Histórico",
    "campaign_concept": "Contrato histórico importado",
    "activity_description": "Reserva registrada en migración de datos históricos.",
}

_EXTRA_CLIENTS = [
    {
        "company_name": "INVERSIONES INA 001, C.A",
        "rif": "J-HIST-INA001-0",
        "email": "historico.ina001@sambil.import",
        "contact_name": "IMPORTACIÓN HISTÓRICA",
        "representative_name": "IMPORTACIÓN HISTÓRICA",
        "representative_id_number": "V-00.000.000",
        "phone": "",
        "address": "Registro histórico importado",
        "city": "CARACAS",
        "notes": "Cliente histórico migrado",
    },
]

_CLIENT_LOOKUP = {
    "mall_advertising": "MALL ADVERTISING PUBLICIDAD, C.A.",
    "grupo_cashea": "GRUPO CASHEA VE, C.A",
    "yummy_rides": "YUMMY RIDES, C.A.",
    "farmatodo": "FARMATODO, C.A",
    "operadora_50": "OPERADORA 50 C.A",
    "gh_estetica": "GH ESTETICA, C.A",
    "inversiones_ina": "INVERSIONES INA 001, C.A",
    "inversiones_canaima": "INVERSIONES CANAIMA 48, C.A.",
}

_AD_SPACE_CODE_ALIASES = {
    "SMRT5A": "SMR-T5A",
    "SCRT1B": "SCR-T1B",
    "TVL-T2D": "SVL-T2D",
}

_SAMBIL_HISTORICAL_ORDER_ROWS = [
    {
        "ad_space_code": "SMG-T4A",
        "client_key": "mall_advertising",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Este cliente tiene  un convenio de negocio, donde nos paga el 70% del "
            "canon  de arrendamiento"
        ),
    },
    {
        "ad_space_code": "SBR-T2",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SBR-T2",
        "client_key": "grupo_cashea",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T1A",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T5C",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T3A",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T4A",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T1A",
        "client_key": "grupo_cashea",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T5C",
        "client_key": "grupo_cashea",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T3A",
        "client_key": "grupo_cashea",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T4A",
        "client_key": "grupo_cashea",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SMR-T5C",
        "client_key": "yummy_rides",
        "start": date(2026, 6, 15),
        "end": date(2026, 10, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual (negociacion 4 mese y 15 dias)"
        ),
    },
    {
        "ad_space_code": "SMR-T5A",
        "client_key": "yummy_rides",
        "start": date(2026, 6, 15),
        "end": date(2026, 10, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual (negociacion 4 mese y 15 dias)"
        ),
    },
    {
        "ad_space_code": "SMR-T1B",
        "client_key": "yummy_rides",
        "start": date(2026, 6, 15),
        "end": date(2026, 10, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual (negociacion 4 mese y 15 dias)"
        ),
    },
    {
        "ad_space_code": "SSN-T4C",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SSN-T3B",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SSN-T4B",
        "client_key": "grupo_cashea",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SSN-T3B",
        "client_key": "grupo_cashea",
        "start": date(2026, 5, 1),
        "end": date(2026, 9, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SSN-T4A",
        "client_key": "farmatodo",
        "start": date(2026, 1, 1),
        "end": date(2026, 12, 31),
        "observation": "Condiciones de la negociaion 12 meses por adelantado",
    },
    {
        "ad_space_code": "SVL-T3B",
        "client_key": "operadora_50",
        "start": date(2026, 1, 1),
        "end": date(2026, 12, 31),
        "observation": (
            "Tarifa aprobada por ing Alfredo condiciones de pago mensual"
        ),
    },
    {
        "ad_space_code": "SVL-T3C",
        "client_key": "grupo_cashea",
        "start": date(2025, 12, 1),
        "end": date(2026, 4, 30),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SVL-T5",
        "client_key": "gh_estetica",
        "start": date(2026, 1, 1),
        "end": date(2026, 5, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SVL-T5",
        "client_key": "gh_estetica",
        "start": date(2026, 6, 1),
        "end": date(2026, 10, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SVL-T2A",
        "client_key": "yummy_rides",
        "start": date(2026, 4, 1),
        "end": date(2026, 8, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SVL-T2C",
        "client_key": "yummy_rides",
        "start": date(2026, 4, 1),
        "end": date(2026, 8, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SVL-T2D",
        "client_key": "yummy_rides",
        "start": date(2026, 4, 1),
        "end": date(2026, 8, 31),
        "observation": (
            "Condiciones de la negociacion: pago 2 meses por adelantado y 3 meses "
            "de manera mensual"
        ),
    },
    {
        "ad_space_code": "SLA-T7A",
        "client_key": "farmatodo",
        "start": date(2026, 3, 1),
        "end": date(2026, 8, 31),
        "observation": "condiciones de pago: de contado",
    },
    {
        "ad_space_code": "SCR-T2",
        "client_key": "inversiones_ina",
        "start": date(2026, 1, 1),
        "end": date(2026, 12, 31),
        "observation": (
            "Se le otorgo 25% de descuesto por pago adelantado de 12 meses"
        ),
    },
    {
        "ad_space_code": "SCR-T1B",
        "client_key": "inversiones_canaima",
        "start": date(2026, 4, 1),
        "end": date(2026, 4, 30),
        "observation": "negociacion por 1 mes",
    },
]

_PIPELINE_TO_ACTIVE = [
    "submitted",
    "client_approved",
    "art_approved",
    "invoiced",
    "paid",
    "permit_pending",
    "installation",
    "active",
]


def _normalize_ad_space_code(raw: str) -> str:
    code = (raw or "").strip().upper()
    return _AD_SPACE_CODE_ALIASES.get(code, code)


def _iter_calendar_months(start: date, end: date):
    y, m = start.year, start.month
    end_y, end_m = end.year, end.month
    while (y, m) <= (end_y, end_m):
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def _calendar_months_between(start: date, end: date) -> list[tuple[int, int]]:
    return list(_iter_calendar_months(start, end))


def _resolve_final_status(*, start: date, end: date, today: date) -> str:
    if end < today:
        return "expired"
    return "active"


def _parse_payment_plan_groups(
    months: list[tuple[int, int]],
    observation: str,
) -> list[list[tuple[int, int]]] | None:
    obs = (observation or "").lower()
    if "70%" in obs and "convenio" in obs:
        return None
    if "negociacion por 1 mes" in obs:
        return None

    match = re.search(
        r"pago\s+(\d+)\s+meses?\s+por\s+adelantado.*?(\d+)\s+meses?\s+(?:de\s+)?manera\s+mensual",
        obs,
    )
    if match:
        advance = int(match.group(1))
        monthly_count = int(match.group(2))
        if len(months) < advance + monthly_count:
            return None
        groups = [months[0:advance]]
        idx = advance
        for _ in range(monthly_count):
            groups.append([months[idx]])
            idx += 1
        return groups

    if "de contado" in obs:
        return [months]

    if re.search(r"12\s+meses?\s+por\s+adelantado", obs) or re.search(
        r"pago adelantado de 12 meses", obs
    ):
        return [months]

    if "pago mensual" in obs:
        return [[month] for month in months]

    return None


def _installment_status_for_historical(
    *,
    sequence: int,
    due_date: date,
    final_status: str,
    today: date,
) -> str:
    from apps.orders.models import OrderPaymentInstallmentStatus

    if final_status == "expired":
        return OrderPaymentInstallmentStatus.PAID
    if sequence == 1:
        return OrderPaymentInstallmentStatus.PAID
    if due_date <= today:
        return OrderPaymentInstallmentStatus.PAID
    return OrderPaymentInstallmentStatus.PENDING


def _ensure_extra_clients(workspace) -> None:
    from apps.clients.models import Client

    for row in _EXTRA_CLIENTS:
        rif = (row["rif"] or "").strip()
        if not rif:
            continue
        Client.objects.get_or_create(
            workspace=workspace,
            rif=rif,
            defaults={
                "company_name": row["company_name"],
                "email": row["email"],
                "contact_name": row["contact_name"],
                "representative_name": row["representative_name"],
                "representative_id_number": row["representative_id_number"],
                "phone": row["phone"],
                "address": row["address"],
                "city": row["city"],
                "notes": row["notes"],
                "status": "active",
                "is_active": True,
            },
        )


def _resolve_client(workspace, client_key: str):
    from apps.clients.models import Client

    company = _CLIENT_LOOKUP.get(client_key)
    if not company:
        return None
    return (
        Client.objects.filter(workspace=workspace, company_name__iexact=company)
        .order_by("id")
        .first()
    )


def _resolve_ad_space(workspace, code: str):
    from apps.ad_spaces.models import AdSpace

    normalized = _normalize_ad_space_code(code)
    qs = AdSpace.objects.filter(
        shopping_center__workspace=workspace,
    ).select_related("shopping_center")
    row = qs.filter(code__iexact=normalized).order_by("id").first()
    if row is not None:
        return row
    compact = re.sub(r"[\s\-]+", "", normalized)
    for sp in qs.order_by("id"):
        if re.sub(r"[\s\-]+", "", (sp.code or "").upper()) == compact:
            return sp
    return None


def _already_imported(*, client_id: int, ad_space_id: int, start: date, end: date) -> bool:
    from apps.orders.models import OrderItem

    return OrderItem.objects.filter(
        order__client_id=client_id,
        ad_space_id=ad_space_id,
        start_date=start,
        end_date=end,
        order__complementary_info__contains=IMPORT_TAG,
    ).exists()


def _emit_status_chain(order, *, final_status: str, t0: datetime) -> None:
    from apps.orders.models import OrderStatusEvent

    OrderStatusEvent.objects.filter(order_id=order.pk).delete()
    t = t0
    prev = ""
    for status in _PIPELINE_TO_ACTIVE:
        OrderStatusEvent.objects.create(
            order=order,
            from_status=prev,
            to_status=status,
            note="Importación histórica Sambil.",
            created_at=t,
        )
        prev = status
        t += timedelta(days=2)

    if final_status == "expired":
        OrderStatusEvent.objects.create(
            order=order,
            from_status="active",
            to_status="expired",
            note="Cierre de contrato histórico importado.",
            created_at=t + timedelta(days=1),
        )


def _create_payment_plan(order, groups: list[list[tuple[int, int]]], *, final_status: str, today: date) -> None:
    from apps.orders.models import (
        OrderPaymentInstallment,
        OrderPaymentInstallmentMonth,
        OrderPaymentPlan,
    )
    from apps.orders.services.payment_plan_services import order_month_amount_usd

    plan = OrderPaymentPlan.objects.create(order=order, enabled=True)
    for sequence, month_group in enumerate(groups, start=1):
        amount = sum(
            order_month_amount_usd(order, year, month)
            for year, month in month_group
        ).quantize(Decimal("0.01"))
        due_date = date(month_group[0][0], month_group[0][1], 1)
        status = _installment_status_for_historical(
            sequence=sequence,
            due_date=due_date,
            final_status=final_status,
            today=today,
        )
        installment = OrderPaymentInstallment.objects.create(
            plan=plan,
            sequence=sequence,
            due_date=due_date,
            amount=amount,
            status=status,
        )
        OrderPaymentInstallmentMonth.objects.bulk_create(
            [
                OrderPaymentInstallmentMonth(
                    installment=installment,
                    year=year,
                    month=month,
                )
                for year, month in month_group
            ]
        )


@transaction.atomic
def import_sambil_historical_orders() -> dict:
    from apps.orders.models import Order, OrderItem, OrderPaymentMethod
    from apps.orders.utils.rental_billing import line_subtotal_for_center
    from apps.orders.utils.validators import order_item_conflicts
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.filter(slug=SAMBIL_WORKSPACE_SLUG).first()
    if workspace is None:
        return {"skipped": "workspace_missing", "created": 0, "errors": []}

    _ensure_extra_clients(workspace)
    today = timezone.localdate()
    created = 0
    skipped = 0
    errors: list[str] = []

    for row in _SAMBIL_HISTORICAL_ORDER_ROWS:
        client = _resolve_client(workspace, row["client_key"])
        if client is None:
            errors.append(f"Cliente no encontrado: {row['client_key']}")
            continue

        ad_space = _resolve_ad_space(workspace, row["ad_space_code"])
        if ad_space is None:
            errors.append(f"Toma no encontrada: {row['ad_space_code']}")
            continue

        start = row["start"]
        end = row["end"]
        if _already_imported(
            client_id=client.pk,
            ad_space_id=ad_space.pk,
            start=start,
            end=end,
        ):
            skipped += 1
            continue

        if order_item_conflicts(ad_space.pk, start, end, exclude_order_id=None):
            errors.append(
                f"Conflicto de calendario: {row['ad_space_code']} "
                f"{start.isoformat()}–{end.isoformat()}"
            )
            continue

        final_status = _resolve_final_status(start=start, end=end, today=today)
        observation = (row["observation"] or "").strip()
        complementary_info = f"{observation}\n\n{IMPORT_TAG}"

        submitted_at = timezone.make_aware(
            datetime.combine(start - timedelta(days=45), time(10, 0))
        )

        order = Order.objects.create(
            client=client,
            status=final_status,
            total_amount=Decimal("0"),
            payment_method=OrderPaymentMethod.BANK_TRANSFER,
            submitted_at=submitted_at,
            installation_verified_at=(
                submitted_at + timedelta(days=30)
                if final_status in ("active", "expired")
                else None
            ),
            complementary_info=complementary_info,
            **_HISTORICAL_RESERVATION_DEFAULTS,
            created_at=submitted_at,
            updated_at=submitted_at,
        )

        monthly = ad_space.monthly_price_usd
        center = ad_space.shopping_center
        subtotal = line_subtotal_for_center(monthly, center, start, end)
        OrderItem.objects.create(
            order=order,
            ad_space=ad_space,
            start_date=start,
            end_date=end,
            monthly_price=monthly,
            subtotal=subtotal,
            original_subtotal=subtotal,
            created_at=submitted_at,
            updated_at=submitted_at,
        )
        order.total_amount = subtotal
        order.save(update_fields=["total_amount", "updated_at"])

        _emit_status_chain(order, final_status=final_status, t0=submitted_at)

        months = _calendar_months_between(start, end)
        plan_groups = _parse_payment_plan_groups(months, observation)
        if plan_groups:
            _create_payment_plan(
                order,
                plan_groups,
                final_status=final_status,
                today=today,
            )

        created += 1

    return {"created": created, "skipped": skipped, "errors": errors}


@transaction.atomic
def revert_sambil_historical_orders() -> int:
    from apps.orders.models import Order

    qs = Order.objects.filter(complementary_info__contains=IMPORT_TAG)
    count = qs.count()
    qs.delete()
    return count
