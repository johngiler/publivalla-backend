from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets

from apps.malls.models import ShoppingCenter
from apps.malls.serializers import ShoppingCenterSerializer
from apps.workspaces.tenant import get_workspace_for_request


class ShoppingCenterViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Listado público de centros filtrado por `on_homepage` (la portada del sitio lista tomas, no centros).
    Detalle por slug (`/api/centers/mi-centro/`).

    Listado: filtros opcionales `search`, `catalog_status` (all|available|soon),
    `location` (all|caracas|other). Paginación estándar (20 por página).
    """

    queryset = ShoppingCenter.objects.filter(on_homepage=True).order_by(
        "listing_order", "-created_at", "slug"
    )
    serializer_class = ShoppingCenterSerializer
    lookup_field = "slug"
    lookup_value_regex = r"[a-zA-Z0-9-]+"

    def get_object(self):
        """Acepta slug en la URL sin distinguir mayúsculas/minúsculas (compat. con enlaces antiguos)."""
        if self.lookup_field not in self.kwargs:
            return super().get_object()
        qs = self.filter_queryset(self.get_queryset())
        slug = self.kwargs[self.lookup_field]
        return get_object_or_404(qs, slug__iexact=slug)

    def get_queryset(self):
        qs = ShoppingCenter.objects.filter(on_homepage=True).order_by(
            "listing_order", "-created_at", "slug"
        )
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(workspace=ws)
        if self.action != "list":
            return qs
        params = self.request.query_params
        search = params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(city__icontains=search)
                | Q(district__icontains=search)
                | Q(slug__icontains=search)
            )
        catalog_status = params.get("catalog_status", "all")
        if catalog_status == "available":
            qs = qs.filter(is_active=True, marketplace_catalog_enabled=True)
        elif catalog_status == "soon":
            qs = qs.filter(is_active=True, marketplace_catalog_enabled=False)
        location = params.get("location", "all")
        if location == "caracas":
            qs = qs.filter(
                Q(name__icontains="caracas")
                | Q(city__icontains="caracas")
                | Q(district__icontains="caracas")
            )
        elif location == "other":
            caracas_q = (
                Q(name__icontains="caracas")
                | Q(city__icontains="caracas")
                | Q(district__icontains="caracas")
            )
            qs = qs.exclude(caracas_q)
        return qs.order_by("listing_order", "-created_at", "slug")
