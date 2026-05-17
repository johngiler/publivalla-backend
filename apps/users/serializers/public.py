from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User, update_last_login
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenObtainSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.settings import api_settings

from apps.users.models import UserProfile
from apps.users.utils import get_user_profile, get_user_role, is_platform_staff
from apps.workspaces.tenant import (
    default_workspace_slug,
    get_workspace_for_request,
    user_can_access_workspace,
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email")


class UserMeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    client_id = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    workspace_slug = serializers.SerializerMethodField()
    workspace_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "client_id",
            "cover_image",
            "workspace_slug",
            "workspace_name",
        )

    def get_role(self, obj):
        return get_user_role(obj)

    def get_client_id(self, obj):
        p = get_user_profile(obj)
        return p.client_id if p and p.client_id else None

    def get_cover_image(self, obj):
        p = get_user_profile(obj)
        if p and p.cover_image:
            return p.cover_image.url
        return None

    def get_workspace_slug(self, obj):
        request = self.context.get("request")
        ws = get_workspace_for_request(request) if request else None
        return ws.slug if ws else None

    def get_workspace_name(self, obj):
        request = self.context.get("request")
        ws = get_workspace_for_request(request) if request else None
        return ws.name if ws else None


class UserMeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    """
    Incluye `role` (y claims de perfil) en cada access token al refrescar,
    para que no quede el rol obsoleto del login anterior.
    """

    def validate(self, attrs: dict[str, Any]) -> dict[str, str]:
        refresh = self.token_class(attrs["refresh"])

        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM, None)
        user = None
        if user_id:
            user = get_user_model().objects.get(
                **{api_settings.USER_ID_FIELD: user_id}
            )
            if not api_settings.USER_AUTHENTICATION_RULE(user):
                raise AuthenticationFailed(
                    self.error_messages["no_active_account"],
                    "no_active_account",
                )

        request = self.context.get("request")
        ws = get_workspace_for_request(request) if request else None
        token_ws = refresh.payload.get("workspace_slug")
        if token_ws is None:
            token_ws = default_workspace_slug()
        if ws is not None and token_ws != ws.slug:
            raise AuthenticationFailed(
                "Sesión no válida. Inicia sesión de nuevo.",
                "token_workspace_mismatch",
            )

        if user is not None and is_platform_staff(user):
            raise AuthenticationFailed(
                "Sesión no válida. Inicia sesión de nuevo.",
                "platform_staff_forbidden",
            )

        access = refresh.access_token
        access["workspace_slug"] = token_ws
        if user is not None:
            access["role"] = get_user_role(user) or "client"
            access["email"] = user.email or ""
            access["username"] = user.username

        data: dict[str, str] = {"access": str(access)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass

            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            refresh.outstand()

            data["refresh"] = str(refresh)

        return data


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    # El mensaje por defecto de Simple JWT (“no hay cuenta activa”) confunde cuando en realidad
    # la clave es incorrecta (authenticate devuelve None en ambos casos).
    default_error_messages = {
        **TokenObtainPairSerializer.default_error_messages,
        "no_active_account": "Usuario o contraseña incorrectos.",
    }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = get_user_role(user) or "client"
        token["email"] = user.email or ""
        token["username"] = user.username
        return token

    def validate(self, attrs: dict[str, Any]) -> dict[str, str]:
        request = self.context.get("request")
        ws = get_workspace_for_request(request) if request else None
        User = get_user_model()
        ident_raw = attrs.get(User.USERNAME_FIELD) or attrs.get("username") or ""
        ident = ident_raw.strip() if isinstance(ident_raw, str) else ""
        if ident:
            candidate = (
                User.objects.filter(username__iexact=ident).first()
                or User.objects.filter(email__iexact=ident).first()
            )
            if (
                candidate is not None
                and not candidate.is_staff
                and not candidate.is_superuser
                and not candidate.has_usable_password()
            ):
                profile = get_user_profile(candidate)
                if (
                    profile is not None
                    and profile.role == UserProfile.Role.CLIENT
                    and profile.client_id is not None
                ):
                    if ws is None or user_can_access_workspace(candidate, ws):
                        raise AuthenticationFailed(
                            "Tu cuenta está creada pero aún no tiene contraseña. "
                            "Usa el enlace de registro que te compartió el administrador "
                            "(página «Definir contraseña») o pídele que te reenvíe el enlace.",
                            "password_not_set",
                        )

        data = TokenObtainSerializer.validate(self, attrs)
        if is_platform_staff(self.user):
            raise AuthenticationFailed(
                self.default_error_messages["no_active_account"],
                "platform_staff_forbidden",
            )
        if ws is not None and not user_can_access_workspace(self.user, ws):
            raise AuthenticationFailed(
                self.default_error_messages["no_active_account"],
                "workspace_forbidden",
            )

        refresh = self.get_token(self.user)
        slug = ws.slug if ws is not None else default_workspace_slug()
        refresh["workspace_slug"] = slug
        refresh.access_token["workspace_slug"] = slug

        data["refresh"] = str(refresh)
        data["access"] = str(refresh.access_token)

        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)

        return data
