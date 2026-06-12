"""Vistas autenticadas solo para rol cliente marketplace: contratos y favoritos."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Prefetch, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ad_spaces.utils.covers import ad_space_effective_cover_url
from apps.ad_spaces.models import AdSpace, AdSpaceImage
from apps.ad_spaces.serializers import AdSpaceSerializer
from apps.common.utils.catalog_access import shopping_center_allows_public_catalog
from apps.clients.models import ClientAdSpaceFavorite
from apps.orders.models import OrderItem, OrderStatus
from apps.orders.services.payment_plan_services import (
    filter_order_items_with_incomplete_payment_plan,
    order_uses_split_payment,
    payment_plan_pending_param_active,
)
from apps.users.utils import get_marketplace_client, user_is_admin


def _contract_row_kind(*, order_status: str, start_date, end_date, today) -> str:
    if order_status == OrderStatus.EXPIRED or end_date < today:
        return "ended"
    if start_date > today:
        return "upcoming"
    return "running"


class MyContractsView(APIView):
    """
    Líneas de pedido en órdenes activas o vencidas (contrato operativo tras el flujo hasta activa).
    Query:
      - phase=running|upcoming|ended|open|all (``open`` = en curso + próximos, sin finalizados)
      - payment_plan_pending=pending — solo líneas cuyo pedido tiene cuotas sin pagar
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta sección es solo para cuentas de empresa en el marketplace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No tienes una empresa asociada."},
                status=status.HTTP_403_FORBIDDEN,
            )

        today = timezone.localdate()
        phase = (request.query_params.get("phase") or "all").strip().lower()
        phase_kinds: frozenset[str] | None = None
        if phase == "open":
            phase_kinds = frozenset(("running", "upcoming"))
        elif phase not in ("running", "upcoming", "ended", "all"):
            phase = "all"

        qs = (
            OrderItem.objects.filter(
                order__client=client,
                order__status__in=(OrderStatus.ACTIVE, OrderStatus.EXPIRED),
            )
            .select_related("order", "order__payment_plan", "ad_space__shopping_center")
            .prefetch_related(
                Prefetch(
                    "ad_space__gallery_images",
                    queryset=AdSpaceImage.objects.order_by("sort_order", "id"),
                ),
            )
            .order_by("-end_date", "-start_date", "-id")
        )

        if payment_plan_pending_param_active(
            request.query_params.get("payment_plan_pending", "")
        ):
            qs = filter_order_items_with_incomplete_payment_plan(qs)

        total_invested = qs.aggregate(s=Sum("subtotal"))["s"] or Decimal("0")

        items_out = []
        running_n = upcoming_n = ended_n = 0
        for it in qs:
            kind = _contract_row_kind(
                order_status=it.order.status,
                start_date=it.start_date,
                end_date=it.end_date,
                today=today,
            )
            if kind == "running":
                running_n += 1
            elif kind == "upcoming":
                upcoming_n += 1
            else:
                ended_n += 1
            if phase_kinds is not None:
                if kind not in phase_kinds:
                    continue
            elif phase != "all" and kind != phase:
                continue

            ad = it.ad_space
            sc = ad.shopping_center
            # Misma forma que `OrderItemSerializer`: galería como lista de `.url` y portada efectiva
            # (primera galería o `cover_image`), sin mezclar `build_absolute_uri` solo en contratos.
            gallery_urls = []
            for row in ad.gallery_images.all():
                if row.image:
                    gallery_urls.append(row.image.url)
            cover = ad_space_effective_cover_url(ad)
            items_out.append(
                {
                    "id": it.id,
                    "order_id": it.order_id,
                    "order_code": it.order.code or "",
                    "order_status": it.order.status,
                    "order_status_label": it.order.get_status_display(),
                    "split_payment_enabled": order_uses_split_payment(it.order),
                    "contract_row_kind": kind,
                    "ad_space_id": ad.id,
                    "ad_space_code": ad.code,
                    "ad_space_title": ad.name,
                    "ad_space_cover_image": cover,
                    "ad_space_gallery_images": gallery_urls,
                    "shopping_center_name": sc.name if sc else "",
                    "shopping_center_slug": sc.slug if sc else "",
                    "shopping_center_city": sc.city if sc else "",
                    "start_date": it.start_date.isoformat(),
                    "end_date": it.end_date.isoformat(),
                    "monthly_price": str(it.monthly_price),
                    "subtotal": str(it.subtotal),
                }
            )

        soon = today + timedelta(days=30)
        ending_soon_count = sum(
            1
            for it in qs
            if it.order.status == OrderStatus.ACTIVE
            and it.start_date <= today
            and today <= it.end_date <= soon
        )

        return Response(
            {
                "summary": {
                    "total_invested_subtotal": str(total_invested),
                    "line_counts": {
                        "running": running_n,
                        "upcoming": upcoming_n,
                        "ended": ended_n,
                        "total": running_n + upcoming_n + ended_n,
                    },
                    "ending_within_30_days": ending_soon_count,
                },
                "items": items_out,
                "phase_filter": phase,
            }
        )


class MyFavoritesView(APIView):
    """Lista favoritos del cliente con disponibilidad año actual y siguiente."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta sección es solo para cuentas de empresa en el marketplace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No tienes una empresa asociada."},
                status=status.HTTP_403_FORBIDDEN,
            )

        favs = (
            ClientAdSpaceFavorite.objects.filter(client=client)
            .select_related("ad_space__shopping_center")
            .prefetch_related(
                Prefetch(
                    "ad_space__gallery_images",
                    queryset=AdSpaceImage.objects.order_by("sort_order", "id"),
                ),
            )
            .order_by("-created_at", "-id")
        )

        fav_list = list(favs)
        ctx = {"request": request, "marketplace_client": client}
        ids = [fav.ad_space_id for fav in fav_list]
        if ids:
            from apps.ad_spaces.utils.availability_calendar import (
                client_months_highlight_by_year_bulk,
            )

            ctx["client_months_bulk"] = client_months_highlight_by_year_bulk(
                ids, client.pk
            )
        results = []
        favorite_space_ids = []
        for fav in fav_list:
            ad = fav.ad_space
            favorite_space_ids.append(ad.id)
            ser = AdSpaceSerializer(ad, context=ctx)
            row = dict(ser.data)
            results.append(
                {
                    "id": fav.id,
                    "created_at": fav.created_at.isoformat() if fav.created_at else None,
                    "ad_space": row,
                }
            )

        return Response({"results": results, "favorite_space_ids": favorite_space_ids})

    def post(self, request):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta sección es solo para cuentas de empresa en el marketplace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No tienes una empresa asociada."},
                status=status.HTTP_403_FORBIDDEN,
            )

        raw_id = request.data.get("ad_space")
        try:
            ad_space_id = int(raw_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Indica un ad_space numérico válido.", "code": "invalid_ad_space"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ad = AdSpace.objects.select_related("shopping_center").get(pk=ad_space_id)
        except AdSpace.DoesNotExist:
            return Response(
                {"detail": "La toma no existe.", "code": "ad_space_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if ad.shopping_center.workspace_id != client.workspace_id:
            return Response(
                {"detail": "Esta toma no pertenece a tu marketplace.", "code": "wrong_workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not shopping_center_allows_public_catalog(ad.shopping_center):
            return Response(
                {"detail": "Esta toma no está disponible en el catálogo público.", "code": "not_public"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fav, created = ClientAdSpaceFavorite.objects.get_or_create(client=client, ad_space=ad)
        ctx = {"request": request}
        ser = AdSpaceSerializer(ad, context=ctx)
        row = dict(ser.data)
        payload = {
            "id": fav.id,
            "created_at": fav.created_at.isoformat() if fav.created_at else None,
            "ad_space": row,
        }
        return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MyFavoriteDetailView(APIView):
    """Quitar favorito por id de toma."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, ad_space_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta sección es solo para cuentas de empresa en el marketplace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "No tienes una empresa asociada."},
                status=status.HTTP_403_FORBIDDEN,
            )

        n, _ = ClientAdSpaceFavorite.objects.filter(
            client=client, ad_space_id=ad_space_id
        ).delete()
        if n == 0:
            return Response(
                {"detail": "No estaba en favoritos.", "code": "not_favorite"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
