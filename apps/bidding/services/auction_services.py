from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.bidding.models import AuctionStatus, SpaceAuction, SpaceBid
from apps.bidding.utils.queries import (
    auction_high_bid_amount,
    minimum_next_bid_amount,
    other_open_auction_exists,
    workspace_bidding_enabled,
)
from apps.clients.models import Client
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.orders.services.order_services import submit_draft_order
from apps.orders.utils.validators import (
    ad_space_allows_marketplace_reservation,
    order_item_conflicts,
    rental_start_allowed_for_marketplace,
)
from apps.orders.utils.rental_billing import contract_meets_minimum, min_units_label


def _ensure_bidding_workspace(ws) -> None:
    if not workspace_bidding_enabled(ws):
        raise serializers.ValidationError(
            {"detail": "Las pujas no están habilitadas en este marketplace."}
        )


def validate_auction_period(ad_space, start_date, end_date, *, exclude_auction_id: int | None = None):
    if end_date < start_date:
        raise serializers.ValidationError(
            {"end_date": "La fecha de fin no puede ser anterior a la de inicio."}
        )
    center = ad_space.shopping_center
    unit = center.rental_billing_unit
    if not rental_start_allowed_for_marketplace(start_date):
        raise serializers.ValidationError(
            {
                "start_date": (
                    "La fecha de inicio no puede ser hoy ni un día pasado."
                    if unit == "calendar_day"
                    else "La fecha de inicio debe ser desde el próximo mes."
                ),
            }
        )
    if not contract_meets_minimum(unit, start_date, end_date):
        n, label = min_units_label(unit)
        raise serializers.ValidationError(
            {"detail": f"El período debe cubrir al menos {n} {label}."}
        )
    if order_item_conflicts(ad_space.id, start_date, end_date):
        raise serializers.ValidationError(
            {"detail": "El período choca con otra reserva o bloqueo existente."}
        )
    overlap = SpaceAuction.objects.filter(
        ad_space_id=ad_space.id,
        is_active=True,
        status__in=(AuctionStatus.DRAFT, AuctionStatus.OPEN, AuctionStatus.CLOSED),
    )
    if exclude_auction_id is not None:
        overlap = overlap.exclude(pk=exclude_auction_id)
    for auc in overlap.iterator():
        if start_date <= auc.end_date and auc.start_date <= end_date:
            raise serializers.ValidationError(
                {"detail": "Ya hay otra puja activa o pendiente que solapa este período."}
            )


@transaction.atomic
def open_auction(auction: SpaceAuction, *, actor: AbstractBaseUser | None = None) -> SpaceAuction:
    if auction.status != AuctionStatus.DRAFT:
        raise serializers.ValidationError({"detail": "Solo se pueden abrir pujas en borrador."})
    ws = auction.ad_space.shopping_center.workspace
    _ensure_bidding_workspace(ws)
    if not ad_space_allows_marketplace_reservation(auction.ad_space):
        raise serializers.ValidationError(
            {"detail": "La toma no está disponible para abrir una puja."}
        )
    if other_open_auction_exists(auction.ad_space_id, exclude_auction_id=auction.pk):
        raise serializers.ValidationError(
            {"detail": "Ya hay otra puja abierta para esta toma."}
        )
    now = timezone.now()
    if auction.closes_at <= now:
        raise serializers.ValidationError({"closes_at": "La fecha de cierre debe ser futura."})
    validate_auction_period(
        auction.ad_space,
        auction.start_date,
        auction.end_date,
        exclude_auction_id=auction.pk,
    )
    auction.status = AuctionStatus.OPEN
    if auction.opens_at > now:
        auction.opens_at = now
    auction.save(update_fields=["status", "opens_at", "updated_at"])
    return auction


@transaction.atomic
def close_auction(auction: SpaceAuction) -> SpaceAuction:
    if auction.status != AuctionStatus.OPEN:
        raise serializers.ValidationError({"detail": "Solo se pueden cerrar pujas abiertas."})
    auction.status = AuctionStatus.CLOSED
    auction.save(update_fields=["status", "updated_at"])
    return auction


@transaction.atomic
def cancel_auction(auction: SpaceAuction) -> SpaceAuction:
    if auction.status in (AuctionStatus.AWARDED, AuctionStatus.CANCELLED):
        raise serializers.ValidationError({"detail": "Esta puja ya no se puede cancelar."})
    auction.status = AuctionStatus.CANCELLED
    auction.save(update_fields=["status", "updated_at"])
    return auction


@transaction.atomic
def place_bid(
    auction: SpaceAuction,
    *,
    client: Client,
    amount_usd: Decimal,
) -> SpaceBid:
    ws = auction.ad_space.shopping_center.workspace
    _ensure_bidding_workspace(ws)
    if auction.status != AuctionStatus.OPEN:
        raise serializers.ValidationError({"detail": "Esta puja no está abierta."})
    now = timezone.now()
    if now < auction.opens_at or now >= auction.closes_at:
        raise serializers.ValidationError({"detail": "Fuera del horario de recepción de ofertas."})
    min_next = minimum_next_bid_amount(auction)
    if amount_usd < min_next:
        raise serializers.ValidationError(
            {
                "amount_usd": f"La oferta debe ser al menos {min_next} USD.",
            }
        )
    if client.workspace_id != ws.id:
        raise serializers.ValidationError({"detail": "No puedes ofertar en este marketplace."})
    return SpaceBid.objects.create(auction=auction, client=client, amount_usd=amount_usd)


@transaction.atomic
def award_auction(
    auction: SpaceAuction,
    bid_id: int,
    *,
    actor: AbstractBaseUser | None = None,
) -> SpaceAuction:
    if auction.status not in (AuctionStatus.OPEN, AuctionStatus.CLOSED):
        raise serializers.ValidationError(
            {"detail": "Solo se pueden adjudicar pujas abiertas o cerradas."}
        )
    try:
        bid = auction.bids.select_related("client").get(pk=bid_id, is_active=True)
    except SpaceBid.DoesNotExist:
        raise serializers.ValidationError({"detail": "Oferta no encontrada."}) from None

    if order_item_conflicts(
        auction.ad_space_id,
        auction.start_date,
        auction.end_date,
    ):
        raise serializers.ValidationError(
            {"detail": "El período ya no está libre; no se puede adjudicar."}
        )

    order = Order.objects.create(client=bid.client, status=OrderStatus.DRAFT)
    monthly = auction.ad_space.monthly_price_usd
    OrderItem.objects.create(
        order=order,
        ad_space=auction.ad_space,
        start_date=auction.start_date,
        end_date=auction.end_date,
        monthly_price=monthly,
        subtotal=bid.amount_usd.quantize(Decimal("0.01")),
    )
    submit_draft_order(order, actor=actor)

    auction.status = AuctionStatus.AWARDED
    auction.winning_bid = bid
    auction.order = order
    auction.save(update_fields=["status", "winning_bid", "order", "updated_at"])
    return auction


def close_expired_open_auctions() -> int:
    now = timezone.now()
    qs = SpaceAuction.objects.filter(status=AuctionStatus.OPEN, closes_at__lte=now)
    return qs.update(status=AuctionStatus.CLOSED, updated_at=now)
