from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.ad_spaces.models import AdSpace, AdSpaceFormat, AdSpaceAvailability
from apps.ad_spaces.utils.nomenclature import validate_toma_code


class AdSpaceFormatSerializer(serializers.ModelSerializer):
    product_type_id = serializers.IntegerField(source="product_type.id", read_only=True)
    product_type_name = serializers.CharField(source="product_type.name", read_only=True)
    product_type_slug = serializers.CharField(source="product_type.slug", read_only=True)

    class Meta:
        model = AdSpaceFormat
        fields = (
            "id",
            "product_type_id",
            "product_type_name",
            "product_type_slug",
            "width",
            "height",
            "quantity",
            "location",
            "double_sided",
            "sort_order",
        )
        read_only_fields = fields


class AdSpaceAdminSerializer(serializers.ModelSerializer):
    shopping_center_slug = serializers.CharField(
        source="shopping_center.slug", read_only=True
    )
    shopping_center_name = serializers.CharField(
        source="shopping_center.name", read_only=True
    )
    shopping_center_city = serializers.CharField(
        source="shopping_center.city", read_only=True, allow_blank=True
    )
    availability_label = serializers.SerializerMethodField()
    gallery_images = serializers.SerializerMethodField(read_only=True)
    formats = AdSpaceFormatSerializer(many=True, read_only=True)
    location_image_url = serializers.SerializerMethodField(read_only=True)
    production_image_url = serializers.SerializerMethodField(read_only=True)
    # Alias legacy para consumidores que aún lean `title`
    title = serializers.CharField(source="name", read_only=True)

    class Meta:
        model = AdSpace
        fields = (
            "id",
            "code",
            "shopping_center",
            "shopping_center_slug",
            "shopping_center_name",
            "shopping_center_city",
            "name",
            "title",
            "description",
            "monthly_price_usd",
            "availability",
            "availability_label",
            "cover_image",
            "location_image",
            "production_image",
            "location_image_url",
            "production_image_url",
            "gallery_images",
            "formats",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at", "formats")
        extra_kwargs = {
            "cover_image": {"required": False, "allow_null": True},
            "location_image": {"required": False, "allow_null": True},
            "production_image": {"required": False, "allow_null": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self, "instance", None) is not None:
            self.fields["code"].read_only = True

    def validate_availability(self, value):
        if value == "reserved":
            raise serializers.ValidationError(
                "La disponibilidad «Reservado» ya no aplica a espacios publicitarios. "
                "Usa Disponible, Ocupado o Bloqueado."
            )
        allowed = {c.value for c in AdSpaceAvailability}
        if value not in allowed:
            raise serializers.ValidationError("Disponibilidad no válida.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is None:
            code = attrs.get("code")
            if code is not None:
                try:
                    attrs["code"] = validate_toma_code(code)
                except DjangoValidationError as exc:
                    raise serializers.ValidationError(
                        {"code": list(exc.messages)}
                    ) from exc
        return attrs

    def get_availability_label(self, obj):
        return obj.get_availability_display()

    def _absolute_media(self, f) -> str | None:
        if not f:
            return None
        request = self.context.get("request")
        url = f.url
        if request:
            uri = request.build_absolute_uri(url)
            if uri.startswith("http://") and request.META.get(
                "HTTP_X_FORWARDED_PROTO", ""
            ).lower() == "https":
                return "https://" + uri[7:]
            return uri
        return url

    def get_location_image_url(self, obj):
        return self._absolute_media(obj.location_image)

    def get_production_image_url(self, obj):
        return self._absolute_media(obj.production_image)

    def get_gallery_images(self, obj):
        out = []
        for i in obj.gallery_images.all():
            out.append(
                {
                    "id": i.id,
                    "image": i.image.url if i.image else "",
                    "sort_order": i.sort_order,
                }
            )
        return out
