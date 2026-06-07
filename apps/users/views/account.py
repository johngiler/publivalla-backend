from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.clients.models import Client
from apps.clients.utils.notifications import (
    client_has_marketplace_user,
    parse_client_activation_token,
)
from apps.users.models import UserProfile
from apps.users.utils.password_policy import marketplace_password_policy_errors
from apps.users.utils.notifications import find_marketplace_user_for_password_reset
from apps.users.utils.password_reset_tokens import parse_user_password_reset_token
from apps.users.utils.password_setup_tokens import (
    build_user_password_setup_token,
    parse_user_password_setup_token,
)
from apps.users.tasks import schedule_send_password_reset_email
from apps.workspaces.tenant import get_workspace_for_request, user_can_access_workspace
from apps.users.serializers import (
    UserMeSerializer,
    UserMeUpdateSerializer,
    revoke_django_privileges,
)
from apps.users.utils import get_user_profile, is_platform_staff

User = get_user_model()


class ValidatePasswordView(APIView):
    """
    Comprueba la contraseña con las mismas reglas que registro / checkout invitado.
    POST { "password": "..." } → 200 { "valid": true } o 400 { "password": ["..."] }.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "validate_password"

    def post(self, request, *args, **kwargs):
        raw = request.data.get("password")
        if raw is not None and not isinstance(raw, str):
            return Response(
                {"password": ["El formato de la contraseña no es válido."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        password = (raw or "").strip()
        if not password:
            return Response(
                {"password": ["Indica una contraseña."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        errs = marketplace_password_policy_errors(password)
        if errs:
            return Response({"password": errs}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"valid": True}, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if is_platform_staff(request.user):
            return Response(
                {"detail": "No autorizado."},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = User.objects.select_related("profile", "profile__client").get(pk=request.user.pk)
        return Response(UserMeSerializer(user, context={"request": request}).data)

    def patch(self, request):
        if is_platform_staff(request.user):
            return Response(
                {"detail": "No autorizado."},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = User.objects.select_related("profile", "profile__client").get(pk=request.user.pk)
        profile, _ = UserProfile.objects.get_or_create(user=user)

        ser = UserMeUpdateSerializer(user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()

        if "cover_image" in request.FILES:
            profile.cover_image = request.FILES["cover_image"]
            profile.save(update_fields=["cover_image"])
        elif request.data.get("remove_cover") in (True, "true", "1", "on"):
            if profile.cover_image:
                profile.cover_image.delete(save=False)
            profile.cover_image = None
            profile.save(update_fields=["cover_image"])

        user.refresh_from_db()
        user = User.objects.select_related("profile").get(pk=user.pk)
        return Response(UserMeSerializer(user, context={"request": request}).data)


class MePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get("old_password") or ""
        new_password = request.data.get("new_password") or ""
        if len(new_password) < 8:
            return Response(
                {"detail": "La nueva contraseña debe tener al menos 8 caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not request.user.check_password(old_password):
            return Response(
                {"detail": "La contraseña actual no es correcta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new_password, user=request.user)
        except DjangoValidationError as e:
            return Response(
                {"detail": " ".join(e.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.set_password(new_password)
        request.user.save()
        return Response({"detail": "Contraseña actualizada."})


class ActivateClientAccountView(APIView):
    """
    Invitado que compró sin cuenta: tras aprobar la orden recibe un enlace firmado.
    POST { token, password } crea el usuario marketplace vinculado a la empresa (Client).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "activate_client"

    def post(self, request, *args, **kwargs):
        token = (request.data.get("token") or "").strip()
        password = (request.data.get("password") or "").strip()
        if not token:
            return Response({"detail": "Falta el token del enlace."}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 8:
            return Response(
                {"detail": "La contraseña debe tener al menos 8 caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            client_id = parse_client_activation_token(token)
        except signing.SignatureExpired:
            return Response(
                {"detail": "El enlace caducó. Solicita uno nuevo al equipo de soporte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)

        client = get_object_or_404(Client, pk=client_id)
        if client_has_marketplace_user(client):
            return Response(
                {
                    "detail": "Esta empresa ya tiene acceso. Inicia sesión con tu correo.",
                    "code": "already_active",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = client.email.strip().lower()
        if not email:
            return Response(
                {"detail": "La ficha de empresa no tiene correo. Contacta a soporte."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(
            email__iexact=email
        ).exists():
            return Response(
                {
                    "detail": "Ya existe un usuario con este correo. Inicia sesión.",
                    "code": "email_taken",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        policy_errs = marketplace_password_policy_errors(password)
        if policy_errs:
            return Response({"password": policy_errs}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(username=email[:150], email=email, password=password)
        profile = user.profile
        profile.role = UserProfile.Role.CLIENT
        profile.client = client
        profile.workspace = client.workspace
        profile.save()
        revoke_django_privileges(user)

        return Response(
            {"detail": "Cuenta creada. Ya puedes iniciar sesión con tu correo y contraseña."},
            status=status.HTTP_201_CREATED,
        )


class PasswordSetupIntentView(APIView):
    """
    GET ?token= — devuelve el correo asociado al enlace de definición de contraseña
    (usuario marketplace sin clave utilizable).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_setup_intent"

    def get(self, request, *args, **kwargs):
        token = (request.query_params.get("token") or "").strip()
        if not token:
            return Response({"detail": "Falta el token."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            uid = parse_user_password_setup_token(token)
        except signing.SignatureExpired:
            return Response(
                {"detail": "El enlace caducó. Solicita uno nuevo al administrador."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(pk=uid, is_staff=False, is_superuser=False).first()
        if user is None or user.has_usable_password():
            return Response(
                {"detail": "Enlace no válido o la cuenta ya tiene contraseña."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = get_user_profile(user)
        if (
            profile is None
            or profile.role != UserProfile.Role.CLIENT
            or profile.client_id is None
        ):
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)

        email = (user.email or user.username or "").strip()
        if not email:
            return Response(
                {"detail": "La cuenta no tiene correo configurado. Contacta a soporte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"email": email})


class SetInitialPasswordView(APIView):
    """
    POST { token, password, password_confirm } — define la primera contraseña para un usuario
    creado sin clave (p. ej. desde «Generar usuario» en clientes).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "set_initial_password"

    def post(self, request, *args, **kwargs):
        token = (request.data.get("token") or "").strip()
        password = (request.data.get("password") or "").strip()
        password_confirm = (request.data.get("password_confirm") or "").strip()
        if not token:
            return Response({"detail": "Falta el token del enlace."}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({"detail": "Indica una contraseña."}, status=status.HTTP_400_BAD_REQUEST)
        if password != password_confirm:
            return Response({"detail": "Las contraseñas no coinciden."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            uid = parse_user_password_setup_token(token)
        except signing.SignatureExpired:
            return Response(
                {"detail": "El enlace caducó. Solicita uno nuevo al administrador."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(pk=uid, is_staff=False, is_superuser=False).first()
        if user is None:
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)
        if user.has_usable_password():
            return Response(
                {
                    "detail": "Esta cuenta ya tiene contraseña. Inicia sesión.",
                    "code": "already_set",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = get_user_profile(user)
        if (
            profile is None
            or profile.role != UserProfile.Role.CLIENT
            or profile.client_id is None
        ):
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)

        policy_errs = marketplace_password_policy_errors(password)
        if policy_errs:
            return Response({"password": policy_errs}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_password(password, user=user)
        except DjangoValidationError as e:
            return Response(
                {"password": list(e.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(password)
        user.save(update_fields=["password"])
        revoke_django_privileges(user)

        return Response(
            {"detail": "Contraseña guardada. Ya puedes iniciar sesión con tu correo y contraseña."},
            status=status.HTTP_200_OK,
        )


PASSWORD_RESET_REQUEST_DETAIL = (
    "Si el correo está registrado, recibirás un enlace para restablecer "
    "tu contraseña en unos minutos."
)


def _password_reset_user_from_token(token: str):
    try:
        uid = parse_user_password_reset_token(token)
    except signing.SignatureExpired:
        return None, "expired"
    except signing.BadSignature:
        return None, "invalid"

    user = User.objects.filter(pk=uid, is_staff=False, is_superuser=False).first()
    if user is None or not user.has_usable_password():
        return None, "invalid"
    profile = get_user_profile(user)
    if profile is None or profile.role not in (
        UserProfile.Role.ADMIN,
        UserProfile.Role.CLIENT,
    ):
        return None, "invalid"
    return user, None


class PasswordResetRequestView(APIView):
    """
    POST { email } — solicita enlace de restablecimiento.
    Respuesta genérica (no revela si el correo existe).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_request"

    def post(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").strip()
        if not email or "@" not in email:
            return Response(
                {"detail": "Indica un correo válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ws = get_workspace_for_request(request)
        user = find_marketplace_user_for_password_reset(email, ws)
        if user is not None:
            schedule_send_password_reset_email(user.pk)

        return Response({"detail": PASSWORD_RESET_REQUEST_DETAIL})


class PasswordResetIntentView(APIView):
    """GET ?token= — correo asociado al enlace de restablecimiento."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_intent"

    def get(self, request, *args, **kwargs):
        token = (request.query_params.get("token") or "").strip()
        if not token:
            return Response({"detail": "Falta el token."}, status=status.HTTP_400_BAD_REQUEST)

        user, err = _password_reset_user_from_token(token)
        if err == "expired":
            return Response(
                {"detail": "El enlace caducó. Solicita uno nuevo desde «Olvidé mi contraseña»."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user is None:
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)

        ws = get_workspace_for_request(request)
        if ws is not None and not user_can_access_workspace(user, ws):
            return Response(
                {"detail": "Este enlace no corresponde a este marketplace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = (user.email or user.username or "").strip()
        if not email:
            return Response(
                {"detail": "La cuenta no tiene correo configurado. Contacta a soporte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"email": email})


class PasswordResetConfirmView(APIView):
    """POST { token, password, password_confirm } — nueva contraseña."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_confirm"

    def post(self, request, *args, **kwargs):
        token = (request.data.get("token") or "").strip()
        password = (request.data.get("password") or "").strip()
        password_confirm = (request.data.get("password_confirm") or "").strip()
        if not token:
            return Response({"detail": "Falta el token del enlace."}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({"detail": "Indica una contraseña."}, status=status.HTTP_400_BAD_REQUEST)
        if password != password_confirm:
            return Response({"detail": "Las contraseñas no coinciden."}, status=status.HTTP_400_BAD_REQUEST)

        user, err = _password_reset_user_from_token(token)
        if err == "expired":
            return Response(
                {"detail": "El enlace caducó. Solicita uno nuevo desde «Olvidé mi contraseña»."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user is None:
            return Response({"detail": "Enlace no válido."}, status=status.HTTP_400_BAD_REQUEST)

        ws = get_workspace_for_request(request)
        if ws is not None and not user_can_access_workspace(user, ws):
            return Response(
                {"detail": "Este enlace no corresponde a este marketplace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        policy_errs = marketplace_password_policy_errors(password)
        if policy_errs:
            return Response({"password": policy_errs}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_password(password, user=user)
        except DjangoValidationError as e:
            return Response(
                {"password": list(e.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(password)
        user.save(update_fields=["password"])
        revoke_django_privileges(user)

        return Response(
            {
                "detail": (
                    "Contraseña actualizada. Ya puedes iniciar sesión con tu correo "
                    "y la nueva contraseña."
                )
            },
            status=status.HTTP_200_OK,
        )
