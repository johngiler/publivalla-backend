"""Usuarios de la empresa del cliente autenticado (Mi empresa)."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Prefetch

from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.models import ClientMemberBrand
from apps.clients.serializers import (
    CompanyMemberCreateSerializer,
    CompanyMemberSerializer,
    CompanyMemberUpdateSerializer,
)
from apps.clients.utils.marketplace_user import (
    MarketplaceUserError,
    create_marketplace_member_user,
    set_member_brand_ids,
)
from apps.users.models import UserProfile
from apps.users.tasks import schedule_notify_marketplace_client_user_created
from apps.users.utils import get_marketplace_client, user_is_admin

User = get_user_model()


def _member_profiles_queryset(client):
    brand_links_qs = ClientMemberBrand.objects.select_related("brand").filter(
        brand__is_active=True
    )
    return (
        UserProfile.objects.filter(
            client=client,
            role=UserProfile.Role.CLIENT,
        )
        .select_related("user")
        .prefetch_related(Prefetch("brand_links", queryset=brand_links_qs))
        .order_by("user__first_name", "user__last_name", "user__email", "user_id")
    )


def _member_profile_for_user(actor, member_user_id: int) -> UserProfile | None:
    client = get_marketplace_client(actor)
    if client is None:
        return None
    return (
        _member_profiles_queryset(client)
        .filter(user_id=member_user_id)
        .first()
    )


class MyCompanyMemberListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "Registra primero la ficha de tu empresa."},
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = _member_profiles_queryset(client)
        ser = CompanyMemberSerializer(rows, many=True, context={"request": request})
        return Response(ser.data)

    def post(self, request):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client = get_marketplace_client(request.user)
        if client is None:
            return Response(
                {"detail": "Registra primero la ficha de tu empresa."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ser = CompanyMemberCreateSerializer(
            data=request.data,
            context={"request": request, "client": client},
        )
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            user = create_marketplace_member_user(
                client,
                email=data["email"],
                first_name=data.get("first_name") or "",
                last_name=data.get("last_name") or "",
                brand_ids=data.get("brand_ids"),
            )
        except MarketplaceUserError as exc:
            payload = {"detail": exc.message}
            if exc.code == "email_taken":
                payload = {"email": exc.message}
            if exc.code == "missing_email":
                payload = {"email": exc.message}
            if exc.code == "invalid_brands":
                payload = {"brand_ids": exc.message}
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        uid = user.pk

        def _notify() -> None:
            schedule_notify_marketplace_client_user_created(uid)

        transaction.on_commit(_notify)

        profile = _member_profile_for_user(request.user, user.pk)
        return Response(
            CompanyMemberSerializer(profile, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MyCompanyMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def patch(self, request, member_user_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = _member_profile_for_user(request.user, member_user_id)
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = CompanyMemberUpdateSerializer(
            data=request.data,
            partial=True,
            context={"request": request, "profile": profile},
        )
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        user = profile.user
        update_fields: list[str] = []
        if "first_name" in data:
            user.first_name = (data["first_name"] or "").strip()
            update_fields.append("first_name")
        if "last_name" in data:
            user.last_name = (data["last_name"] or "").strip()
            update_fields.append("last_name")
        if update_fields:
            user.save(update_fields=update_fields)
        if "brand_ids" in data:
            try:
                set_member_brand_ids(profile, data["brand_ids"])
            except MarketplaceUserError as exc:
                return Response(
                    {"brand_ids": exc.message},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        profile = _member_profile_for_user(request.user, member_user_id)
        return Response(
            CompanyMemberSerializer(profile, context={"request": request}).data,
        )

    def delete(self, request, member_user_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.user.pk == member_user_id:
            return Response(
                {"detail": "No puedes eliminar tu propia cuenta desde aquí."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = _member_profile_for_user(request.user, member_user_id)
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        user = profile.user
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
