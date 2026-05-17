from django.db import transaction
from django.db.models import Count, Prefetch, Q
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.malls.models import ShoppingCenter, ShoppingCenterMountingProvider
from apps.malls.serializers import MountingProviderSerializer, ShoppingCenterSerializer
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.workspaces.tenant import enforce_workspace_for_non_superuser, get_workspace_for_request


class MountingProviderAdminViewSet(AdminModelViewSet):
    """CRUD proveedores de montaje por centro (solo admin)."""

    queryset = ShoppingCenterMountingProvider.objects.all()
    serializer_class = MountingProviderSerializer

    def create(self, request, *args, **kwargs):
        raw_ids = request.data.get("shopping_center_ids")
        if isinstance(raw_ids, list) and len(raw_ids) > 0:
            ids = []
            for x in raw_ids:
                try:
                    ids.append(int(x))
                except (TypeError, ValueError):
                    continue
            ids = list(dict.fromkeys(ids))
            if not ids:
                return super().create(request, *args, **kwargs)
            base = dict(request.data)
            base.pop("shopping_center_ids", None)
            base.pop("shopping_center", None)
            created = []
            ctx = self.get_serializer_context()
            with transaction.atomic():
                for cid in ids:
                    payload = {**base, "shopping_center": cid}
                    ser = MountingProviderSerializer(data=payload, context=ctx)
                    ser.is_valid(raise_exception=True)
                    self.perform_create(ser)
                    created.append(ser.instance)
            out = MountingProviderSerializer(
                created, many=True, context=self.get_serializer_context()
            )
            return Response(out.data, status=status.HTTP_201_CREATED)
        return super().create(request, *args, **kwargs)

    def get_queryset(self):
        qs = ShoppingCenterMountingProvider.objects.select_related(
            "shopping_center", "shopping_center__workspace"
        ).order_by("shopping_center_id", "sort_order", "id")
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(shopping_center__workspace=ws)
        cid = self.request.query_params.get("shopping_center")
        if cid and str(cid).strip().isdigit():
            qs = qs.filter(shopping_center_id=int(cid))
        return qs


class ShoppingCenterAdminViewSet(AdminModelViewSet):
    """CRUD centros comerciales (solo rol admin)."""

    serializer_class = ShoppingCenterSerializer

    def perform_create(self, serializer):
        tw = enforce_workspace_for_non_superuser(
            self.request,
            serializer.validated_data.get("workspace"),
        )
        if not tw.can_create_shopping_centers:
            raise ValidationError(
                "No se pueden crear centros comerciales en este workspace. "
                "Si necesitas habilitarlo, contacta a la plataforma."
            )
        serializer.save(workspace=tw)

    def perform_update(self, serializer):
        extra = {}
        if "workspace" in serializer.validated_data:
            extra["workspace"] = enforce_workspace_for_non_superuser(
                self.request,
                serializer.validated_data.get("workspace"),
            )
        serializer.save(**extra)

    def get_queryset(self):
        qs = ShoppingCenter.objects.all().order_by("-created_at", "-id")
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(workspace=ws)
        if self.action == "list":
            qs = qs.annotate(tomas_count=Count("ad_spaces", distinct=True))
            active = self.request.query_params.get("active", "all")
            if active == "active":
                qs = qs.filter(is_active=True)
            elif active == "inactive":
                qs = qs.filter(is_active=False)
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(slug__icontains=search)
                    | Q(name__icontains=search)
                    | Q(city__icontains=search)
                    | Q(district__icontains=search)
                )
        return qs.prefetch_related(
            Prefetch(
                "mounting_providers",
                queryset=ShoppingCenterMountingProvider.objects.order_by("sort_order", "id"),
            ),
        )
