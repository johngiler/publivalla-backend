import re

from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.ad_spaces.serializers import AdSpaceAdminSerializer
from apps.ad_spaces.utils.format_sync import apply_ad_space_formats_from_request
from apps.ad_spaces.utils.gallery import apply_ad_space_gallery_from_request
from apps.ad_spaces.models import AdSpace
from apps.malls.models import ShoppingCenter
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.workspaces.tenant import get_workspace_for_request


class AdSpaceAdminViewSet(AdminModelViewSet):
    """CRUD tomas / espacios publicitarios (solo rol admin)."""

    serializer_class = AdSpaceAdminSerializer
    _RE_CODE = re.compile(
        r"^(?P<prefix>[A-Z0-9]{2,5})-T(?P<num>\d{1,3})(?P<suf>[A-Z]?)$")

    def _assert_center_in_tenant(self, center):
        if center is None:
            return
        ws = get_workspace_for_request(self.request)
        if ws is None:
            raise ValidationError(
                {"shopping_center": "No se pudo determinar el owner de esta petición."}
            )
        if center.workspace_id != ws.id:
            raise ValidationError(
                {"shopping_center": "Este centro no pertenece al owner de este sitio."}
            )

    def perform_create(self, serializer):
        ws = get_workspace_for_request(self.request)
        if ws is not None and not ws.can_create_ad_spaces:
            raise ValidationError(
                "No se pueden crear tomas en este workspace. "
                "Si necesitas habilitarlo, contacta a la plataforma."
            )
        self._assert_center_in_tenant(
            serializer.validated_data.get("shopping_center"))
        instance = serializer.save()
        apply_ad_space_gallery_from_request(instance, self.request)
        apply_ad_space_formats_from_request(instance, self.request)

    def perform_update(self, serializer):
        center = serializer.validated_data.get("shopping_center")
        if center is not None:
            self._assert_center_in_tenant(center)
        instance = serializer.save()
        apply_ad_space_gallery_from_request(instance, self.request)
        apply_ad_space_formats_from_request(instance, self.request)

    def get_queryset(self):
        qs = AdSpace.objects.select_related("shopping_center").all().order_by(
            "-created_at", "-id"
        )
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(shopping_center__workspace=ws)
        if self.action == "list":
            availability = self.request.query_params.get("availability", "").strip()
            if availability and availability != "all":
                qs = qs.filter(availability=availability)
            active = self.request.query_params.get("active", "all")
            if active == "active":
                qs = qs.filter(is_active=True)
            elif active == "inactive":
                qs = qs.filter(is_active=False)
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(code__icontains=search) | Q(name__icontains=search)
                )
            center_raw = self.request.query_params.get("shopping_center", "").strip()
            if center_raw.isdigit():
                qs = qs.filter(shopping_center_id=int(center_raw))
        return qs.prefetch_related(
            "gallery_images",
            "formats__product_type",
        )

    @action(detail=False, methods=["get"], url_path="next-code")
    def next_code(self, request):
        """
        Sugiere el próximo código de toma para un centro (prefijo + T{n}).
        - Prefijo: se infiere desde códigos existentes del centro; si no hay, desde el slug.
        - Sugerencia: toma el mayor número encontrado y suma 1.
        """
        raw = (request.query_params.get("shopping_center") or "").strip()
        if not raw.isdigit():
            raise ValidationError(
                {"shopping_center": "Selecciona un centro comercial válido."})
        center_id = int(raw)
        ws = get_workspace_for_request(request)
        qs_center = ShoppingCenter.objects.all()
        if ws is not None:
            qs_center = qs_center.filter(workspace=ws)
        center = qs_center.filter(id=center_id).first()
        if center is None:
            raise ValidationError(
                {"shopping_center": "El centro comercial no existe o no pertenece a este workspace."})

        codes = list(
            AdSpace.objects.filter(
                shopping_center_id=center.id).values_list("code", flat=True)
        )
        prefix = ""
        max_n = 0
        for c in codes:
            m = self._RE_CODE.match((c or "").strip().upper())
            if not m:
                continue
            if not prefix:
                prefix = m.group("prefix")
            try:
                max_n = max(max_n, int(m.group("num")))
            except Exception:
                continue

        if not prefix:
            slug = (center.slug or "").strip().upper()
            ws_slug = (ws.slug if ws else "").strip().lower()
            parts = [
                p for p in slug.split("-") if p and (not ws_slug or p.lower() != ws_slug)
            ]
            prefix = (parts[0] if parts else slug)[:5] or "SC"

        candidate = f"{prefix}-T{max_n + 1}"
        return Response(
            {
                "shopping_center": center.id,
                "prefix": prefix,
                "max_existing_number": max_n,
                "suggested_code": candidate,
                "is_active": bool(center.is_active),
                "center_slug": center.slug,
                "center_name": center.name,
            }
        )
