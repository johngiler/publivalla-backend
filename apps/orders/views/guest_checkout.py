"""Checkout sin sesión: crea empresa (Client), orden enviada y opcionalmente usuario marketplace."""

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.common.utils.catalog_access import shopping_center_allows_public_catalog
from apps.clients.models import Client, ClientStatus
from apps.orders.models import Order, OrderItem, OrderPaymentMethod, OrderStatus
from apps.orders.serializers import OrderItemWriteSerializer, OrderSerializer
from apps.orders.services import log_order_status_transition, submit_draft_order
from apps.users.serializers import revoke_django_privileges
from apps.users.models import UserProfile
from apps.users.utils.password_policy import marketplace_password_policy_errors
from apps.workspaces.tenant import get_workspace_for_request

User = get_user_model()


class GuestCheckoutEmailCheckSerializer(serializers.Serializer):
    email = serializers.EmailField()


class GuestCheckoutEmailCheckView(APIView):
    """
    POST público: indica si el correo está libre para «crear cuenta al comprar»
    (misma regla que GuestCheckoutView al crear usuario).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "guest_checkout_email"

    def post(self, request, *args, **kwargs):
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response(
                {
                    "detail": "No se identificó el espacio de trabajo. Usa el subdominio o la cabecera del tenant.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = GuestCheckoutEmailCheckSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        taken = User.objects.filter(username__iexact=email).exists() or User.objects.filter(
            email__iexact=email
        ).exists()
        if taken:
            return Response(
                {
                    "available": False,
                    "detail": "Ya existe un usuario con este correo. Inicia sesión o usa otro email.",
                    "code": "email_taken",
                },
                status=status.HTTP_200_OK,
            )
        return Response({"available": True}, status=status.HTTP_200_OK)


class GuestCheckoutClientEmailCheckView(APIView):
    """
    POST público: indica si el correo ya corresponde a un Client en el workspace
    y si ese cliente ya tiene usuario marketplace (debe iniciar sesión).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "guest_checkout_email"

    def post(self, request, *args, **kwargs):
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response(
                {
                    "detail": "No se identificó el espacio de trabajo. Usa el subdominio o la cabecera del tenant.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = GuestCheckoutEmailCheckSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        client = Client.objects.filter(workspace=ws, email__iexact=email).order_by("id").first()
        if client is None:
            return Response(
                {
                    "client_exists": False,
                    "has_marketplace_account": False,
                },
                status=status.HTTP_200_OK,
            )
        has_account = UserProfile.objects.filter(
            client=client,
            role=UserProfile.Role.CLIENT,
        ).exists()
        return Response(
            {
                "client_exists": True,
                "has_marketplace_account": has_account,
            },
            status=status.HTTP_200_OK,
        )


class GuestCheckoutDatosValidateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    company_name = serializers.CharField(max_length=255)

    def validate_company_name(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError("Indica el nombre de la empresa.")
        return s


class GuestCheckoutDatosValidateView(APIView):
    """
    POST público: valida correo y razón social frente a Clientes del workspace
    (una sola petición al pulsar «Continuar» en datos del checkout invitado).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "guest_checkout_email"

    @staticmethod
    def _client_flags(client):
        if client is None:
            return {"client_exists": False, "has_marketplace_account": False}
        has_account = UserProfile.objects.filter(
            client=client,
            role=UserProfile.Role.CLIENT,
        ).exists()
        return {"client_exists": True, "has_marketplace_account": has_account}

    def post(self, request, *args, **kwargs):
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response(
                {
                    "detail": "No se identificó el espacio de trabajo. Usa el subdominio o la cabecera del tenant.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = GuestCheckoutDatosValidateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        company_name = ser.validated_data["company_name"].strip()

        client_by_email = Client.objects.filter(workspace=ws, email__iexact=email).order_by("id").first()
        client_by_company = Client.objects.filter(
            workspace=ws, company_name__iexact=company_name
        ).order_by("id").first()

        email_flags = self._client_flags(client_by_email)
        company_flags = self._client_flags(client_by_company)
        same_client = (
            client_by_email is not None
            and client_by_company is not None
            and client_by_email.pk == client_by_company.pk
        )

        return Response(
            {
                "email": email_flags,
                "company": company_flags,
                "same_client": same_client,
            },
            status=status.HTTP_200_OK,
        )


class GuestCheckoutSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    contact_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=32)
    address = serializers.CharField(allow_blank=True, default="", required=False)
    city = serializers.CharField(allow_blank=True, default="", max_length=120, required=False)
    create_account = serializers.BooleanField(default=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    items = OrderItemWriteSerializer(many=True)
    payment_method = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Agrega al menos una toma.")
        from apps.orders.utils.validators import order_request_items_have_internal_overlap

        if order_request_items_have_internal_overlap(value):
            raise serializers.ValidationError(
                "Las fechas de una misma toma no pueden solaparse en el pedido."
            )
        return value

    def validate_company_name(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError("Indica el nombre de la empresa.")
        return s

    def validate_contact_name(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError("Indica el nombre de contacto.")
        return s

    def validate_phone(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError("Indica un teléfono de contacto.")
        return s

    def validate_payment_method(self, value):
        v = (value or "").strip()
        if not v:
            return ""
        valid = {c[0] for c in OrderPaymentMethod.choices}
        if v not in valid:
            raise serializers.ValidationError("Método de pago no válido.")
        return v

    def validate(self, attrs):
        if attrs.get("create_account"):
            p1 = (attrs.get("password") or "").strip()
            p2 = (attrs.get("password_confirm") or "").strip()
            if p1 != p2:
                raise serializers.ValidationError(
                    {"password_confirm": "Las contraseñas no coinciden."}
                )
            policy_errs = marketplace_password_policy_errors(p1)
            if policy_errs:
                raise serializers.ValidationError({"password": policy_errs})
            attrs["_password"] = p1
        return attrs


class GuestCheckoutView(APIView):
    """
    POST público: datos de empresa + líneas del carrito.
    Crea o actualiza Client por correo en el workspace (sin duplicar por email).
    Si ese cliente ya tiene usuario marketplace, se pide iniciar sesión.
    Genera orden enviada. Opcionalmente crea usuario con contraseña (crear cuenta al comprar).

    Cuerpo JSON (comportamiento anterior) o multipart/form-data con:
    - ``payload``: cadena JSON con los mismos campos que el POST JSON (incl. ``payment_method`` opcional).
    - ``payment_receipt``: archivo opcional (imagen o PDF).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "guest_checkout"
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response(
                {
                    "detail": "No se identificó el espacio de trabajo. Usa el subdominio o la cabecera del tenant.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload_in = request.data
        content_type = (request.content_type or "").lower()
        if "multipart/form-data" in content_type:
            raw = request.data.get("payload")
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                return Response(
                    {
                        "detail": "Con archivo o multipart, envía el cuerpo del checkout en el campo «payload» (JSON).",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                payload_in = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, json.JSONDecodeError):
                return Response(
                    {"detail": "El campo «payload» debe ser JSON válido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        ser = GuestCheckoutSerializer(data=payload_in)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        email = data["email"].strip().lower()
        company_name = data["company_name"].strip()
        contact_name = data["contact_name"].strip()
        phone = data["phone"].strip()

        items_data = data["items"]
        for row in items_data:
            sc = row["ad_space"].shopping_center
            if not shopping_center_allows_public_catalog(sc):
                return Response(
                    {
                        "detail": f"La toma {row['ad_space'].code} no está disponible en el marketplace público.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if sc.workspace_id != ws.id:
                return Response(
                    {
                        "detail": f"La toma {row['ad_space'].code} no pertenece a este sitio.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        client = Client.objects.filter(workspace=ws, email__iexact=email).order_by("id").first()

        if client is not None:
            if UserProfile.objects.filter(client=client, role=UserProfile.Role.CLIENT).exists():
                return Response(
                    {
                        "detail": "Este correo ya está asociado a una cuenta del marketplace. Inicia sesión para completar la reserva.",
                        "code": "client_email_has_account",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            client.company_name = company_name
            client.contact_name = contact_name
            client.email = email
            client.phone = phone
            client.address = (data.get("address") or "").strip()
            client.city = (data.get("city") or "").strip()
            client.save()
        else:
            client = Client.objects.create(
                workspace=ws,
                company_name=company_name,
                rif=None,
                contact_name=contact_name,
                email=email,
                phone=phone,
                address=(data.get("address") or "").strip(),
                city=(data.get("city") or "").strip(),
                status=ClientStatus.ACTIVE,
            )

        if data.get("create_account"):
            if User.objects.filter(username__iexact=email).exists() or User.objects.filter(
                email__iexact=email
            ).exists():
                return Response(
                    {
                        "detail": "Ya existe un usuario con este correo. Inicia sesión o usa otro email.",
                        "code": "email_taken",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    client=client,
                    status=OrderStatus.DRAFT,
                    total_amount=Decimal("0"),
                )
                total = Decimal("0")
                for row in items_data:
                    OrderItem.objects.create(
                        order=order,
                        ad_space=row["ad_space"],
                        start_date=row["start_date"],
                        end_date=row["end_date"],
                        monthly_price=row["_monthly_price"],
                        subtotal=row["_subtotal"],
                    )
                    total += row["_subtotal"]
                order.total_amount = total.quantize(Decimal("0.01"))
                order.save(update_fields=["total_amount"])

                log_order_status_transition(
                    order,
                    "",
                    OrderStatus.DRAFT,
                    actor=None,
                    note="Orden creada (checkout invitado, borrador).",
                )

                actor_user = None
                if data.get("create_account"):
                    pwd = data["_password"]
                    uname = email[:150]
                    user = User.objects.create_user(username=uname, email=email, password=pwd)
                    profile = user.profile
                    profile.role = UserProfile.Role.CLIENT
                    profile.client = client
                    profile.workspace = ws
                    profile.save()
                    revoke_django_privileges(user)
                    actor_user = user

                submit_draft_order(order, actor=actor_user)
        except serializers.ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        order.refresh_from_db()
        return Response(
            OrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
