"""Serializers admin de bloqueos de disponibilidad."""

from __future__ import annotations

from rest_framework import serializers

from apps.ad_spaces.models import AdSpace
from apps.availability.models import AvailabilityBlock, AvailabilityBlockType
from apps.availability.services.availability_block_services import (
    normalize_block_type_on_save,
)
from apps.workspaces.tenant import get_workspace_for_request


def _type_label(value: str) -> str:
    if not value:
        return ""
    try:
        return AvailabilityBlockType(value).label
    except ValueError:
        return value


class AvailabilityBlockAdminSerializer(serializers.ModelSerializer):
    ad_space_code = serializers.CharField(source="ad_space.code", read_only=True)
    ad_space_title = serializers.CharField(source="ad_space.title", read_only=True)
    shopping_center_id = serializers.IntegerField(
        source="ad_space.shopping_center_id", read_only=True
    )
    shopping_center_name = serializers.CharField(
        source="ad_space.shopping_center.name", read_only=True
    )
    type_label = serializers.SerializerMethodField()

    class Meta:
        model = AvailabilityBlock
        fields = (
            "id",
            "ad_space",
            "ad_space_code",
            "ad_space_title",
            "shopping_center_id",
            "shopping_center_name",
            "start_date",
            "end_date",
            "type",
            "type_label",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "ad_space_code",
            "ad_space_title",
            "shopping_center_id",
            "shopping_center_name",
            "type",
            "type_label",
            "created_at",
            "updated_at",
        )

    def get_type_label(self, obj):
        return _type_label(obj.type)

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "La fecha de fin no puede ser anterior a la de inicio."}
            )
        is_active = attrs.get("is_active", getattr(self.instance, "is_active", True))
        attrs["type"] = normalize_block_type_on_save(
            is_active=is_active,
            end_date=end,
        )
        attrs["is_active"] = attrs["type"] == AvailabilityBlockType.OCCUPIED
        return attrs

    def validate_ad_space(self, ad_space: AdSpace):
        request = self.context.get("request")
        if request is None:
            return ad_space
        ws = get_workspace_for_request(request)
        if ws is not None and ad_space.shopping_center.workspace_id != ws.id:
            raise serializers.ValidationError("Esta toma no pertenece a tu marketplace.")
        return ad_space
