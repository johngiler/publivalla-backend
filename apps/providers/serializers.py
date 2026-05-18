from rest_framework import serializers

from apps.malls.models import ShoppingCenter
from apps.providers.models import MountingProvider
from apps.workspaces.tenant import get_workspace_for_request


class CatalogMountingProviderSerializer(serializers.ModelSerializer):
    """Campos públicos del proveedor de montaje (catálogo / detalle de toma)."""

    class Meta:
        model = MountingProvider
        fields = (
            "id",
            "company_name",
            "contact_name",
            "phone",
            "email",
            "rif",
            "notes",
        )


class MountingProviderSerializer(serializers.ModelSerializer):
    shopping_center = serializers.PrimaryKeyRelatedField(
        queryset=ShoppingCenter.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    shopping_center_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        write_only=True,
        required=False,
        allow_empty=True,
    )
    shopping_center_name = serializers.SerializerMethodField(read_only=True)
    shopping_center_names = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = MountingProvider
        fields = (
            "id",
            "workspace",
            "shopping_center",
            "shopping_center_ids",
            "shopping_center_name",
            "shopping_center_names",
            "company_name",
            "contact_name",
            "phone",
            "email",
            "rif",
            "notes",
            "sort_order",
            "is_active",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "workspace": {"required": False, "read_only": True},
            "contact_name": {"required": False, "allow_blank": True},
            "phone": {"required": False, "allow_blank": True},
            "email": {"required": False, "allow_blank": True},
            "rif": {"required": False, "allow_blank": True},
            "notes": {"required": False, "allow_blank": True},
            "created_at": {"read_only": True},
            "updated_at": {"read_only": True},
        }

    def get_shopping_center_name(self, obj):
        first = self._ordered_centers(obj).first()
        return first.name if first else None

    def get_shopping_center_names(self, obj):
        return [c.name for c in self._ordered_centers(obj)]

    def _ordered_centers(self, obj):
        cache = getattr(obj, "_prefetched_objects_cache", None)
        if cache is not None and "shopping_centers" in cache:
            centers = list(cache["shopping_centers"])
            centers.sort(key=lambda c: (c.listing_order, c.slug, c.id))
            return centers
        return obj.shopping_centers.order_by("listing_order", "slug", "id")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        centers = self._ordered_centers(instance)
        data["shopping_center"] = centers[0].pk if centers else None
        data["shopping_center_ids"] = [c.pk for c in centers]
        return data

    def _resolve_center_ids(self, attrs):
        ids: list[int] = []
        if attrs.get("shopping_center_ids"):
            ids.extend(attrs["shopping_center_ids"])
        center = attrs.get("shopping_center")
        if center is not None:
            ids.append(center.pk)
        return list(dict.fromkeys(ids))

    def _centers_for_ids(self, center_ids: list[int]):
        if not center_ids:
            return []
        centers = list(ShoppingCenter.objects.filter(pk__in=center_ids).select_related("workspace"))
        found = {c.pk for c in centers}
        missing = set(center_ids) - found
        if missing:
            raise serializers.ValidationError(
                {"shopping_center_ids": f"No existen centros con id: {sorted(missing)}."}
            )
        return centers

    def validate(self, attrs):
        request = self.context.get("request")
        ws = get_workspace_for_request(request) if request else None

        center_ids = self._resolve_center_ids(attrs)
        attrs.pop("shopping_center", None)
        attrs.pop("shopping_center_ids", None)

        if self.instance is None and not center_ids:
            raise serializers.ValidationError(
                {"shopping_center_ids": "Indica al menos un centro comercial."}
            )

        centers = self._centers_for_ids(center_ids) if center_ids else []
        if centers:
            workspace_ids = {c.workspace_id for c in centers}
            if len(workspace_ids) > 1:
                raise serializers.ValidationError(
                    {"shopping_center_ids": "Todos los centros deben pertenecer al mismo espacio de trabajo."}
                )
            if ws is not None and ws.id not in workspace_ids:
                raise serializers.ValidationError(
                    {"shopping_center_ids": "Los centros no pertenecen a tu espacio de trabajo."}
                )
            attrs["_workspace_id"] = next(iter(workspace_ids))
        elif self.instance is not None:
            attrs["_workspace_id"] = self.instance.workspace_id
        elif ws is not None:
            attrs["_workspace_id"] = ws.id

        attrs["_centers"] = centers
        return attrs

    def create(self, validated_data):
        centers = validated_data.pop("_centers")
        workspace_id = validated_data.pop("_workspace_id")
        validated_data.pop("workspace", None)
        provider = MountingProvider.objects.create(
            workspace_id=workspace_id,
            **validated_data,
        )
        if centers:
            provider.shopping_centers.set(centers)
        return provider

    def update(self, instance, validated_data):
        centers = validated_data.pop("_centers", None)
        validated_data.pop("_workspace_id", None)
        validated_data.pop("workspace", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if centers is not None:
            instance.shopping_centers.set(centers)
        return instance
