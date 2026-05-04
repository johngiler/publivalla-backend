"""Correos por cambio de estado de pedido (cuenta SMTP configurada en el workspace)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

from apps.orders.models import Order, OrderStatus
from apps.users.models import UserProfile

logger = logging.getLogger(__name__)


def _order_public_url(order: Order) -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
    return f"{base}/cuenta/pedidos"


def _emails_client_company(order: Order) -> list[str]:
    """Correo de ficha empresa (Mi empresa)."""
    a = (order.client.email or "").strip()
    return [a] if a else []


def _emails_marketplace_admins(
    order: Order, *, exclude_user_id: int | None = None
) -> list[str]:
    """Correos de usuarios con rol administrador marketplace (Mi perfil)."""
    ws = order.client.workspace
    if ws is None:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(addr: str | None) -> None:
        x = (addr or "").strip()
        if not x or x in seen:
            return
        seen.add(x)
        out.append(x)

    qs = UserProfile.objects.filter(
        workspace_id=ws.pk,
        role=UserProfile.Role.ADMIN,
    ).select_related("user")
    for prof in qs:
        if exclude_user_id is not None and prof.user_id == exclude_user_id:
            continue
        add(getattr(prof.user, "email", None))
    return out


def _emails_client_and_admins(order: Order) -> list[str]:
    """Cliente + todos los admins (p. ej. proceso automático sin actor)."""
    ws = order.client.workspace
    if ws is None:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(addr: str | None) -> None:
        a = (addr or "").strip()
        if not a or a in seen:
            return
        seen.add(a)
        out.append(a)

    add(order.client.email)
    qs = UserProfile.objects.filter(
        workspace_id=ws.pk,
        role=UserProfile.Role.ADMIN,
    ).select_related("user")
    for prof in qs:
        add(getattr(prof.user, "email", None))
    return out


def _status_change_recipient_emails(order: Order, actor_id: int | None) -> list[str]:
    """
    Quién recibe el aviso de cambio de estado:
    - Admin marketplace del workspace → solo la empresa cliente (Mi empresa).
    - Cliente marketplace de ese pedido → solo administradores (Mi perfil), sin el propio actor.
    - Sin actor (sistema, invitado sin usuario) → cliente y admins (comportamiento amplio).
    - Actor no clasificable (p. ej. staff de plataforma) → cliente y admins.
    """
    if actor_id is None:
        return _emails_client_and_admins(order)

    try:
        profile = UserProfile.objects.only(
            "role", "workspace_id", "client_id"
        ).get(user_id=actor_id)
    except UserProfile.DoesNotExist:
        return _emails_client_and_admins(order)

    ws_id = order.client.workspace_id
    if profile.role == UserProfile.Role.ADMIN and profile.workspace_id == ws_id:
        return _emails_client_company(order)
    if (
        profile.role == UserProfile.Role.CLIENT
        and profile.client_id == order.client_id
    ):
        return _emails_marketplace_admins(order, exclude_user_id=actor_id)
    return _emails_client_and_admins(order)


def _workspace_smtp_connection(ws):
    host = (ws.transactional_email_host or "").strip()
    if not host:
        return None
    # Evita bloqueos largos en connect() (el worker de Gunicorn puede abortar con SystemExit → 500).
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=host,
        port=int(ws.transactional_email_port or 587),
        username=(ws.transactional_email_username or "").strip(),
        password=(ws.transactional_email_password or "").strip(),
        use_tls=bool(ws.transactional_email_use_tls),
        use_ssl=bool(getattr(ws, "transactional_email_use_ssl", False)),
        timeout=25,
    )


def send_workspace_transactional_email(
    ws,
    *,
    to_emails: list[str],
    subject: str,
    body: str,
) -> bool:
    """
    Envía un correo usando solo la cuenta SMTP configurada en el workspace (Mi negocio).

    Retorna True si el mensaje se envió. Retorna False si falta workspace, SMTP incompleto,
    no hay destinatarios o el envío falló (en ese caso también se registra la excepción).
    """
    if ws is None:
        return False
    host = (ws.transactional_email_host or "").strip()
    from_addr = (ws.transactional_email_from_address or "").strip()
    if not host or not from_addr:
        return False
    recipients = [e.strip() for e in to_emails if (e or "").strip()]
    if not recipients:
        return False
    conn = _workspace_smtp_connection(ws)
    if conn is None:
        return False
    marketplace = (ws.marketplace_title or ws.name or "").strip() or ws.slug
    from_name = (ws.transactional_email_from_name or "").strip() or marketplace
    from_email = f"{from_name} <{from_addr}>" if from_name else from_addr
    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=recipients,
            connection=conn,
        )
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception(
            "Fallo al enviar correo transaccional del workspace (slug=%s).",
            getattr(ws, "slug", None),
        )
        return False


def try_send_order_status_emails(
    order: Order,
    from_status: str,
    to_status: str,
    *,
    actor_id: int | None = None,
) -> None:
    """
    Envía un correo cuando cambia el estado del pedido (SMTP del workspace).

    Destinatarios según quién originó el cambio (``actor_id`` en el evento de historial):
    administrador marketplace → solo correo de la empresa cliente (Mi empresa); cliente
    marketplace del pedido → solo correos de administradores (Mi perfil); sin actor o actor
    no reconocido → empresa y administradores.
    """
    if from_status == to_status:
        return
    ws = order.client.workspace
    if ws is None:
        return
    host = (ws.transactional_email_host or "").strip()
    from_addr = (ws.transactional_email_from_address or "").strip()
    if not host or not from_addr:
        return

    recipients = _status_change_recipient_emails(order, actor_id)
    if not recipients:
        logger.info(
            "Pedido %s → %s: no hay destinatarios con correo (cliente o admins).",
            order.pk,
            to_status,
        )
        return

    try:
        to_label = OrderStatus(to_status).label
    except ValueError:
        to_label = to_status

    try:
        from_label = OrderStatus(from_status).label if from_status else ""
    except ValueError:
        from_label = from_status or ""

    ref = (order.code or "").strip() or f"#{order.pk}"
    marketplace = (ws.marketplace_title or ws.name or "").strip() or ws.slug
    subject = f"[{marketplace}] Pedido {ref}: {to_label}"
    lines: list[str] = [
        f"El pedido {ref} cambió de estado.",
        "",
        f"Estado anterior: {from_label or '—'}",
        f"Estado actual: {to_label}",
        "",
        f"Cliente: {(order.client.company_name or '').strip() or '—'}",
        "",
        f"Consulta el detalle en tu cuenta: {_order_public_url(order)}",
        "",
        "Este mensaje lo envía el sistema de notificaciones del marketplace.",
    ]
    body = "\n".join(lines)

    if not send_workspace_transactional_email(
        ws,
        to_emails=recipients,
        subject=subject,
        body=body,
    ):
        logger.warning(
            "No se envió correo de cambio de estado (pedido %s, %s → %s); "
            "revisa SMTP del workspace o el registro de errores anterior.",
            order.pk,
            from_status,
            to_status,
        )
