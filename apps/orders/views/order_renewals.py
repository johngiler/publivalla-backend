"""API de renovación de contratos (cliente y admin)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import OrderItem, OrderRenewal, OrderRenewalStatus, OrderStatus
from apps.orders.services.order_renewal_services import (
    approve_and_apply_renewal,
    confirm_renewal_payment,
    count_consecutive_free_renewal_months,
    create_renewal_request,
    first_renewal_month_after,
    latest_open_renewal,
    reject_renewal,
    renewal_payload,
)
from apps.users.permissions import IsAdminRole
from apps.users.utils import get_marketplace_client, user_is_admin


def _parse_months(raw) -> list[tuple[int, int]]:
    if not isinstance(raw, list):
        return []
    out: list[tuple[int, int]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            y = int(row["year"])
            m = int(row["month"])
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= m <= 12:
            out.append((y, m))
    return out


class MyContractRenewalView(APIView):
    """Cliente: crear solicitud o consultar renovación abierta de una línea."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request, item_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "No disponible para esta cuenta."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No hay empresa asociada."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        item = (
            OrderItem.objects.filter(
                pk=item_id,
                order__client=client,
                order__status=OrderStatus.ACTIVE,
            )
            .select_related("order")
            .first()
        )
        if item is None:
            return Response({"detail": "Contrato no encontrado."}, status=404)
        open_r = latest_open_renewal(item.pk)
        recent = (
            OrderRenewal.objects.filter(order_item=item)
            .prefetch_related("months")
            .order_by("-created_at")[:5]
        )
        ny, nm = first_renewal_month_after(item.end_date)
        max_free = count_consecutive_free_renewal_months(
            item.ad_space_id, start_after=item.end_date
        )
        return Response(
            {
                "order_item_id": item.id,
                "end_date": item.end_date.isoformat(),
                "next_month": {"year": ny, "month": nm},
                "max_free_months": max_free,
                "open_renewal": renewal_payload(open_r) if open_r else None,
                "recent": [renewal_payload(r) for r in recent],
            }
        )

    def post(self, request, item_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "No disponible para esta cuenta."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No hay empresa asociada."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        item = (
            OrderItem.objects.filter(
                pk=item_id,
                order__client=client,
                order__status=OrderStatus.ACTIVE,
            )
            .select_related("order", "ad_space__shopping_center")
            .first()
        )
        if item is None:
            return Response({"detail": "Contrato no encontrado."}, status=404)
        months = _parse_months(request.data.get("months"))
        renewal = create_renewal_request(
            item,
            months=months,
            actor=request.user,
            client_note=str(request.data.get("client_note") or ""),
        )
        return Response(renewal_payload(renewal), status=status.HTTP_201_CREATED)


class MyContractRenewalDocumentsView(APIView):
    """Cliente: subir comprobante o permiso de una renovación propia."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, renewal_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "No disponible para esta cuenta."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No hay empresa asociada."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        renewal = (
            OrderRenewal.objects.filter(
                pk=renewal_id,
                order_item__order__client=client,
            )
            .prefetch_related("months")
            .select_related("order_item__order")
            .first()
        )
        if renewal is None:
            return Response({"detail": "Renovación no encontrada."}, status=404)
        if renewal.status not in (
            OrderRenewalStatus.PENDING,
            OrderRenewalStatus.COMPLETED,
        ):
            return Response(
                {"detail": "No puedes adjuntar archivos a esta renovación."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        updated = False
        receipt = request.FILES.get("payment_receipt")
        permit = request.FILES.get("permit_file")
        if receipt is not None:
            if renewal.payment_receipt:
                renewal.payment_receipt.delete(save=False)
            renewal.payment_receipt = receipt
            updated = True
        if permit is not None:
            if renewal.permit_file:
                renewal.permit_file.delete(save=False)
            renewal.permit_file = permit
            updated = True
        if not updated:
            return Response(
                {"detail": "Adjunta el comprobante o el permiso."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fields = ["updated_at"]
        if receipt is not None:
            fields.append("payment_receipt")
        if permit is not None:
            fields.append("permit_file")
        renewal.save(update_fields=fields)
        renewal = (
            OrderRenewal.objects.filter(pk=renewal.pk)
            .prefetch_related("months")
            .select_related("order_item__order")
            .get()
        )
        return Response(renewal_payload(renewal))


class AdminContractRenewalActionView(APIView):
    """Admin: aprobar (aplica extensión), rechazar o confirmar pago."""

    permission_classes = [IsAuthenticated, IsAdminRole]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, renewal_id: int):
        action = (request.data.get("action") or "").strip().lower()
        renewal = (
            OrderRenewal.objects.filter(pk=renewal_id)
            .select_related("order_item__order__client__workspace")
            .prefetch_related("months")
            .first()
        )
        if renewal is None:
            return Response({"detail": "Renovación no encontrada."}, status=404)

        note = str(request.data.get("admin_note") or "")
        if action == "approve":
            renewal = approve_and_apply_renewal(
                renewal, actor=request.user, admin_note=note
            )
        elif action == "reject":
            renewal = reject_renewal(renewal, actor=request.user, admin_note=note)
        elif action == "confirm_payment":
            renewal = confirm_renewal_payment(renewal, actor=request.user)
        else:
            return Response(
                {"detail": "Acción no válida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        renewal = (
            OrderRenewal.objects.filter(pk=renewal.pk)
            .prefetch_related("months")
            .select_related("order_item__order")
            .get()
        )
        return Response(renewal_payload(renewal))
