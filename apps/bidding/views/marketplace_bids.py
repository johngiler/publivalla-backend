"""Ofertas de clientes marketplace sobre pujas abiertas."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bidding.models import SpaceAuction
from apps.bidding.serializers import PlaceBidSerializer, SpaceBidAdminSerializer
from apps.bidding.services.auction_services import place_bid
from apps.bidding.utils.queries import workspace_bidding_enabled
from apps.users.utils import get_marketplace_client, user_is_admin
from apps.workspaces.tenant import get_workspace_for_request


class PlaceAuctionBidView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, auction_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Las ofertas son solo para clientes del marketplace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No tienes una empresa cliente asociada."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ws = get_workspace_for_request(request)
        if ws is None or not workspace_bidding_enabled(ws):
            return Response(
                {"detail": "Las pujas no están disponibles en este sitio."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            auction = SpaceAuction.objects.select_related(
                "ad_space__shopping_center__workspace"
            ).get(pk=auction_id, ad_space__shopping_center__workspace=ws)
        except SpaceAuction.DoesNotExist:
            return Response({"detail": "Puja no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        ser = PlaceBidSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        bid = place_bid(auction, client=client, amount_usd=ser.validated_data["amount_usd"])
        return Response(
            SpaceBidAdminSerializer(bid).data,
            status=status.HTTP_201_CREATED,
        )
