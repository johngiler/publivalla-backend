"""Marcas de la empresa del cliente autenticado (Mi empresa)."""

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.models import ClientBrand
from apps.clients.serializers import ClientBrandSerializer
from apps.users.utils import get_marketplace_client, user_is_admin


def _client_brand_for_user(user, brand_id: int) -> ClientBrand | None:
    client = get_marketplace_client(user)
    if client is None:
        return None
    return (
        ClientBrand.objects.filter(pk=brand_id, client_id=client.pk, is_active=True)
        .select_related("client")
        .first()
    )


class MyCompanyBrandListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

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
        rows = ClientBrand.objects.filter(client=client, is_active=True).order_by(
            "name", "id"
        )
        ser = ClientBrandSerializer(rows, many=True, context={"request": request})
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
        ser = ClientBrandSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        if ClientBrand.objects.filter(
            client=client, name__iexact=ser.validated_data["name"]
        ).exists():
            return Response(
                {"name": "Ya existe una marca con ese nombre."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        brand = ClientBrand.objects.create(client=client, **ser.validated_data)
        return Response(
            ClientBrandSerializer(brand, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MyCompanyBrandDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @staticmethod
    def _truthy_remove_logo(data):
        return data.get("remove_logo") in (True, "true", "1", "on")

    def patch(self, request, brand_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        brand = _client_brand_for_user(request.user, brand_id)
        if brand is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = ClientBrandSerializer(
            brand,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        ser.is_valid(raise_exception=True)
        new_name = ser.validated_data.get("name")
        if new_name is not None and new_name.lower() != brand.name.lower():
            if (
                ClientBrand.objects.filter(client_id=brand.client_id, name__iexact=new_name)
                .exclude(pk=brand.pk)
                .exists()
            ):
                return Response(
                    {"name": "Ya existe una marca con ese nombre."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        ser.save()
        brand.refresh_from_db()
        if self._truthy_remove_logo(request.data) and "logo" not in request.FILES:
            if brand.logo:
                brand.logo.delete(save=False)
            brand.logo = None
            brand.save(update_fields=["logo", "updated_at"])
        return Response(ClientBrandSerializer(brand, context={"request": request}).data)

    def delete(self, request, brand_id: int):
        if user_is_admin(request.user):
            return Response(
                {"detail": "Esta acción no está disponible para tu cuenta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        brand = _client_brand_for_user(request.user, brand_id)
        if brand is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if brand.logo:
            brand.logo.delete(save=False)
        brand.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
