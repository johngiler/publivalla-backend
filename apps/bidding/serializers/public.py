from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.bidding.models import SpaceAuction
from apps.bidding.utils.queries import auction_high_bid_amount, minimum_next_bid_amount


class CatalogActiveAuctionSerializer(serializers.ModelSerializer):
    high_bid_usd = serializers.SerializerMethodField()
    minimum_next_bid_usd = serializers.SerializerMethodField()
    bid_count = serializers.SerializerMethodField()

    class Meta:
        model = SpaceAuction
        fields = (
            "id",
            "start_date",
            "end_date",
            "opens_at",
            "closes_at",
            "minimum_bid_usd",
            "high_bid_usd",
            "minimum_next_bid_usd",
            "bid_count",
        )

    def get_high_bid_usd(self, obj):
        return auction_high_bid_amount(obj)

    def get_minimum_next_bid_usd(self, obj):
        return minimum_next_bid_amount(obj)

    def get_bid_count(self, obj):
        if hasattr(obj, "_bid_count"):
            return obj._bid_count
        return obj.bids.filter(is_active=True).count()


class PlaceBidSerializer(serializers.Serializer):
    amount_usd = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
