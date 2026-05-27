from django.db.models import Prefetch, Q
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
                    queryset=ShoppingCenter.objects.order_by("slug", "id"),
                )
            )
            .order_by("sort_order", "id")
        )
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(workspace=ws)
        if self.action == "list":
            cid = self.request.query_params.get("shopping_center", "").strip()
            if cid.isdigit():
                qs = qs.filter(shopping_centers__id=int(cid)).distinct()
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(company_name__icontains=search)
                    | Q(contact_name__icontains=search)
                    | Q(rif__icontains=search)
                    | Q(email__icontains=search)
                    | Q(phone__icontains=search)
                    | Q(notes__icontains=search)
                )
            active = self.request.query_params.get("active", "").strip()
            if active == "1":
                qs = qs.filter(is_active=True)
            elif active == "0":
                qs = qs.filter(is_active=False)
        return qs
