from django.db.models import Prefetch
from rest_framework.response import Response

from apps.malls.models import ShoppingCenter
from apps.providers.models import MountingProvider
from apps.providers.serializers import MountingProviderSerializer
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.workspaces.tenant import get_workspace_for_request


class MountingProviderAdminViewSet(AdminModelViewSet):
    """CRUD proveedores de montaje del tenant (solo admin)."""

    queryset = MountingProvider.objects.all()
    serializer_class = MountingProviderSerializer

    def perform_create(self, serializer):
        serializer.save()

    def get_queryset(self):
        qs = (
            MountingProvider.objects.select_related("workspace")
            .prefetch_related(
                Prefetch(
                    "shopping_centers",
                    queryset=ShoppingCenter.objects.order_by("listing_order", "slug", "id"),
                )
            )
            .order_by("sort_order", "id")
        )
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(workspace=ws)
        cid = self.request.query_params.get("shopping_center")
        if cid and str(cid).strip().isdigit():
            qs = qs.filter(shopping_centers__id=int(cid)).distinct()
        return qs
