from rest_framework import serializers

from django.contrib.auth import get_user_model

from apps.clients.models import Client, ClientBrand, ClientStatus
from apps.clients.utils.marketplace_user import validate_member_brand_ids
from apps.users.models import UserProfile
from apps.clients.validators import (
    normalize_client_representative_fields,
    normalize_client_rif_required,
)
from apps.users.utils import is_platform_staff
from apps.workspaces.tenant import get_workspace_for_request


class ClientBrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientBrand
        fields = ("id", "name", "logo")
        read_only_fields = ("id",)
        extra_kwargs = {
            "logo": {"required": False, "allow_null": True},
            "name": {"required": True, "allow_blank": False},
        }

    def validate_name(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError("Indica el nombre de la marca.")
        if len(s) > 255:
            raise serializers.ValidationError("El nombre es demasiado largo.")
        return s


class ClientAdminSerializer(serializers.ModelSerializer):
    """Admin: datos de empresa. Usuarios enlazados vía UserProfile.client (varios por empresa)."""

    linked_user_ids = serializers.SerializerMethodField()
    linked_usernames = serializers.SerializerMethodField()
    orders_count = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    brands = ClientBrandSerializer(many=True, read_only=True)

    class Meta:
        model = Client
        fields = (
            "id",
            "workspace",
            "linked_user_ids",
            "linked_usernames",
            "orders_count",
            "brands",
            "company_name",
            "rif",
            "contact_name",
            "representative_name",
            "representative_id_number",
            "email",
            "phone",
            "address",
            "city",
            "notes",
            "status",
            "status_label",
            "cover_image",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("linked_user_ids", "linked_usernames", "created_at", "updated_at")
        extra_kwargs = {
            "workspace": {"read_only": True},
            "cover_image": {"required": False, "allow_null": True},
        }

    def validate_rif(self, value):
        incoming = (value or "").strip() if value is not None else ""
        if self.instance is not None:
            existing = (self.instance.rif or "").strip()
            if incoming:
                return normalize_client_rif_required(incoming)
            if existing:
                return existing
            return normalize_client_rif_required("")
        return normalize_client_rif_required(value)

    def validate(self, attrs):
        inst = self.instance
        rep_name = attrs.get(
            "representative_name",
            getattr(inst, "representative_name", None) if inst else None,
        )
        rep_ci = attrs.get(
            "representative_id_number",
            getattr(inst, "representative_id_number", None) if inst else None,
        )
        rep_name, rep_ci = normalize_client_representative_fields(
            representative_name=rep_name,
            representative_id_number=rep_ci,
        )
        attrs["representative_name"] = rep_name
        attrs["representative_id_number"] = rep_ci
        return attrs

    def get_linked_user_ids(self, obj):
        return sorted(obj.member_profiles.values_list("user_id", flat=True))

    def get_linked_usernames(self, obj):
        profiles = obj.member_profiles.select_related("user").order_by("user__username")
        return [p.user.username for p in profiles]

    def get_orders_count(self, obj):
        if hasattr(obj, "_orders_count"):
            return obj._orders_count
        return obj.orders.count()

    def get_status_label(self, obj):
        return obj.get_status_display()


class MyCompanySerializer(serializers.ModelSerializer):
    rif = serializers.CharField(max_length=32, required=True, allow_blank=False)

    class Meta:
        model = Client
        fields = (
            "company_name",
            "rif",
            "contact_name",
            "representative_name",
            "representative_id_number",
            "email",
            "phone",
            "address",
            "city",
            "cover_image",
        )
        extra_kwargs = {
            "cover_image": {"required": False, "allow_null": True},
        }

    def validate_rif(self, value):
        instance = getattr(self, "instance", None)
        existing = (instance.rif or "").strip() if instance else ""
        s = str(value or "").strip()
        if s:
            return normalize_client_rif_required(s)
        if existing:
            return existing
        return normalize_client_rif_required(value)

    def validate(self, attrs):
        inst = self.instance
        rep_name = attrs.get(
            "representative_name",
            getattr(inst, "representative_name", None) if inst else None,
        )
        rep_ci = attrs.get(
            "representative_id_number",
            getattr(inst, "representative_id_number", None) if inst else None,
        )
        rep_name, rep_ci = normalize_client_representative_fields(
            representative_name=rep_name,
            representative_id_number=rep_ci,
        )
        attrs["representative_name"] = rep_name
        attrs["representative_id_number"] = rep_ci
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        if is_platform_staff(request.user):
            raise serializers.ValidationError({"detail": "No se pudo completar la solicitud."})
        ws = get_workspace_for_request(request)
        if not ws:
            raise serializers.ValidationError(
                {
                    "detail": "No hay workspace para esta petición. Revisa el subdominio o configura DEFAULT_WORKSPACE_SLUG."
                }
            )
        c = Client.objects.create(
            status=ClientStatus.ACTIVE,
            workspace=ws,
            **validated_data,
        )
        prof, _ = UserProfile.objects.get_or_create(user=request.user)
        prof.client = c
        prof.save(update_fields=["client"])
        return c


User = get_user_model()


class CompanyMemberSerializer(serializers.Serializer):
    """Usuario cliente vinculado a la empresa (Mi empresa → Usuarios)."""

    id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    brands = serializers.SerializerMethodField()
    is_self = serializers.SerializerMethodField()

    def get_brands(self, obj: UserProfile):
        links = getattr(obj, "brand_links", None)
        if links is None:
            return []
        rows = []
        for link in links.all():
            brand = link.brand
            if brand and brand.is_active:
                rows.append(brand)
        ser = ClientBrandSerializer(rows, many=True, context=self.context)
        return ser.data

    def get_is_self(self, obj: UserProfile) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.user_id == request.user.pk


class CompanyMemberCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    brand_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )

    def validate_email(self, value):
        return (value or "").strip().lower()

    def validate_brand_ids(self, value):
        client = self.context.get("client")
        if client is None:
            return value or []
        try:
            return validate_member_brand_ids(client, value)
        except Exception as exc:
            from apps.clients.utils.marketplace_user import MarketplaceUserError

            if isinstance(exc, MarketplaceUserError) and exc.code == "invalid_brands":
                raise serializers.ValidationError(exc.message) from exc
            raise


class CompanyMemberUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    brand_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )

    def validate_brand_ids(self, value):
        profile = self.context.get("profile")
        if profile is None or profile.client_id is None:
            return value or []
        try:
            return validate_member_brand_ids(profile.client, value)
        except Exception as exc:
            from apps.clients.utils.marketplace_user import MarketplaceUserError

            if isinstance(exc, MarketplaceUserError) and exc.code == "invalid_brands":
                raise serializers.ValidationError(exc.message) from exc
            raise
