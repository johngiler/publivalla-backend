"""CRUD admin de bloqueos de disponibilidad por toma."""

from __future__ import annotations

from django.db.models import Q

from apps.ad_spaces.utils.marketplace_availability import sync_ad_space_commercial_status
from apps.availability.models import AvailabilityBlock
from apps.availability.serializers import AvailabilityBlockAdminSerializer
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.workspaces.tenant import get_workspace_for_request


class AvailabilityBlockAdminViewSet(AdminModelViewSet):
    serializer_class = AvailabilityBlockAdminSerializer

    def _after_block_change(self, ad_space_id: int) -> None:
        sync_ad_space_commercial_status(ad_space_id, force_calendar=True)

    def perform_create(self, serializer):
        block = serializer.save()
        self._after_block_change(block.ad_space_id)

    def perform_update(self, serializer):
        block = serializer.save()
        self._after_block_change(block.ad_space_id)

    def perform_destroy(self, instance):
        ad_space_id = instance.ad_space_id
        super().perform_destroy(instance)
        self._after_block_change(ad_space_id)

    def get_queryset(self):
        qs = AvailabilityBlock.objects.select_related(
            "ad_space",
            "ad_space__shopping_center",
        ).order_by("-start_date", "-id")
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(ad_space__shopping_center__workspace=ws)

        if self.action == "list":
            cid = self.request.query_params.get("shopping_center", "").strip()
            if cid.isdigit():
                qs = qs.filter(ad_space__shopping_center_id=int(cid))
            aid = self.request.query_params.get("ad_space", "").strip()
            if aid.isdigit():
                qs = qs.filter(ad_space_id=int(aid))
            bt = self.request.query_params.get("type", "").strip()
            if bt and bt != "all":
                qs = qs.filter(type=bt)
            active = self.request.query_params.get("active", "").strip()
            if active == "1":
                qs = qs.filter(is_active=True, type="occupied")
            elif active == "0":
                qs = qs.filter(Q(is_active=False) | Q(type="expired"))
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(ad_space__code__icontains=search)
                    | Q(ad_space__title__icontains=search)
                    | Q(note__icontains=search)
                    | Q(ad_space__shopping_center__name__icontains=search)
                )
        return qs
