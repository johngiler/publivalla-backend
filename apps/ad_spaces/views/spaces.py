from django.db.models import Count, Prefetch, Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.ad_spaces.models import AdSpace, AdSpaceFormat
from apps.ad_spaces.serializers import (
    AdSpaceSerializer,
    CatalogMountingProviderSerializer,
    MOUNTING_PROVIDERS_PAGE_SIZE,
)
from apps.providers.models import MountingProvider
from apps.orders.utils.rental_billing import (
    min_units_label,
    rental_start_allowed,
    total_billed_units,
)
from apps.orders.utils.validators import order_item_conflicts
from apps.ad_spaces.utils.catalog_client_scope import (
    MINE_ACTIVE,
    MINE_CART,
    MINE_FAVORITES,
    MINE_RESERVED,
    apply_catalog_mine_filter,
    count_catalog_scope,
    parse_cart_ad_space_ids,
)
from apps.workspaces.tenant import get_workspace_for_request

_EMPTY_CITY_SENTINEL = "__empty__"


class RentalSegmentCheckSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class CheckRentalRangeSerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    rental_segments = RentalSegmentCheckSerializer(many=True, required=False)

    def validate(self, attrs):
        segments = attrs.get("rental_segments") or []
        if segments:
            attrs["_segments"] = segments
            return attrs
        start = attrs.get("start_date")
        end = attrs.get("end_date")
        if not start or not end:
            raise serializers.ValidationError(
                "Indica un rango (inicio y fin) o una lista rental_segments."
            )
        attrs["_segments"] = [{"start_date": start, "end_date": end}]
        return attrs


class CatalogMountingProvidersPagination(PageNumberPagination):
    page_size = MOUNTING_PROVIDERS_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = 50


class AdSpaceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdSpaceSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        request = self.request
        if request.user.is_authenticated:
            from apps.users.utils import get_marketplace_client

            client = get_marketplace_client(request.user)
            if client is not None:
                ctx["marketplace_client"] = client
        return ctx

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        context = self.get_serializer_context()
        client = context.get("marketplace_client")
        if client is not None:
            targets = page if page is not None else queryset
            ids = [obj.pk for obj in targets]
            if ids:
                from apps.ad_spaces.utils.availability_calendar import (
                    client_months_highlight_by_year_bulk,
                )

                context["client_months_bulk"] = client_months_highlight_by_year_bulk(
                    ids, client.pk
                )
        if page is not None:
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response(serializer.data)

    @staticmethod
    def _apply_list_search(qs, search: str):
        if not search:
            return qs
        return qs.filter(
            Q(code__icontains=search)
            | Q(name__icontains=search)
            | Q(description__icontains=search)
            | Q(formats__location__icontains=search)
            | Q(formats__product_type__name__icontains=search)
            | Q(shopping_center__name__icontains=search)
            | Q(shopping_center__city__icontains=search)
        ).distinct()

    def _catalog_base_qs(self, request, *, apply_mine: bool = True):
        """Tomas publicables del tenant con filtros de listado/facets (sin prefetch)."""
        qs = AdSpace.objects.filter(
            shopping_center__is_active=True,
            is_active=True,
        )
        ws = get_workspace_for_request(request)
        if ws is not None:
            qs = qs.filter(shopping_center__workspace=ws)
        center = (request.query_params.get("center") or "").strip()
        if center:
            qs = qs.filter(shopping_center__slug__iexact=center)
        search = (request.query_params.get("search") or "").strip()
        qs = self._apply_list_search(qs, search)
        city = (request.query_params.get("city") or "").strip()
        if city == _EMPTY_CITY_SENTINEL:
            qs = qs.filter(shopping_center__city="")
        elif city:
            qs = qs.filter(shopping_center__city__iexact=city)
        space_type = (request.query_params.get("type") or "").strip()
        if space_type:
            qs = qs.filter(formats__product_type__slug=space_type).distinct()
        if apply_mine:
            mine = (request.query_params.get("mine") or "").strip().lower()
            if mine:
                client = None
                if request.user.is_authenticated:
                    from apps.users.utils import get_marketplace_client

                    client = get_marketplace_client(request.user)
                cart_ids = parse_cart_ad_space_ids(
                    request.query_params.get("cart_ids") or ""
                )
                qs = apply_catalog_mine_filter(
                    qs,
                    mine=mine,
                    client_id=client.pk if client else None,
                    cart_ad_space_ids=cart_ids if mine == MINE_CART else None,
                )
        return qs

    def get_queryset(self):
        qs = self._catalog_base_qs(self.request).select_related("shopping_center")
        return qs.prefetch_related(
            "gallery_images",
            Prefetch(
                "formats",
                queryset=AdSpaceFormat.objects.select_related("product_type").order_by(
                    "sort_order", "id"
                ),
            ),
            Prefetch(
                "shopping_center__mounting_providers",
                queryset=MountingProvider.objects.filter(is_active=True).order_by(
                    "sort_order", "id"
                ),
            ),
        ).order_by("-created_at", "-id")

    @action(detail=True, methods=["post"], url_path="check-rental-range")
    def check_rental_range(self, request, pk=None):
        """
        Comprueba solapamiento con órdenes en pipeline y bloques (misma regla que al enviar la orden).
        """
        space = self.get_object()
        ser = CheckRentalRangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        segments = ser.validated_data["_segments"]
        from apps.orders.utils.validators import ad_space_allows_marketplace_reservation

        if not ad_space_allows_marketplace_reservation(space):
            return Response(
                {
                    "ok": False,
                    "detail": (
                        "Esta toma no admite nuevas reservas en el marketplace "
                        f"(estado: {space.get_status_display()})."
                    ),
                },
                status=200,
            )
        center = space.shopping_center
        unit = center.rental_billing_unit
        title = (space.name or "").strip() or "esta toma"
        total_units = 0
        for seg in segments:
            start = seg["start_date"]
            end = seg["end_date"]
            if end < start:
                return Response(
                    {
                        "ok": False,
                        "detail": "En cada tramo, la fecha fin debe ser posterior o igual al inicio.",
                    },
                    status=200,
                )
            total_units += total_billed_units(unit, start, end)
            if not rental_start_allowed(unit, start):
                return Response(
                    {
                        "ok": False,
                        "detail": (
                            "La fecha de inicio no puede ser hoy ni un día pasado."
                            if unit == "calendar_day"
                            else (
                                "No puedes reservar desde un mes pasado. "
                                "El mes en curso solo está disponible hasta el día 15."
                            )
                        ),
                    },
                    status=200,
                )
            if order_item_conflicts(space.pk, start, end):
                return Response(
                    {
                        "ok": False,
                        "detail": f'Las fechas elegidas para «{title}» chocan con otra reserva o bloqueo.',
                    },
                    status=200,
                )
        n_min, label = min_units_label(unit)
        if total_units < n_min:
            return Response(
                {
                    "ok": False,
                    "detail": f"Elige al menos {n_min} {label} en total.",
                },
                status=200,
            )
        from apps.orders.utils.validators import order_request_items_have_internal_overlap

        pseudo = [
            {"ad_space": space, "start_date": s["start_date"], "end_date": s["end_date"]}
            for s in segments
        ]
        if order_request_items_have_internal_overlap(pseudo):
            return Response(
                {
                    "ok": False,
                    "detail": "Los tramos elegidos no pueden solaparse entre sí.",
                },
                status=200,
            )
        return Response({"ok": True}, status=200)

    @action(detail=True, methods=["get"], url_path="mounting-providers")
    def mounting_providers(self, request, pk=None):
        """Proveedores de montaje del centro de la toma, paginados (page_size por defecto 5)."""
        space = self.get_object()
        qs = MountingProvider.objects.filter(
            shopping_centers=space.shopping_center_id,
            is_active=True,
        ).order_by("sort_order", "id").distinct()
        paginator = CatalogMountingProvidersPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        ser = CatalogMountingProviderSerializer(
            page, many=True, context=self.get_serializer_context()
        )
        return paginator.get_paginated_response(ser.data)

    @action(detail=False, methods=["get"], url_path="location-facets")
    def location_facets(self, request):
        """
        Conteos por ciudad del centro (para pills en portada). Respeta tenant y búsqueda de listado.
        """
        qs = self._catalog_base_qs(request)
        total = qs.count()
        rows = (
            qs.exclude(shopping_center__city="")
            .values("shopping_center__city")
            .annotate(count=Count("id"))
            .order_by("-count", "shopping_center__city")
        )
        items = [
            {"city": r["shopping_center__city"], "count": r["count"]} for r in rows
        ]
        empty_city = qs.filter(shopping_center__city="").count()
        if empty_city:
            items.append(
                {"city": _EMPTY_CITY_SENTINEL, "label": "Sin ciudad", "count": empty_city}
            )
        return Response({"total": total, "items": items})

    @action(detail=False, methods=["get"], url_path="center-facets")
    def center_facets(self, request):
        """
        Conteos por centro comercial (slug + nombre) para pills en portada.
        Respeta tenant, búsqueda de listado y filtro opcional por ciudad.
        """
        qs = self._catalog_base_qs(request)
        total = qs.count()
        rows = (
            qs.values("shopping_center__slug", "shopping_center__name")
            .annotate(count=Count("id"))
            .order_by("-count", "shopping_center__name", "shopping_center__slug")
        )
        items = [
            {
                "slug": (r["shopping_center__slug"] or "").strip(),
                "name": (r["shopping_center__name"] or "").strip() or r["shopping_center__slug"],
                "count": r["count"],
            }
            for r in rows
            if (r.get("shopping_center__slug") or "").strip()
        ]
        return Response({"total": total, "items": items})

    @action(detail=False, methods=["get"], url_path="type-facets")
    def type_facets(self, request):
        """Conteos por tipo de elemento (product_type) para filtros en portada."""
        qs = self._catalog_base_qs(request)
        total = qs.count()
        rows = (
            qs.filter(formats__product_type__isnull=False)
            .values("formats__product_type__slug", "formats__product_type__name")
            .annotate(count=Count("id", distinct=True))
            .order_by("-count", "formats__product_type__name")
        )
        items = [
            {
                "type": (r["formats__product_type__slug"] or "").strip(),
                "label": (
                    (r["formats__product_type__name"] or r["formats__product_type__slug"] or "")
                    .strip()
                ),
                "count": r["count"],
            }
            for r in rows
            if (r.get("formats__product_type__slug") or "").strip()
        ]
        return Response({"total": total, "items": items})

    @action(detail=False, methods=["get"], url_path="client-scope-facets")
    def client_scope_facets(self, request):
        """
        Conteos para filtros «Mis favoritos», «Mis activos», «En carrito», «Mis reservas».
        Respeta búsqueda y filtros de ciudad, centro y tipo (no el filtro `mine` activo).
        """
        qs = self._catalog_base_qs(request, apply_mine=False)
        client = None
        if request.user.is_authenticated:
            from apps.users.utils import get_marketplace_client

            client = get_marketplace_client(request.user)
        cart_ids = parse_cart_ad_space_ids(request.query_params.get("cart_ids") or "")
        client_id = client.pk if client else None
        scopes = [
            (MINE_FAVORITES, "Mis favoritos"),
            (MINE_ACTIVE, "Mis activos"),
            (MINE_CART, "En carrito"),
            (MINE_RESERVED, "Mis reservas"),
        ]
        items = [
            {
                "scope": scope,
                "label": label,
                "count": count_catalog_scope(
                    qs,
                    scope,
                    client_id=client_id,
                    cart_ad_space_ids=cart_ids,
                ),
            }
            for scope, label in scopes
        ]
        return Response({"items": items})
