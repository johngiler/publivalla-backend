from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.utils import is_platform_staff, user_is_admin
from apps.workspaces.serializers import (
    WorkspaceMeReadSerializer,
    WorkspaceMeUpdateSerializer,
    WorkspacePublicSerializer,
)
from apps.workspaces.tenant import get_workspace_for_request


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
