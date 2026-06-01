from django.utils.text import slugify
from rest_framework import serializers

from apps.ad_spaces.models import AdSpaceProductType


class AdSpaceProductTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdSpaceProductType
        fields = ("id", "name", "slug", "is_active", "created_at", "updated_at")
        read_only_fields = ("slug", "created_at", "updated_at")

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Indica un nombre para el tipo.")
        if len(name) > 120:
            raise serializers.ValidationError("El nombre no puede superar 120 caracteres.")
        return name

    def create(self, validated_data):
        ws = self.context["workspace"]
        name = validated_data["name"]
        base = slugify(name) or "tipo"
        slug = base[:64]
        n = 2
        while AdSpaceProductType.objects.filter(workspace=ws, slug=slug).exists():
            suffix = f"-{n}"
            slug = f"{base[: max(1, 64 - len(suffix))]}{suffix}"
            n += 1
        return AdSpaceProductType.objects.create(
            workspace=ws,
            name=name,
            slug=slug,
            is_active=validated_data.get("is_active", True),
        )
