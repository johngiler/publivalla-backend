from decimal import Decimal

from rest_framework import serializers

from apps.malls.models import ShoppingCenter
from apps.malls.utils.high_season import normalize_high_season_months
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
            "district",
            "address",
            "country",
            "phone",
            "contact_email",
            "website",
            "description",
            "cover_image",
            "cover_image_url",
            "on_homepage",
            "listing_order",
            "marketplace_catalog_enabled",
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
            "workspace": {"required": False, "allow_null": True},
            "cover_image": {"required": False, "allow_null": True},
            "district": {"required": False, "allow_blank": True},
            "created_at": {"read_only": True},
            "updated_at": {"read_only": True},
        }

    def validate_high_season_months(self, value):
        return normalize_high_season_months(value)

    def validate_high_season_multiplier(self, value):
        if value is None:
            return Decimal("1.00")
        try:
            m = Decimal(str(value))
        except Exception:
            raise serializers.ValidationError("Indica un factor numérico válido.")
        if m < Decimal("1"):
            raise serializers.ValidationError("El factor debe ser al menos 1.")
        if m > Decimal("10"):
            raise serializers.ValidationError("El factor no puede superar 10.")
        return m.quantize(Decimal("0.01"))

    def get_display_title(self, obj):
        city = (obj.city or "").strip()
        district = (obj.district or "").strip()
        if district and city:
            return f"{city.upper()} — {district.upper()}"
        if city:
            return city.upper()
        return obj.name

    def get_marketplace_enabled(self, obj):
        """Alias de `marketplace_catalog_enabled` para el front (tarjetas «Disponible»)."""
        return bool(obj.marketplace_catalog_enabled)

    def get_cover_image_url(self, obj):
        if not obj.cover_image:
            return None
        request = self.context.get("request")
        url = obj.cover_image.url
        if request:
            uri = request.build_absolute_uri(url)
            # Tras Nginx+TLS, a veces `build_absolute_uri` sigue en http:// → contenido mixto en el SPA.
            if uri.startswith("http://") and request.META.get("HTTP_X_FORWARDED_PROTO", "").lower() == "https":
                return "https://" + uri[7:]
            return uri
        return url
