"""CRUD admin de pujas por toma."""

from __future__ import annotations

from django.db.models import Count, Prefetch, Q

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.bidding.models import SpaceAuction, SpaceBid
from apps.bidding.serializers import (
    AwardAuctionSerializer,
    SpaceAuctionAdminSerializer,
    SpaceAuctionAdminWriteSerializer,
)
from apps.bidding.services.auction_services import (
    award_auction,
    cancel_auction,
    close_auction,
    open_auction,
)
from apps.bidding.utils.queries import workspace_bidding_enabled
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.workspaces.tenant import get_workspace_for_request


class SpaceAuctionAdminViewSet(AdminModelViewSet):
    def get_serializer_class(self):
        if self.action in ("list", "retrieve", "open", "close", "cancel", "award"):
            return SpaceAuctionAdminSerializer
        return SpaceAuctionAdminWriteSerializer

    def get_queryset(self):
        qs = (
            SpaceAuction.objects.select_related(
                "ad_space",
                "ad_space__shopping_center",
                "winning_bid",
                "order",
            )
            .prefetch_related(
                Prefetch(
                    "bids",
                    queryset=SpaceBid.objects.select_related("client").order_by(
                        "-amount_usd", "-created_at"
                    ),
                )
            )
            .annotate(_bid_count=Count("bids", filter=Q(bids__is_active=True)))
            .order_by("-closes_at", "-id")
        )
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(ad_space__shopping_center__workspace=ws)

        if self.action == "list":
            cid = self.request.query_params.get("shopping_center", "").strip()
            if cid.isdigit():
                qs = qs.filter(ad_space__shopping_center_id=int(cid))
            aid = self.request.query_params.get("ad_space", "").strip()
            if aid.isdigit():
                qs = qs.filter(ad_space_id=int(aid))
            st = self.request.query_params.get("status", "").strip()
            if st and st != "all":
                qs = qs.filter(status=st)
            active = self.request.query_params.get("active", "").strip()
            if active == "1":
                qs = qs.filter(is_active=True)
            elif active == "0":
                qs = qs.filter(is_active=False)
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(ad_space__code__icontains=search)
                    | Q(ad_space__title__icontains=search)
                    | Q(note__icontains=search)
                    | Q(ad_space__shopping_center__name__icontains=search)
                )
        return qs

    def create(self, request, *args, **kwargs):
        ws = get_workspace_for_request(request)
        if ws is not None and not workspace_bidding_enabled(ws):
            return Response(
                {"detail": "Las pujas no están habilitadas en este workspace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def open(self, request, pk=None):
        auction = self.get_object()
        open_auction(auction, actor=request.user)
        return Response(SpaceAuctionAdminSerializer(auction, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        auction = self.get_object()
        close_auction(auction)
        return Response(SpaceAuctionAdminSerializer(auction, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        auction = self.get_object()
        cancel_auction(auction)
        return Response(SpaceAuctionAdminSerializer(auction, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def award(self, request, pk=None):
        auction = self.get_object()
        ser = AwardAuctionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        award_auction(auction, ser.validated_data["bid_id"], actor=request.user)
        auction = self.get_queryset().get(pk=auction.pk)
        return Response(SpaceAuctionAdminSerializer(auction, context=self.get_serializer_context()).data)
