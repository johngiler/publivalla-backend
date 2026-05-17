from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch, Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.models import Client
from apps.clients.utils.notifications import client_has_marketplace_user
from apps.clients.serializers import (
    ClientAdminSerializer,
    MyCompanySerializer,
)
from apps.users.serializers import revoke_django_privileges
from apps.users.views.base_viewsets import AdminModelViewSet
from apps.users.models import UserProfile
from apps.users.utils.password_setup_tokens import build_user_password_setup_token
from apps.users.utils import get_marketplace_client, user_is_admin
from apps.workspaces.tenant import enforce_workspace_for_non_superuser, get_workspace_for_request

User = get_user_model()


class ClientViewSet(AdminModelViewSet):
    """Alta/gestión de clientes (empresa) — solo administradores."""

    serializer_class = ClientAdminSerializer

    def perform_create(self, serializer):
        tw = enforce_workspace_for_non_superuser(
            self.request,
            serializer.validated_data.get("workspace"),
        )
        serializer.save(workspace=tw)

    def perform_update(self, serializer):
        extra = {}
        if "workspace" in serializer.validated_data:
            extra["workspace"] = enforce_workspace_for_non_superuser(
                self.request,
                serializer.validated_data.get("workspace"),
            )
        serializer.save(**extra)

    def get_queryset(self):
        qs = (
            Client.objects.all()
            .order_by("-created_at", "-id")
            .annotate(_orders_count=Count("orders"))
            .prefetch_related(
                Prefetch(
                    "member_profiles",
                    queryset=UserProfile.objects.only("id", "user_id", "client_id"),
                ),
            )
        )
        ws = get_workspace_for_request(self.request)
        if ws is not None:
            qs = qs.filter(workspace=ws)
        if self.action == "list":
            st = self.request.query_params.get("status")
            if st and st != "all":
                qs = qs.filter(status=st)
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(
                    Q(company_name__icontains=search)
                    | Q(rif__icontains=search)
                    | Q(email__icontains=search)
                    | Q(contact_name__icontains=search)
                )
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        n = instance.orders.count()
        if n > 0:
            return Response(
                {
                    "detail": (
                        f"Este cliente tiene {n} pedido(s) relacionado(s). "
                        "Elimina o reasigna esos pedidos antes de borrar la empresa."
                    ),
                    "code": "client_has_orders",
                    "orders_count": n,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="generate-user")
    def generate_user(self, request, pk=None):
        """
        Crea un usuario marketplace (sin contraseña) con el correo de la empresa y lo vincula.
        Respuesta incluye token y datos para armar el enlace `/registro?...` en el front.
        """
        client = self.get_object()
        if client_has_marketplace_user(client):
            return Response(
                {
                    "detail": "Esta empresa ya tiene al menos un usuario vinculado.",
                    "code": "already_linked",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        email = (client.email or "").strip().lower()
        if not email:
            return Response(
                {"detail": "La empresa no tiene correo. Complétalo antes de generar usuario."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            return Response(
                {
                    "detail": "Ya existe un usuario con este correo. Usa la sección Usuarios o otro correo.",
                    "code": "email_taken",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        username = email[: User._meta.get_field("username").max_length]
        user = User(username=username, email=email)
        user.set_unusable_password()
        user.save()
        profile = user.profile
        profile.role = UserProfile.Role.CLIENT
        profile.client = client
        profile.workspace = client.workspace
        profile.full_clean()
        profile.save()
        revoke_django_privileges(user)
        token = build_user_password_setup_token(user.pk)
        q = f"token={quote(token, safe='')}&email={quote(email, safe='')}"
        return Response(
            {
                "user_id": user.id,
                "email": email,
                "token": token,
                "registration_query": q,
            },
            status=status.HTTP_201_CREATED,
        )


class MyCompanyView(APIView):
    """
    Cliente autenticado: crear o actualizar su ficha de empresa (una por usuario).
    Requerido antes de generar órdenes desde el marketplace.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @staticmethod
    def _truthy_remove_company_cover(data):
        return data.get("remove_company_cover") in (True, "true", "1", "on")

    def _serialize_company(self, client, request):
        return Response(ClientAdminSerializer(client, context={"request": request}).data)

    def get(self, request):
        c = get_marketplace_client(request.user)
        if c is None:
            return Response(None, status=status.HTTP_204_NO_CONTENT)
        return self._serialize_company(c, request)

    def post(self, request):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if get_marketplace_client(request.user):
            return Response(
                {"detail": "Ya existe una ficha. Usa PATCH para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = MyCompanySerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        c = ser.save()
        if self._truthy_remove_company_cover(request.data) and "cover_image" not in request.FILES:
            if c.cover_image:
                c.cover_image.delete(save=False)
            c.cover_image = None
            c.save(update_fields=["cover_image"])
        return Response(
            ClientAdminSerializer(c, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request):
        c = get_marketplace_client(request.user)
        if c is None:
            return Response(
                {"detail": "No hay ficha. Crea una con POST."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = MyCompanySerializer(c, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        c.refresh_from_db()
        if self._truthy_remove_company_cover(request.data) and "cover_image" not in request.FILES:
            if c.cover_image:
                c.cover_image.delete(save=False)
            c.cover_image = None
            c.save(update_fields=["cover_image"])
        return self._serialize_company(c, request)
