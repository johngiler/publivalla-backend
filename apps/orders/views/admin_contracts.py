"""Listado de contratos (líneas de pedido activas/vencidas) para el panel del administrador marketplace."""

from __future__ import annotations

import re
from datetime import timedelta
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ad_spaces.utils.covers import ad_space_effective_cover_url
from apps.ad_spaces.models import AdSpaceImage
from apps.common.utils.pagination import StandardPagination
from apps.orders.models import OrderItem, OrderStatus
from apps.users.permissions import IsAdminRole
from apps.workspaces.tenant import get_workspace_for_request


def _contract_row_kind(*, order_status: str, start_date, end_date, today) -> str:
    if order_status == OrderStatus.EXPIRED or end_date < today:
        return "ended"
    if start_date > today:
        return "upcoming"
    return "running"


def _build_contracts_search_q(search: str) -> Q:
    raw = search.strip()
    # Código de toma en BD suele ir sin espacios (p. ej. SLC-T5A); el usuario puede escribir «SLC - T5A».
    code_compact = re.sub(r"\s+", "", raw)
    q = (
        Q(order__client__company_name__icontains=raw)
        | Q(order__code__icontains=raw)
        | Q(ad_space__title__icontains=raw)
        | Q(ad_space__code__icontains=raw)
    )
    if code_compact and code_compact != raw:
        q |= Q(ad_space__code__icontains=code_compact)
    norm = re.sub(r"\s+", "", raw).upper()
    if norm.isdigit():
        try:
            q |= Q(order_id=int(norm))
        except (ValueError, OverflowError):
            pass
    m = re.search(r"-ORDER-(\d+)$", norm)
    if m:
        try:
            q |= Q(order_id=int(m.group(1)))
        except (ValueError, OverflowError):
            pass
    return q


class AdminMarketplaceContractsView(APIView):
    """
    Líneas de contrato de todos los clientes del workspace (pedidos activos o vencidos).

    Query:
      - search: texto (cliente, pedido, código o título de toma).
      - order_status: active | expired | all
      - phase: running | upcoming | ended | all (periodo vs hoy; pedido vencido cuenta como finalizado)
      - ending_within: 7 | 30 | 90 | all — solo líneas en curso cuyo fin cae dentro de N días (incluye hoy).
      - ordering: -end_date | end_date | -start_date | start_date | client
      - client_id: id numérico de empresa (opcional)
      - ad_space_id: id numérico de toma (opcional)
    """

    permission_classes = [IsAdminRole]

    def get(self, request):
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response(
                {"detail": "No se pudo determinar el workspace.", "results": [], "count": 0},
                status=status.HTTP_400_BAD_REQUEST,
            )

        today = timezone.localdate()
        qs = (
            OrderItem.objects.filter(
                order__client__workspace=ws,
                order__status__in=(OrderStatus.ACTIVE, OrderStatus.EXPIRED),
            )
            .select_related("order", "order__client", "ad_space__shopping_center")
            .prefetch_related(
                Prefetch(
                    "ad_space__gallery_images",
                    queryset=AdSpaceImage.objects.order_by("sort_order", "id"),
                ),
            )
        )

        st = (request.query_params.get("order_status") or "all").strip().lower()
        if st == "active":
            qs = qs.filter(order__status=OrderStatus.ACTIVE)
        elif st == "expired":
            qs = qs.filter(order__status=OrderStatus.EXPIRED)

        phase = (request.query_params.get("phase") or "all").strip().lower()
        if phase == "ended":
            qs = qs.filter(Q(order__status=OrderStatus.EXPIRED) | Q(end_date__lt=today))
        elif phase == "upcoming":
            qs = qs.filter(
                Q(order__status=OrderStatus.ACTIVE),
                Q(start_date__gt=today),
            )
        elif phase == "running":
            qs = qs.filter(
                Q(order__status=OrderStatus.ACTIVE),
                Q(start_date__lte=today),
                Q(end_date__gte=today),
            )

        ending = (request.query_params.get("ending_within") or "all").strip().lower()
        if ending in ("7", "30", "90"):
            n = int(ending)
            horizon = today + timedelta(days=n)
            qs = qs.filter(
                Q(order__status=OrderStatus.ACTIVE),
                Q(start_date__lte=today),
                Q(end_date__gte=today),
                Q(end_date__lte=horizon),
            )

        cid = request.query_params.get("client_id", "").strip()
        if cid.isdigit():
            qs = qs.filter(order__client_id=int(cid))

        aid = request.query_params.get("ad_space_id", "").strip()
        if aid.isdigit():
            qs = qs.filter(ad_space_id=int(aid))

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(_build_contracts_search_q(search))

        ordering = (request.query_params.get("ordering") or "-end_date").strip()
        allowed = {
            "-end_date": ("-end_date", "-id"),
            "end_date": ("end_date", "id"),
            "-start_date": ("-start_date", "-id"),
            "start_date": ("start_date", "id"),
            "client": ("order__client__company_name", "end_date", "id"),
        }
        qs = qs.order_by(*allowed.get(ordering, ("-end_date", "-id")))

        summary_qs = OrderItem.objects.filter(
            order__client__workspace=ws,
            order__status__in=(OrderStatus.ACTIVE, OrderStatus.EXPIRED),
        )
        soon = today + timedelta(days=30)
        summary = {
            "lines_total": summary_qs.count(),
            "running": summary_qs.filter(
                Q(order__status=OrderStatus.ACTIVE),
                Q(start_date__lte=today),
                Q(end_date__gte=today),
            ).count(),
            "upcoming": summary_qs.filter(
                Q(order__status=OrderStatus.ACTIVE),
                Q(start_date__gt=today),
            ).count(),
            "ended": summary_qs.filter(
                Q(order__status=OrderStatus.EXPIRED) | Q(end_date__lt=today),
            ).count(),
            "ending_within_30_days": summary_qs.filter(
                Q(order__status=OrderStatus.ACTIVE),
                Q(start_date__lte=today),
                Q(end_date__gte=today),
                Q(end_date__lte=soon),
            ).count(),
            "active_orders": summary_qs.filter(order__status=OrderStatus.ACTIVE)
            .values("order_id")
            .distinct()
            .count(),
        }

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is None:
            page = list(qs[: paginator.page_size])

        results = []
        for it in page:
            ad = it.ad_space
            sc = ad.shopping_center
            client = it.order.client
            kind = _contract_row_kind(
                order_status=it.order.status,
                start_date=it.start_date,
                end_date=it.end_date,
                today=today,
            )
            gallery_urls = []
            for row in ad.gallery_images.all():
                if row.image:
                    gallery_urls.append(row.image.url)
            cover = ad_space_effective_cover_url(ad)

            total_days = max(0, (it.end_date - it.start_date).days + 1)
            days_remaining = None
            days_until_start = None
            elapsed_ratio = None
            if kind == "running":
                elapsed = (today - it.start_date).days
                span = max(1, (it.end_date - it.start_date).days)
                elapsed_ratio = max(0.0, min(1.0, elapsed / span))
                days_remaining = max(0, (it.end_date - today).days)
            elif kind == "upcoming":
                days_until_start = max(0, (it.start_date - today).days)
                elapsed_ratio = 0.0
            else:
                elapsed_ratio = 1.0
                days_remaining = 0

            results.append(
                {
                    "id": it.id,
                    "order_id": it.order_id,
                    "order_code": it.order.code or "",
                    "order_status": it.order.status,
                    "order_status_label": it.order.get_status_display(),
                    "contract_row_kind": kind,
                    "client_id": client.id,
                    "client_company_name": (client.company_name or "").strip(),
                    "ad_space_id": ad.id,
                    "ad_space_code": ad.code,
                    "ad_space_title": ad.title,
                    "ad_space_cover_image": cover,
                    "ad_space_gallery_images": gallery_urls,
                    "shopping_center_name": sc.name if sc else "",
                    "shopping_center_slug": sc.slug if sc else "",
                    "shopping_center_city": sc.city if sc else "",
                    "start_date": it.start_date.isoformat(),
                    "end_date": it.end_date.isoformat(),
                    "monthly_price": str(it.monthly_price),
                    "subtotal": str(it.subtotal),
                    "period_days_total": total_days,
                    "period_elapsed_ratio": elapsed_ratio,
                    "days_remaining": days_remaining,
                    "days_until_start": days_until_start,
                }
            )

        paginated = paginator.get_paginated_response(results)
        data = dict(paginated.data)
        data["summary"] = summary
        return Response(data)
