"""Correos transaccionales de usuarios marketplace (alta admin, recuperar contraseña)."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from apps.orders.utils.email_notifications import send_workspace_transactional_email
from apps.clients.utils.marketplace_user import build_client_password_setup_url
from apps.orders.utils.transactional_email_templates import (
    build_admin_welcome_transactional_email,
    build_client_marketplace_welcome_transactional_email,
    build_password_reset_transactional_email,
)
from apps.users.models import UserProfile
from apps.users.utils import get_user_profile
from apps.users.utils.password_reset_tokens import build_user_password_reset_token
from apps.workspaces.models import Workspace
from apps.workspaces.tenant import spa_public_base_url, user_can_access_workspace

logger = logging.getLogger(__name__)

User = get_user_model()


def find_marketplace_user_for_password_reset(email: str, workspace: Workspace | None):
    """Usuario marketplace con correo y contraseña utilizable en el tenant de la petición."""
    addr = (email or "").strip()
    if not addr or "@" not in addr:
        return None
    qs = User.objects.filter(
        is_staff=False,
        is_superuser=False,
        email__iexact=addr,
    ).select_related("profile", "profile__client")
    for user in qs.iterator():
        if not user.has_usable_password():
            continue
        profile = get_user_profile(user)
        if profile is None or profile.role not in (
            UserProfile.Role.ADMIN,
            UserProfile.Role.CLIENT,
        ):
            continue
        if workspace is not None and not user_can_access_workspace(user, workspace):
            continue
        return user
    return None


def _workspace_for_user(user) -> Workspace | None:
    profile = get_user_profile(user)
    if profile is None:
        return None
    if profile.role == UserProfile.Role.ADMIN:
        return profile.workspace
    if profile.role == UserProfile.Role.CLIENT and profile.client_id:
        return getattr(profile.client, "workspace", None)
    return None


def build_password_reset_url(*, user, workspace: Workspace | None) -> str:
    base = spa_public_base_url(workspace)
    token = build_user_password_reset_token(user.pk)
    return f"{base}/restablecer-contrasena?token={token}"


def notify_marketplace_admin_user_created(user_id: int) -> None:
    """Correo al nuevo administrador marketplace (alta o promoción a admin)."""
    user = (
        User.objects.filter(pk=user_id, is_staff=False, is_superuser=False)
        .select_related("profile")
        .first()
    )
    if user is None:
        return
    profile = get_user_profile(user)
    if profile is None or profile.role != UserProfile.Role.ADMIN:
        return
    to_addr = (user.email or "").strip()
    if not to_addr:
        logger.warning(
            "No se envió correo de alta admin: usuario %s sin correo.",
            user.pk,
        )
        return

    ws = profile.workspace
    if ws is None:
        logger.warning(
            "No se envió correo de alta admin: usuario %s sin workspace.",
            user.pk,
        )
        return

    marketplace = (ws.marketplace_title or ws.name or "").strip() or (ws.slug or "")
    accent = (getattr(ws, "primary_color", None) or "").strip() or None
    login_url = f"{spa_public_base_url(ws)}/login"
    display_name = (user.get_full_name() or user.username or "").strip()
    login_email = (user.email or user.username or "").strip().lower()

    subject, body, html_body, inline_logo = build_admin_welcome_transactional_email(
        marketplace_title=marketplace,
        contact_name=display_name,
        login_email=login_email,
        login_url=login_url,
        accent_hex=accent,
        workspace=ws,
    )

    if not send_workspace_transactional_email(
        ws,
        to_emails=[to_addr],
        subject=subject,
        body=body,
        html_body=html_body,
        inline_logo=inline_logo,
    ):
        logger.warning(
            "No se envió correo de alta admin para usuario %s. "
            "Configura el envío de correo en Mi negocio.",
            user.pk,
        )


def notify_marketplace_client_user_created(user_id: int) -> None:
    """Correo al nuevo usuario cliente marketplace (alta manual o «Generar usuario»)."""
    user = (
        User.objects.filter(pk=user_id, is_staff=False, is_superuser=False)
        .select_related("profile", "profile__client", "profile__client__workspace")
        .first()
    )
    if user is None:
        return
    profile = get_user_profile(user)
    if profile is None or profile.role != UserProfile.Role.CLIENT or profile.client_id is None:
        return

    client = profile.client
    to_addr = (user.email or client.email or "").strip()
    if not to_addr:
        logger.warning(
            "No se envió correo de alta cliente: usuario %s sin correo.",
            user.pk,
        )
        return

    ws = client.workspace
    if ws is None:
        logger.warning(
            "No se envió correo de alta cliente: usuario %s sin workspace.",
            user.pk,
        )
        return

    marketplace = (ws.marketplace_title or ws.name or "").strip() or (ws.slug or "")
    accent = (getattr(ws, "primary_color", None) or "").strip() or None
    display_name = (user.get_full_name() or client.contact_name or "").strip()
    login_email = (user.email or user.username or to_addr).strip().lower()
    company_name = (client.company_name or "").strip()
    needs_setup = not user.has_usable_password()

    if needs_setup:
        action_url = build_client_password_setup_url(client=client, user=user)
        action_label = "Crear contraseña"
    else:
        action_url = f"{spa_public_base_url(ws)}/login"
        action_label = "Iniciar sesión"

    subject, body, html_body, inline_logo = build_client_marketplace_welcome_transactional_email(
        marketplace_title=marketplace,
        company_name=company_name,
        contact_name=display_name,
        login_email=login_email,
        action_url=action_url,
        action_label=action_label,
        needs_password_setup=needs_setup,
        accent_hex=accent,
        workspace=ws,
    )

    if not send_workspace_transactional_email(
        ws,
        to_emails=[to_addr],
        subject=subject,
        body=body,
        html_body=html_body,
        inline_logo=inline_logo,
    ):
        logger.warning(
            "No se envió correo de alta cliente para usuario %s. "
            "Configura el envío de correo en Mi negocio.",
            user.pk,
        )


def send_password_reset_email(user_id: int) -> None:
    user = (
        User.objects.filter(pk=user_id, is_staff=False, is_superuser=False)
        .select_related("profile", "profile__client")
        .first()
    )
    if user is None or not user.has_usable_password():
        return
    profile = get_user_profile(user)
    if profile is None or profile.role not in (
        UserProfile.Role.ADMIN,
        UserProfile.Role.CLIENT,
    ):
        return

    to_addr = (user.email or "").strip()
    if not to_addr:
        return

    ws = _workspace_for_user(user)
    if ws is None:
        return

    marketplace = (ws.marketplace_title or ws.name or "").strip() or (ws.slug or "")
    accent = (getattr(ws, "primary_color", None) or "").strip() or None
    reset_url = build_password_reset_url(user=user, workspace=ws)
    display_name = (user.get_full_name() or "").strip()
    login_email = to_addr.lower()

    subject, body, html_body, inline_logo = build_password_reset_transactional_email(
        marketplace_title=marketplace,
        contact_name=display_name,
        login_email=login_email,
        reset_url=reset_url,
        accent_hex=accent,
        workspace=ws,
    )

    if not send_workspace_transactional_email(
        ws,
        to_emails=[to_addr],
        subject=subject,
        body=body,
        html_body=html_body,
        inline_logo=inline_logo,
    ):
        logger.warning(
            "No se envió correo de restablecimiento para usuario %s.",
            user.pk,
        )
