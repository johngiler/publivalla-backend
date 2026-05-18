from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.ad_spaces.models import AdSpace, AdSpaceStatus
from apps.ad_spaces.utils.nomenclature import validate_toma_code


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
    status_label = serializers.SerializerMethodField()
    gallery_images = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = AdSpace
        fields = (
            "id",
            "code",
            "shopping_center",
            "shopping_center_slug",
            "shopping_center_name",
            "shopping_center_city",
            "type",
            "title",
            "description",
            "width",
            "height",
            "quantity",
            "material",
            "location_description",
            "level",
            "monthly_price_usd",
            "status",
            "status_label",
            "cover_image",
            "gallery_images",
            "venue_zone",
            "double_sided",
            "production_specs",
            "installation_notes",
            "hem_pocket_top_cm",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")
        extra_kwargs = {"cover_image": {"required": False, "allow_null": True}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self, "instance", None) is not None:
            self.fields["code"].read_only = True

    def validate_status(self, value):
        if value == "reserved":
            raise serializers.ValidationError(
                "El estado «Reservado» ya no aplica a espacios publicitarios. "
                "Usa Disponible, Ocupado o Bloqueado."
            )
        allowed = {c.value for c in AdSpaceStatus}
        if value not in allowed:
            raise serializers.ValidationError("Estado no válido.")
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

    def get_status_label(self, obj):
        return obj.get_status_display()

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
