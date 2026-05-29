from rest_framework import serializers

from apps.malls.models import ShoppingCenter
from apps.providers.serializers import MountingProviderSerializer


class ShoppingCenterSerializer(serializers.ModelSerializer):
    display_title = serializers.SerializerMethodField(read_only=True)
    marketplace_enabled = serializers.SerializerMethodField(read_only=True)
    cover_image_url = serializers.SerializerMethodField(read_only=True)
    mounting_providers = MountingProviderSerializer(many=True, read_only=True)
    tomas_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ShoppingCenter
        fields = (
            "id",
            "workspace",
            "name",
            "slug",
            "city",
            "address",
            "country",
            "description",
            "cover_image",
            "cover_image_url",
            "lessor_legal_name",
            "lessor_rif",
            "municipal_authority_line",
            "municipal_permit_notice",
            "advertising_regulations",
            "authorization_letter_city",
            "high_season_months",
            "high_season_multiplier",
            "rental_billing_unit",
            "mounting_providers",
            "tomas_count",
            "display_title",
            "marketplace_enabled",
            "is_active",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "workspace": {"read_only": True},
            "cover_image": {"required": False, "allow_null": True},
            "created_at": {"read_only": True},
            "updated_at": {"read_only": True},
            "high_season_months": {"read_only": True},
            "high_season_multiplier": {"read_only": True},
            "rental_billing_unit": {"read_only": True},
        }

    def get_display_title(self, obj):
        city = (obj.city or "").strip()
        if city:
            return city.upper()
        return obj.name

    def get_marketplace_enabled(self, obj):
        """Centro con catálogo y reservas públicas (equivale a `is_active`)."""
        return bool(obj.is_active)

    def get_cover_image_url(self, obj):
        if not obj.cover_image:
            return None
        request = self.context.get("request")
        url = obj.cover_image.url
        if request:
            uri = request.build_absolute_uri(url)
            if uri.startswith("http://") and request.META.get("HTTP_X_FORWARDED_PROTO", "").lower() == "https":
                return "https://" + uri[7:]
            return uri
        return url
