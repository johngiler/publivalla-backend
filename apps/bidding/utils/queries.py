from __future__ import annotations

from decimal import Decimal

from django.db.models import Max
from django.utils import timezone

from apps.bidding.models import AuctionStatus, SpaceAuction, SpaceBid


def workspace_bidding_enabled(workspace) -> bool:
    return bool(workspace and getattr(workspace, "marketplace_bidding_enabled", False))


def get_open_auction_for_space(ad_space_id: int) -> SpaceAuction | None:
    now = timezone.now()
    return (
        SpaceAuction.objects.filter(
            ad_space_id=ad_space_id,
            status=AuctionStatus.OPEN,
            is_active=True,
            opens_at__lte=now,
            closes_at__gt=now,
        )
        .select_related("ad_space", "ad_space__shopping_center")
        .first()
    )


def ad_space_has_open_auction(ad_space_id: int) -> bool:
    return get_open_auction_for_space(ad_space_id) is not None


def auction_high_bid_amount(auction: SpaceAuction) -> Decimal | None:
    agg = auction.bids.filter(is_active=True).aggregate(m=Max("amount_usd"))
    val = agg.get("m")
    return val if val is not None else None


def minimum_next_bid_amount(auction: SpaceAuction) -> Decimal:
    high = auction_high_bid_amount(auction)
    if high is None:
        return auction.minimum_bid_usd
    return (high + Decimal("1.00")).quantize(Decimal("0.01"))


def other_open_auction_exists(ad_space_id: int, *, exclude_auction_id: int | None = None) -> bool:
    qs = SpaceAuction.objects.filter(
        ad_space_id=ad_space_id,
        status=AuctionStatus.OPEN,
        is_active=True,
    )
    if exclude_auction_id is not None:
        qs = qs.exclude(pk=exclude_auction_id)
    return qs.exists()
