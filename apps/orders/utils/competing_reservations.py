"""
Adjudicación entre solicitudes enviadas (pujas): varios clientes envían la misma toma;
el admin elige qué pedido pasa a «Solicitud aprobada» y cancela el resto.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Count

from apps.ad_spaces.models import AdSpace
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.orders.services.order_services import log_order_status_transition
from apps.orders.utils.validators import PIPELINE_STATUSES, date_ranges_overlap
from apps.workspaces.models import Workspace

NOTE_COMPETING_LOST = "Otra solicitud fue adjudicada para esta toma."
NOTE_COMPETING_WON = "Solicitud adjudicada entre varias enviadas para la misma toma."


def workspace_competing_reservations_enabled(workspace: Workspace | None) -> bool:
    """Pujas (varias solicitudes enviadas por toma) forman parte del flujo estándar."""
    return workspace is not None


def pipeline_statuses_blocking_marketplace(workspace: Workspace | None) -> tuple[str, ...]:
    """
    Estados que bloquean un nuevo envío o el calendario público.
    Con pujas activas, «enviada» no bloquea: compiten hasta que el admin adjudica.
    """
    if workspace_competing_reservations_enabled(workspace):
        return tuple(s for s in PIPELINE_STATUSES if s != OrderStatus.SUBMITTED)
    return PIPELINE_STATUSES


def _workspace_for_ad_space(ad_space_id: int) -> Workspace | None:
    row = (
        AdSpace.objects.filter(pk=ad_space_id)
        .select_related("shopping_center__workspace")
        .first()
    )
    if row is None:
        return None
    return row.shopping_center.workspace


def order_item_conflicts_with_workspace(
    ad_space_id: int,
    start: date,
    end: date,
    *,
    exclude_order_id: int | None = None,
    workspace: Workspace | None = None,
) -> bool:
    if workspace is None:
        workspace = _workspace_for_ad_space(ad_space_id)
    statuses = pipeline_statuses_blocking_marketplace(workspace)

    q_items = OrderItem.objects.filter(ad_space_id=ad_space_id).filter(
        order__status__in=statuses
    )
    if exclude_order_id is not None:
        q_items = q_items.exclude(order_id=exclude_order_id)

    for row in q_items.iterator():
        if date_ranges_overlap(start, end, row.start_date, row.end_date):
            return True

    from apps.availability.models import AvailabilityBlock, AvailabilityBlockType

    from apps.ad_spaces.utils.availability_calendar import calendar_ref_date

    ref = calendar_ref_date()
    blocks = AvailabilityBlock.objects.filter(
        ad_space_id=ad_space_id,
        is_active=True,
        type=AvailabilityBlockType.OCCUPIED,
        end_date__gte=ref,
    )
    for b in blocks.iterator():
        if date_ranges_overlap(start, end, b.start_date, b.end_date):
            return True

    return False


def _orders_for_space_submitted(ad_space_id: int, workspace: Workspace) -> list[Order]:
    order_ids = (
        OrderItem.objects.filter(
            ad_space_id=ad_space_id,
            order__status=OrderStatus.SUBMITTED,
            order__client__workspace=workspace,
        )
        .values_list("order_id", flat=True)
        .distinct()
    )
    return list(
        Order.objects.filter(pk__in=order_ids)
        .select_related("client")
        .prefetch_related("items__ad_space")
        .order_by("submitted_at", "pk")
    )


def count_competing_submission_groups(workspace: Workspace) -> int:
    """Número de tomas con dos o más solicitudes enviadas pendientes de adjudicar."""
    return len(list_competing_submission_groups(workspace))


def list_competing_submission_groups(workspace: Workspace) -> list[dict]:
    """Tomas con dos o más pedidos en estado «enviada»."""
    rows = (
        OrderItem.objects.filter(
            order__status=OrderStatus.SUBMITTED,
            ad_space__shopping_center__workspace=workspace,
        )
        .values("ad_space_id")
        .annotate(order_count=Count("order_id", distinct=True))
        .filter(order_count__gte=2)
        .order_by("ad_space_id")
    )

    groups: list[dict] = []
    for row in rows:
        ad_space_id = row["ad_space_id"]
        ad = (
            AdSpace.objects.filter(pk=ad_space_id)
            .select_related("shopping_center")
            .first()
        )
        if ad is None:
            continue
        orders = _orders_for_space_submitted(ad_space_id, workspace)
        if len(orders) < 2:
            continue
        groups.append(
            {
                "ad_space_id": ad.pk,
                "ad_space_code": ad.code,
                "ad_space_title": ad.title,
                "shopping_center_name": ad.shopping_center.name,
                "orders": [_serialize_competing_order(o, ad_space_id) for o in orders],
            }
        )
    return groups


def _serialize_competing_order(order: Order, ad_space_id: int) -> dict:
    lines = [
        item
        for item in order.items.all()
        if item.ad_space_id == ad_space_id
    ]
    line = lines[0] if lines else None
    period_lines = [
        {
            "start_date": item.start_date.isoformat(),
            "end_date": item.end_date.isoformat(),
            "subtotal": str(item.subtotal),
        }
        for item in lines
    ]
    return {
        "id": order.pk,
        "code": order.code,
        "client_name": (order.client.company_name or "").strip(),
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        "hold_expires_at": order.hold_expires_at.isoformat() if order.hold_expires_at else None,
        "total_amount": str(order.total_amount),
        "start_date": line.start_date.isoformat() if line else None,
        "end_date": line.end_date.isoformat() if line else None,
        "period_lines": period_lines,
    }


@transaction.atomic
def award_competing_submission(
    *,
    workspace: Workspace,
    ad_space_id: int,
    winner_order_id: int,
    actor: AbstractBaseUser | None,
) -> dict:
    orders = _orders_for_space_submitted(ad_space_id, workspace)
    if len(orders) < 2:
        raise ValueError("No hay varias solicitudes enviadas para esta toma.")

    winner = next((o for o in orders if o.pk == winner_order_id), None)
    if winner is None:
        raise ValueError("El pedido elegido no está entre las solicitudes en disputa.")

    losers = [o for o in orders if o.pk != winner_order_id]

    from apps.orders.services.order_hold_services import (
        NOTE_CANCELLED_BY_TEAM,
        cancel_order_releasing_hold,
        reserve_ad_spaces_for_order,
    )

    for loser in losers:
        cancel_order_releasing_hold(
            loser,
            actor=actor,
            note=NOTE_COMPETING_LOST,
        )

    prev = winner.status
    winner.status = OrderStatus.CLIENT_APPROVED
    winner.hold_expires_at = None
    winner.save(update_fields=["status", "hold_expires_at", "updated_at"])
    log_order_status_transition(
        winner,
        prev,
        OrderStatus.CLIENT_APPROVED,
        actor=actor,
        note=NOTE_COMPETING_WON,
    )
    from apps.orders.services.order_hold_services import on_order_status_changed

    on_order_status_changed(
        winner,
        prev,
        OrderStatus.CLIENT_APPROVED,
        actor=actor,
    )
    reserve_ad_spaces_for_order(winner)

    from apps.orders.utils.document_generation import generate_negotiation_and_municipality_pdfs

    generate_negotiation_and_municipality_pdfs(winner)
    winner.refresh_from_db()

    from apps.orders.tasks import schedule_notify_client_activation_after_approval

    transaction.on_commit(lambda: schedule_notify_client_activation_after_approval(winner.pk))

    return {
        "winner_order_id": winner.pk,
        "cancelled_order_ids": [o.pk for o in losers],
    }
