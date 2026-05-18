from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.ad_spaces.models import AdSpace
from apps.bidding.models import AuctionStatus, SpaceAuction, SpaceBid
from apps.bidding.services.auction_services import validate_auction_period
from apps.bidding.utils.queries import (
    auction_high_bid_amount,
    minimum_next_bid_amount,
    workspace_bidding_enabled,
)
from apps.workspaces.tenant import get_workspace_for_request


def _status_label(value: str) -> str:
    try:
        return AuctionStatus(value).label
    except ValueError:
        return value or ""


class SpaceBidAdminSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.company_name", read_only=True)
    client_email = serializers.EmailField(source="client.email", read_only=True)

    class Meta:
        model = SpaceBid
        fields = (
            "id",
            "client",
            "client_name",
            "client_email",
            "amount_usd",
            "is_active",
            "created_at",
        )
        read_only_fields = fields


class SpaceAuctionAdminSerializer(serializers.ModelSerializer):
    ad_space_code = serializers.CharField(source="ad_space.code", read_only=True)
    ad_space_title = serializers.CharField(source="ad_space.title", read_only=True)
    shopping_center_id = serializers.IntegerField(
        source="ad_space.shopping_center_id", read_only=True
    )
    shopping_center_name = serializers.CharField(
        source="ad_space.shopping_center.name", read_only=True
    )
    status_label = serializers.SerializerMethodField()
    high_bid_usd = serializers.SerializerMethodField()
    minimum_next_bid_usd = serializers.SerializerMethodField()
    bid_count = serializers.SerializerMethodField()
    bids = SpaceBidAdminSerializer(many=True, read_only=True)
    winning_bid_id = serializers.IntegerField(source="winning_bid_id", read_only=True)
    order_id = serializers.IntegerField(source="order_id", read_only=True)

    class Meta:
        model = SpaceAuction
        fields = (
            "id",
            "ad_space",
            "ad_space_code",
            "ad_space_title",
            "shopping_center_id",
            "shopping_center_name",
            "start_date",
            "end_date",
            "opens_at",
            "closes_at",
            "status",
            "status_label",
            "minimum_bid_usd",
            "high_bid_usd",
            "minimum_next_bid_usd",
            "bid_count",
            "bids",
            "winning_bid_id",
            "order_id",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "ad_space_code",
            "ad_space_title",
            "shopping_center_id",
            "shopping_center_name",
            "status_label",
            "high_bid_usd",
            "minimum_next_bid_usd",
            "bid_count",
            "bids",
            "winning_bid_id",
            "order_id",
            "created_at",
            "updated_at",
        )

    def get_status_label(self, obj):
        return _status_label(obj.status)

    def get_high_bid_usd(self, obj):
        return auction_high_bid_amount(obj)

    def get_minimum_next_bid_usd(self, obj):
        return minimum_next_bid_amount(obj)

    def get_bid_count(self, obj):
        if hasattr(obj, "_bid_count"):
            return obj._bid_count
        return obj.bids.filter(is_active=True).count()


class SpaceAuctionAdminWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpaceAuction
        fields = (
            "id",
            "ad_space",
            "start_date",
            "end_date",
            "opens_at",
            "closes_at",
            "minimum_bid_usd",
            "note",
            "is_active",
        )
        read_only_fields = ("id",)

    def validate_ad_space(self, ad_space: AdSpace):
        request = self.context.get("request")
        if request is None:
            return ad_space
        ws = get_workspace_for_request(request)
        if ws is not None and ad_space.shopping_center.workspace_id != ws.id:
            raise serializers.ValidationError("Esta toma no pertenece a tu marketplace.")
        if ws is not None and not workspace_bidding_enabled(ws):
            raise serializers.ValidationError("Las pujas no están habilitadas en este workspace.")
        return ad_space

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        opens = attrs.get("opens_at", getattr(self.instance, "opens_at", None))
        closes = attrs.get("closes_at", getattr(self.instance, "closes_at", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "La fecha de fin no puede ser anterior a la de inicio."}
            )
        if opens and closes and closes <= opens:
            raise serializers.ValidationError(
                {"closes_at": "El cierre debe ser posterior a la apertura."}
            )
        min_bid = attrs.get(
            "minimum_bid_usd",
            getattr(self.instance, "minimum_bid_usd", None),
        )
        if min_bid is not None and min_bid <= Decimal("0"):
            raise serializers.ValidationError(
                {"minimum_bid_usd": "La oferta mínima debe ser mayor que cero."}
            )
        ad_space = attrs.get("ad_space") or getattr(self.instance, "ad_space", None)
        if ad_space and start and end:
            validate_auction_period(
                ad_space,
                start,
                end,
                exclude_auction_id=getattr(self.instance, "pk", None),
            )
        return attrs

    def create(self, validated_data):
        validated_data.setdefault("status", AuctionStatus.DRAFT)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if instance.status != AuctionStatus.DRAFT:
            locked = {"ad_space", "start_date", "end_date", "opens_at", "closes_at", "minimum_bid_usd"}
            for key in list(validated_data.keys()):
                if key in locked:
                    raise serializers.ValidationError(
                        {"detail": "Solo se pueden editar nota y estado activo fuera de borrador."}
                    )
        return super().update(instance, validated_data)


class AwardAuctionSerializer(serializers.Serializer):
    bid_id = serializers.IntegerField(min_value=1)
