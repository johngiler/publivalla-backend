import logging

from django.conf import settings as django_settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.utils import is_platform_staff, user_is_admin
from apps.workspaces.serializers import (
    WorkspaceMeReadSerializer,
    WorkspaceMeUpdateSerializer,
    WorkspacePublicSerializer,
    WorkspaceTransactionalSmtpTestSerializer,
)
from apps.workspaces.smtp_test import run_transactional_smtp_connection_test
from apps.workspaces.mailgun_test import run_transactional_mailgun_auth_test
from apps.workspaces.tenant import get_workspace_for_request

logger = logging.getLogger(__name__)


def _truthy_form_value(val) -> bool:
    return val in (True, "true", "1", "on", "True")


def _resolve_admin_editable_workspace(request):
    """
    Workspace del perfil admin, alineado con el tenant de la petición (Host / Origin).
    """
    user = request.user
    if not user.is_authenticated:
        return None, status.HTTP_401_UNAUTHORIZED, {"detail": "Autenticación requerida."}
    if is_platform_staff(user):
        return None, status.HTTP_403_FORBIDDEN, {"detail": "No autorizado."}
    if not user_is_admin(user):
        return None, status.HTTP_403_FORBIDDEN, {
            "detail": "Solo los administradores del marketplace pueden consultar o editar estos datos.",
        }
    profile = getattr(user, "profile", None)
    ws = profile.workspace if profile else None
    if ws is None:
        return None, status.HTTP_403_FORBIDDEN, {"detail": "Tu cuenta no tiene un workspace asignado."}
    resolved = get_workspace_for_request(request)
    if resolved is None or resolved.pk != ws.pk:
        return None, status.HTTP_403_FORBIDDEN, {
            "detail": "El workspace del sitio no coincide con el de tu cuenta.",
        }
    return ws, None, None


class WorkspaceCurrentView(APIView):
    """
    Datos públicos del owner (Workspace) según Host / Origin de la petición.
    El front usa esto para marca, título y colores sin acoplar nombres fijos.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        ws = get_workspace_for_request(request)
        if ws is None:
            return Response(
                {"detail": "No hay workspace para este contexto."},
                status=404,
            )
        ser = WorkspacePublicSerializer(ws, context={"request": request})
        return Response(ser.data)


class MyWorkspaceView(APIView):
    """
    GET/PATCH del Workspace (owner) para el administrador marketplace del mismo tenant.
    El slug no se puede cambiar: rechazado si viene en el cuerpo.
    Archivos: multipart con campos `logo`, `logo_mark`, `favicon` o `remove_*`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ws, code, body = _resolve_admin_editable_workspace(request)
        if code is not None:
            return Response(body, status=code)
        ser = WorkspaceMeReadSerializer(ws, context={"request": request})
        return Response(ser.data)

    def patch(self, request):
        ws, code, body = _resolve_admin_editable_workspace(request)
        if code is not None:
            return Response(body, status=code)
        if "slug" in request.data:
            return Response(
                {"slug": ["El identificador (slug) no se puede modificar desde aquí."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = WorkspaceMeUpdateSerializer(ws, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()

        if "transactional_email_password" in request.data:
            raw = request.data.get("transactional_email_password")
            ws.transactional_email_password = (str(raw).strip() if raw is not None else "")
            ws.save(update_fields=["transactional_email_password"])

        if "transactional_email_api_key" in request.data:
            raw = request.data.get("transactional_email_api_key")
            ws.transactional_email_api_key = (str(raw).strip() if raw is not None else "")
            ws.save(update_fields=["transactional_email_api_key"])

        if "logo" in request.FILES:
            ws.logo = request.FILES["logo"]
        if _truthy_form_value(request.data.get("remove_logo")):
            if ws.logo:
                ws.logo.delete(save=False)
            ws.logo = None

        if "logo_mark" in request.FILES:
            ws.logo_mark = request.FILES["logo_mark"]
        if _truthy_form_value(request.data.get("remove_logo_mark")):
            if ws.logo_mark:
                ws.logo_mark.delete(save=False)
            ws.logo_mark = None

        if "favicon" in request.FILES:
            ws.favicon = request.FILES["favicon"]
        if _truthy_form_value(request.data.get("remove_favicon")):
            if ws.favicon:
                ws.favicon.delete(save=False)
            ws.favicon = None

        ws.save()
        ws.refresh_from_db()
        out = WorkspaceMeReadSerializer(ws, context={"request": request})
        return Response(out.data)


class MyWorkspaceTransactionalSmtpTestView(APIView):
    """
    POST: prueba conexión y autenticación SMTP (sin guardar ni enviar correo).

    - Con worker Celery (CELERY_TASK_ALWAYS_EAGER=False): 202 { queued, task_id }; el resultado se consulta en GET …/status/<task_id>/.
    - Modo eager (p. ej. sin broker): 200 { ok, detail, technical } en la misma respuesta.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ws, code, body = _resolve_admin_editable_workspace(request)
        if code is not None:
            return Response(body, status=code)
        ser = WorkspaceTransactionalSmtpTestSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        d = ser.validated_data
        password = (d.get("transactional_email_password") or "").strip()
        if not password:
            password = (ws.transactional_email_password or "").strip()
        if not password:
            return Response(
                {
                    "ok": False,
                    "detail": "Indica la contraseña SMTP en el formulario o guarda una contraseña en Mi negocio antes de probar.",
                    "technical": None,
                },
                status=status.HTTP_200_OK,
            )
        kwargs = dict(
            host=(d["transactional_email_host"] or "").strip(),
            port=int(d["transactional_email_port"]),
            username=(d.get("transactional_email_username") or "").strip(),
            password=password,
            use_tls=bool(d["transactional_email_use_tls"]),
            use_ssl=bool(d["transactional_email_use_ssl"]),
        )
        if getattr(django_settings, "CELERY_TASK_ALWAYS_EAGER", True):
            result = run_transactional_smtp_connection_test(**kwargs)
            return Response(result, status=status.HTTP_200_OK)
        try:
            from apps.workspaces.tasks import workspace_smtp_connection_test_task

            ar = workspace_smtp_connection_test_task.delay(**kwargs)
            return Response(
                {"queued": True, "task_id": ar.id},
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception:
            logger.exception("No se pudo encolar la prueba SMTP; se ejecuta en línea.")
            result = run_transactional_smtp_connection_test(**kwargs)
            return Response(result, status=status.HTTP_200_OK)


class MyWorkspaceTransactionalSmtpTestStatusView(APIView):
    """GET: estado/resultado de una prueba SMTP encolada (task_id devuelto en el POST 202)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, task_id: str):
        ws, code, body = _resolve_admin_editable_workspace(request)
        if code is not None:
            return Response(body, status=code)
        if not (task_id or "").strip():
            return Response({"detail": "task_id inválido."}, status=status.HTTP_400_BAD_REQUEST)
        from celery.result import AsyncResult

        r = AsyncResult(task_id.strip())
        if not r.ready():
            return Response({"ready": False, "state": r.state})
        if r.failed():
            err = r.result
            tech = repr(err) if err is not None else ""
            if isinstance(err, BaseException):
                tech = str(err)
            return Response(
                {
                    "ready": True,
                    "ok": False,
                    "detail": "La prueba SMTP falló en el worker.",
                    "technical": tech or None,
                },
                status=status.HTTP_200_OK,
            )
        payload = r.result
        if isinstance(payload, dict):
            return Response({"ready": True, **payload}, status=status.HTTP_200_OK)
        return Response(
            {
                "ready": True,
                "ok": False,
                "detail": "Respuesta inesperada del worker.",
                "technical": str(payload),
            },
            status=status.HTTP_200_OK,
        )


class MyWorkspaceTransactionalRelayTestView(APIView):
    """
    POST: prueba credenciales del relay transaccional elegido (SMTP o API key).
    No envía correo.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ws, code, body = _resolve_admin_editable_workspace(request)
        if code is not None:
            return Response(body, status=code)

        d = request.data if isinstance(request.data, dict) else {}
        method = (
            (d.get("transactional_email_method") or ws.transactional_email_method or "smtp")
            .strip()
            .lower()
        )
        if method != "api":
            return MyWorkspaceTransactionalSmtpTestView().post(request)

        provider = (
            (d.get("transactional_email_provider") or ws.transactional_email_provider or "mailgun")
            .strip()
            .lower()
        )
        if provider != "mailgun":
            return Response({"detail": "Proveedor no soportado."}, status=status.HTTP_400_BAD_REQUEST)

        api_key = (d.get("transactional_email_api_key") or "").strip() or (
            ws.transactional_email_api_key or ""
        ).strip()
        domain = (d.get("transactional_email_mailgun_domain") or "").strip() or (
            ws.transactional_email_mailgun_domain or ""
        ).strip()
        region = (d.get("transactional_email_mailgun_region") or "").strip() or (
            ws.transactional_email_mailgun_region or "us"
        ).strip()

        result = run_transactional_mailgun_auth_test(api_key=api_key, domain=domain, region=region)
        return Response(result, status=status.HTTP_200_OK)
