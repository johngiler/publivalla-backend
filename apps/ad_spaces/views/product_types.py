from rest_framework.exceptions import ValidationError

from apps.ad_spaces.models import AdSpaceProductType
from apps.ad_spaces.serializers import AdSpaceProductTypeSerializer
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.workspaces.tenant import enforce_workspace_for_non_superuser, get_workspace_for_request


class AdSpaceProductTypeAdminViewSet(AdminModelViewSet):
    """Tipos de elemento publicitario del workspace (creatable en admin)."""

    serializer_class = AdSpaceProductTypeSerializer

    def get_queryset(self):
        qs = AdSpaceProductType.objects.filter(is_active=True).order_by("name", "slug")
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(workspace=ws)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["workspace"] = get_workspace_for_request(self.request)
        return ctx

    def perform_create(self, serializer):
        ws = enforce_workspace_for_non_superuser(self.request, None)
        if ws is None:
            raise ValidationError({"detail": "No se pudo determinar el workspace."})
        serializer.save(workspace=ws)
