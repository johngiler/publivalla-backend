"""Correos por cambio de estado de pedido (cuenta SMTP configurada en el workspace)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from apps.orders.models import Order, OrderStatus
from apps.orders.mailgun_sender import send_mailgun_text_email
from apps.orders.transactional_email_templates import (
    OrderStatusAudience,
    build_order_status_transactional_email,
)
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


def _order_status_email_audience(order: Order, actor_id: int | None) -> OrderStatusAudience:
    """
    Alineado con _status_change_recipient_emails: define el tono del asunto y del cuerpo
    (cliente del pedido, equipo del marketplace, o ambos).
    """
    if actor_id is None:
        return "all"

    try:
        profile = UserProfile.objects.only(
            "role", "workspace_id", "client_id"
        ).get(user_id=actor_id)
    except UserProfile.DoesNotExist:
        return "all"

    ws_id = order.client.workspace_id
    if profile.role == UserProfile.Role.ADMIN and profile.workspace_id == ws_id:
        return "client"
    if (
        profile.role == UserProfile.Role.CLIENT
        and profile.client_id == order.client_id
    ):
        return "admins"
    return "all"


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
    html_body: str | None = None,
) -> bool:
    """
    Envía un correo con la configuración transaccional del workspace (Mi negocio): SMTP o API (Mailgun).

    ``body`` es texto plano; ``html_body`` opcional se envía como alternativa multipart / campo HTML en Mailgun.
    Retorna False si falta remitente, relay incompleto, no hay destinatarios o el envío falló.
    """
    if ws is None:
        return False
    method = (getattr(ws, "transactional_email_method", "") or "smtp").strip().lower()
    from_addr = (ws.transactional_email_from_address or "").strip()
    if not from_addr:
        return False
    recipients = [e.strip() for e in to_emails if (e or "").strip()]
    if not recipients:
        return False
    marketplace = (ws.marketplace_title or ws.name or "").strip() or ws.slug
    from_name = (ws.transactional_email_from_name or "").strip() or marketplace
    from_email = f"{from_name} <{from_addr}>" if from_name else from_addr
    if method == "api":
        provider = (getattr(ws, "transactional_email_provider", "") or "mailgun").strip().lower()
        if provider != "mailgun":
            return False
        api_key = (getattr(ws, "transactional_email_api_key", "") or "").strip()
        domain = (getattr(ws, "transactional_email_mailgun_domain", "") or "").strip()
        region = (getattr(ws, "transactional_email_mailgun_region", "") or "us").strip()
        return send_mailgun_text_email(
            api_key=api_key,
            domain=domain,
            region=region,
            from_email=from_email,
            to_emails=recipients,
            subject=subject,
            text=body,
            html=html_body,
        )

    host = (ws.transactional_email_host or "").strip()
    if not host:
        return False
    conn = _workspace_smtp_connection(ws)
    if conn is None:
        return False
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=from_email,
            to=recipients,
            connection=conn,
        )
        if (html_body or "").strip():
            msg.attach_alternative(html_body.strip(), "text/html")
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
    from_addr = (ws.transactional_email_from_address or "").strip()
    if not from_addr:
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

    marketplace = (ws.marketplace_title or ws.name or "").strip() or ws.slug
    audience = _order_status_email_audience(order, actor_id)
    accent = (getattr(ws, "primary_color", None) or "").strip() or None
    subject, body, html_body = build_order_status_transactional_email(
        marketplace_title=marketplace,
        audience=audience,
        order_code=(order.code or "").strip(),
        previous_status_label=from_label,
        new_status_label=to_label,
        company_name=(order.client.company_name or "").strip(),
        orders_url=_order_public_url(order),
        accent_hex=accent,
    )

    if not send_workspace_transactional_email(
        ws,
        to_emails=recipients,
        subject=subject,
        body=body,
        html_body=html_body,
    ):
        logger.warning(
            "No se envió correo de cambio de estado (pedido %s, %s → %s); "
            "revisa el relay de correo del workspace o el registro de errores anterior.",
            order.pk,
            from_status,
            to_status,
        )
