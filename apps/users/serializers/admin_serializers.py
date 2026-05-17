from django.contrib.auth.models import User
from rest_framework import serializers

from apps.clients.models import Client
from apps.users.models import UserProfile
from apps.users.utils import get_user_profile, is_platform_staff


class NullableClientIdField(serializers.IntegerField):
    """FormData envía cadena vacía para «sin empresa»; JSON puede mandar null."""

    def to_internal_value(self, data):
        if data in ("", None):
            if self.allow_null:
                return None
        return super().to_internal_value(data)


def revoke_django_privileges(user):
    """Quita staff/superuser de Django al pasar a cliente marketplace."""
    if not user.is_staff and not user.is_superuser:
        return
    user.is_staff = False
    user.is_superuser = False
    user.save(update_fields=["is_staff", "is_superuser"])


class UserAdminSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    client_id = serializers.SerializerMethodField()
    client_company_name = serializers.SerializerMethodField()
    has_usable_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "role",
            "cover_image",
            "client_id",
            "client_company_name",
            "has_usable_password",
            "is_staff",
            "is_superuser",
            "date_joined",
        )

    def get_role(self, obj):
        p = get_user_profile(obj)
        return p.role if p else None

    def get_cover_image(self, obj):
        p = get_user_profile(obj)
        if p and p.cover_image:
            return p.cover_image.url
        return None

    def get_client_id(self, obj):
        p = get_user_profile(obj)
        return p.client_id if p and p.client_id else None

    def get_client_company_name(self, obj):
        p = get_user_profile(obj)
        if p and p.client_id:
            c = getattr(p, "client", None)
            return c.company_name if c else None
        return None

    def get_has_usable_password(self, obj):
        return obj.has_usable_password()


class UserAdminCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    role = serializers.ChoiceField(
        choices=UserProfile.Role.choices,
        default=UserProfile.Role.CLIENT,
    )
    cover_image = serializers.ImageField(required=False, allow_null=True)
    client_id = NullableClientIdField(required=False, allow_null=True)

    def validate_client_id(self, value):
        if value is None:
            return value
        request = self.context.get("request")
        tw = self.context.get("tenant_workspace")
        qs = Client.objects.filter(pk=value)
        if tw is not None and request is not None:
            qs = qs.filter(workspace=tw)
        if not qs.exists():
            raise serializers.ValidationError("Empresa (cliente) no encontrada.")
        return value

    def validate(self, attrs):
        role = attrs.get("role", UserProfile.Role.CLIENT)
        cid = attrs.get("client_id")
        if cid is not None and role != UserProfile.Role.CLIENT:
            raise serializers.ValidationError(
                {"client_id": "Solo los usuarios con rol «Cliente marketplace» pueden vincularse a una empresa."}
            )
        request = self.context.get("request")
        tw = self.context.get("tenant_workspace")
        if role == UserProfile.Role.ADMIN and tw is None and request is not None:
            raise serializers.ValidationError("No se pudo completar la solicitud.")
        if role == UserProfile.Role.CLIENT and cid is None:
            raise serializers.ValidationError(
                {"client_id": "Selecciona la empresa para el rol cliente marketplace."}
            )
        if (
            role == UserProfile.Role.ADMIN
            and tw is not None
            and not tw.can_create_marketplace_admin_users
        ):
            raise serializers.ValidationError(
                {
                    "role": "No está permitido crear usuarios con rol administrador marketplace en este workspace."
                }
            )
        return attrs

    def create(self, validated_data):
        cover = validated_data.pop("cover_image", None)
        role = validated_data.pop("role")
        client_id = validated_data.pop("client_id", None)
        tw = self.context.get("tenant_workspace")
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email", ""),
            password=validated_data["password"],
        )
        profile = user.profile
        profile.role = role
        if cover:
            profile.cover_image = cover
        if role == UserProfile.Role.ADMIN:
            profile.client = None
            profile.workspace = tw
        else:
            try:
                c = Client.objects.get(pk=client_id)
            except Client.DoesNotExist as exc:
                raise serializers.ValidationError({"client_id": "Empresa no encontrada."}) from exc
            if tw is not None and c.workspace_id != tw.id:
                raise serializers.ValidationError({"client_id": "Empresa no encontrada."})
            profile.client = c
            profile.workspace = c.workspace
        profile.full_clean()
        profile.save()
        revoke_django_privileges(user)
        return user


class UserAdminUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    role = serializers.ChoiceField(choices=UserProfile.Role.choices, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    cover_image = serializers.ImageField(required=False, allow_null=True)
    client_id = NullableClientIdField(required=False, allow_null=True)

    def validate_client_id(self, value):
        if value is None:
            return value
        request = self.context.get("request")
        tw = self.context.get("tenant_workspace")
        qs = Client.objects.filter(pk=value)
        if tw is not None and request is not None:
            qs = qs.filter(workspace=tw)
        if not qs.exists():
            raise serializers.ValidationError("Empresa (cliente) no encontrada.")
        return value

    def validate(self, attrs):
        inst = self.instance
        p = get_user_profile(inst)
        current_role = p.role if p else UserProfile.Role.CLIENT
        role_after = attrs.get("role", current_role)
        request = self.context.get("request")
        tw = self.context.get("tenant_workspace")

        if "client_id" in attrs and attrs["client_id"] is not None and role_after != UserProfile.Role.CLIENT:
            raise serializers.ValidationError(
                {"client_id": "Solo los usuarios con rol «Cliente marketplace» pueden vincularse a una empresa."}
            )

        if role_after == UserProfile.Role.ADMIN:
            if tw is None and request is not None:
                raise serializers.ValidationError("No se pudo completar la solicitud.")
            if "client_id" in attrs and attrs.get("client_id") is not None:
                raise serializers.ValidationError(
                    {
                        "client_id": "Los administradores del marketplace no llevan empresa vinculada.",
                    }
                )

        if role_after == UserProfile.Role.CLIENT:
            cid = attrs["client_id"] if "client_id" in attrs else (p.client_id if p else None)
            if cid is None:
                raise serializers.ValidationError(
                    {"client_id": "Selecciona la empresa para el rol cliente marketplace."}
                )

        promoting_to_admin = current_role != UserProfile.Role.ADMIN and role_after == UserProfile.Role.ADMIN
        if (
            promoting_to_admin
            and tw is not None
            and not tw.can_create_marketplace_admin_users
        ):
            raise serializers.ValidationError(
                {
                    "role": "No está permitido asignar el rol administrador marketplace en este workspace."
                }
            )

        return attrs

    def validate_password(self, value):
        if value and len(value) < 8:
            raise serializers.ValidationError("La contraseña debe tener al menos 8 caracteres.")
        return value

    def update(self, instance, validated_data):
        client_id_provided = "client_id" in validated_data
        client_id = validated_data.pop("client_id", None) if client_id_provided else None

        if "password" in validated_data:
            pwd = validated_data.pop("password")
            if pwd:
                instance.set_password(pwd)
                instance.save(update_fields=["password"])

        if "email" in validated_data:
            instance.email = validated_data["email"]
            instance.save(update_fields=["email"])

        if is_platform_staff(instance):
            raise serializers.ValidationError({"detail": "No se pudo completar la solicitud."})
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        tw = self.context.get("tenant_workspace")

        if "role" in validated_data:
            profile.role = validated_data["role"]

        if "cover_image" in validated_data:
            profile.cover_image = validated_data["cover_image"]

        if profile.role == UserProfile.Role.CLIENT and client_id_provided:
            if client_id is None:
                profile.client = None
            else:
                try:
                    c = Client.objects.get(pk=client_id)
                except Client.DoesNotExist as exc:
                    raise serializers.ValidationError({"client_id": "Empresa no encontrada."}) from exc
                profile.client = c

        if profile.role == UserProfile.Role.ADMIN:
            profile.client_id = None
            profile.workspace = tw
        elif profile.role == UserProfile.Role.CLIENT:
            if not profile.client_id:
                raise serializers.ValidationError(
                    {"client_id": "Selecciona la empresa para el rol cliente marketplace."}
                )
            profile.workspace_id = profile.client.workspace_id

        profile.full_clean()
        profile.save()

        if profile.role in (UserProfile.Role.CLIENT, UserProfile.Role.ADMIN):
            revoke_django_privileges(instance)

        return instance
