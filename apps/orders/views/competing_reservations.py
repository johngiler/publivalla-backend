"""API admin: listar disputas de solicitudes enviadas y adjudicar ganador."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.utils.competing_reservations import (
    award_competing_submission,
    count_competing_submission_groups,
    list_competing_submission_groups,
)
from apps.users.utils import user_is_admin
from apps.workspaces.tenant import get_workspace_for_request


class AdminCompetingReservationsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_is_admin(request.user):
            return Response({"detail": "No autorizado."}, status=status.HTTP_403_FORBIDDEN)
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response({"detail": "Workspace no encontrado."}, status=status.HTTP_400_BAD_REQUEST)
        groups = list_competing_submission_groups(ws)
        return Response({"groups": groups, "count": len(groups)})


class AdminCompetingReservationsCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_is_admin(request.user):
            return Response({"detail": "No autorizado."}, status=status.HTTP_403_FORBIDDEN)
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response({"detail": "Workspace no encontrado."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"count": count_competing_submission_groups(ws)})


class AdminCompetingReservationAwardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ad_space_id: int):
        if not user_is_admin(request.user):
            return Response({"detail": "No autorizado."}, status=status.HTTP_403_FORBIDDEN)
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response({"detail": "Workspace no encontrado."}, status=status.HTTP_400_BAD_REQUEST)
        winner_order_id = request.data.get("winner_order_id")
        if winner_order_id is None:
            return Response(
                {"detail": "Indica winner_order_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            winner_order_id = int(winner_order_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "winner_order_id no válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = award_competing_submission(
                workspace=ws,
                ad_space_id=int(ad_space_id),
                winner_order_id=winner_order_id,
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)
