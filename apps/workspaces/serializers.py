from rest_framework import serializers

from apps.workspaces.models import Workspace


class WorkspacePublicSerializer(serializers.ModelSerializer):
    """Branding y metadatos públicos del owner resuelto por la petición."""

    logo_url = serializers.SerializerMethodField()
    logo_mark_url = serializers.SerializerMethodField()
    favicon_url = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = (
            "slug",
            "name",
            "legal_name",
            "marketplace_title",
            "marketplace_tagline",
            "primary_color",
            "secondary_color",
            "support_email",
            "phone",
            "country",
            "city",
            "logo_url",
            "logo_mark_url",
            "favicon_url",
        )

    def _absolute_media(self, obj, field_name: str) -> str | None:
        f = getattr(obj, field_name, None)
        if not f:
            return None
        request = self.context.get("request")
        url = f.url
        if request:
            uri = request.build_absolute_uri(url)
            if uri.startswith("http://") and request.META.get("HTTP_X_FORWARDED_PROTO", "").lower() == "https":
                return "https://" + uri[7:]
            return uri
        return url

    def get_logo_url(self, obj):
        return self._absolute_media(obj, "logo")

    def get_logo_mark_url(self, obj):
        return self._absolute_media(obj, "logo_mark")

    def get_favicon_url(self, obj):
        return self._absolute_media(obj, "favicon")


class WorkspaceMeReadSerializer(WorkspacePublicSerializer):
    """
    Igual que la respuesta pública más flags de capacidad (solo GET/PATCH autenticado admin en /api/me/workspace/).
    No se expone en /api/workspace/current/ (anónimo).
    """

    transactional_email_password_set = serializers.SerializerMethodField()

    class Meta(WorkspacePublicSerializer.Meta):
        fields = WorkspacePublicSerializer.Meta.fields + (
            "can_create_shopping_centers",
            "can_create_ad_spaces",
            "can_create_marketplace_admin_users",
            "transactional_email_host",
            "transactional_email_port",
            "transactional_email_use_tls",
            "transactional_email_username",
            "transactional_email_password_set",
            "transactional_email_from_address",
            "transactional_email_from_name",
        )

    def get_transactional_email_password_set(self, obj):
        return bool((getattr(obj, "transactional_email_password", None) or "").strip())


class WorkspaceMeUpdateSerializer(serializers.ModelSerializer):
    """Actualización por el admin del owner; `slug` no se expone aquí (solo lectura en otro canal)."""

    class Meta:
        model = Workspace
        fields = (
            "name",
            "legal_name",
            "primary_color",
            "secondary_color",
            "support_email",
            "phone",
            "country",
            "city",
            "marketplace_title",
            "marketplace_tagline",
            "transactional_email_host",
            "transactional_email_port",
            "transactional_email_use_tls",
            "transactional_email_username",
            "transactional_email_from_address",
            "transactional_email_from_name",
        )
