from urllib.parse import quote

from django.contrib.auth.models import User
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.users.serializers import (
    UserAdminCreateSerializer,
    UserAdminSerializer,
    UserAdminUpdateSerializer,
)
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.users.models import UserProfile
from apps.users.utils.password_setup_tokens import build_user_password_setup_token
from apps.users.utils import get_user_profile
from apps.workspaces.tenant import get_workspace_for_request


class UserAdminViewSet(AdminModelViewSet):
    """Listado y gestión de usuarios del marketplace (solo admin)."""

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["tenant_workspace"] = get_workspace_for_request(self.request)
        return ctx

    def get_queryset(self):
        # Solo cuentas de marketplace (niveles 2 y 3); no operadores Django (nivel 1).
        qs = (
            User.objects.select_related("profile", "profile__client")
            .filter(is_staff=False, is_superuser=False)
            .order_by("-date_joined", "-id")
        )
        ws = get_workspace_for_request(self.request)
        if ws is None:
            # Sin tenant resuelto no debe listarse nadie (evita filtrar por todos los owners).
            return qs.none()
        qs = qs.filter(
            Q(profile__workspace=ws) | Q(profile__client__workspace=ws)
        ).distinct()
        if self.action == "list":
            role = self.request.query_params.get("role")
            if role and role != "all":
                qs = qs.filter(profile__role=role)
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(username__icontains=search)
                    | Q(email__icontains=search)
                    | Q(first_name__icontains=search)
                    | Q(last_name__icontains=search)
                    | Q(profile__client__company_name__icontains=search)
                )
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return UserAdminCreateSerializer
        if self.action in ("partial_update", "update"):
            return UserAdminUpdateSerializer
        return UserAdminSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        out = UserAdminSerializer(user, context=self.get_serializer_context())
        headers = self.get_success_headers(out.data)
        return Response(out.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserAdminSerializer(user, context=self.get_serializer_context()).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.pk == request.user.pk:
            return Response(
                {"detail": "No puedes eliminar tu propio usuario."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="password-setup-link")
    def password_setup_link(self, request, pk=None):
        """Devuelve token y query string para copiar el enlace a /registro (usuario sin contraseña)."""
        user = self.get_object()
        if user.has_usable_password():
            return Response(
                {"detail": "Este usuario ya tiene contraseña."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = get_user_profile(user)
        if (
            profile is None
            or profile.role != UserProfile.Role.CLIENT
            or profile.client_id is None
        ):
            return Response(
                {
                    "detail": "Solo aplica a clientes marketplace pendientes de definir contraseña.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        email = (user.email or user.username or "").strip()
        if not email:
            return Response(
                {"detail": "El usuario no tiene correo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        token = build_user_password_setup_token(user.pk)
        q = f"token={quote(token, safe='')}&email={quote(email, safe='')}"
        return Response({"token": token, "email": email, "registration_query": q})
