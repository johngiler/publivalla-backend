"""Correos y enlaces de activación de cuenta (empresa sin login en marketplace)."""

import logging

from django.core import signing

from apps.clients.models import Client
from apps.clients.utils.marketplace_user import (
    MarketplaceUserError,
    build_client_password_setup_url,
    client_has_marketplace_user,
    create_marketplace_user_for_client,
)
from apps.orders.utils.email_notifications import send_workspace_transactional_email
from apps.orders.models import Order
from apps.orders.utils.transactional_email_templates import (
    build_client_activation_transactional_email,
)

logger = logging.getLogger(__name__)

CLIENT_ACTIVATE_SALT = "publivalla-client-activate-v1"


def build_client_activation_token(client_id: int) -> str:
    signer = signing.TimestampSigner(salt=CLIENT_ACTIVATE_SALT)
    return signer.sign(str(client_id))


def parse_client_activation_token(token: str, *, max_age: int = 14 * 86400) -> int:
    signer = signing.TimestampSigner(salt=CLIENT_ACTIVATE_SALT)
    value = signer.unsign(token, max_age=max_age)
    return int(value)


def notify_client_after_order_client_approved(order: Order) -> None:
    """
    Cuando el admin pasa la orden a «Solicitud aprobada» (estado client_approved):

    - Si la empresa ya tiene usuario marketplace: no hace nada.
    - Si no: crea el usuario (mismo flujo que «Generar usuario» en clientes) y envía
      correo con enlace ``/registro`` para definir contraseña, indicando el correo de acceso.
    """
    client = order.client
    if client_has_marketplace_user(client):
        logger.info(
            "Orden %s aprobada; cliente %s ya tiene acceso marketplace.",
            order.pk,
            client.pk,
        )
        return

    to_addr = (client.email or "").strip()
    if not to_addr:
        logger.warning(
            "No se envía correo de activación: cliente %s sin correo en ficha (orden %s).",
            client.pk,
            order.pk,
        )
        return

    try:
        user = create_marketplace_user_for_client(client)
    except MarketplaceUserError as exc:
        logger.warning(
            "Orden %s aprobada; no se creó usuario para cliente %s (%s): %s",
            order.pk,
            client.pk,
            exc.code,
            exc.message,
        )
        return

    link = build_client_password_setup_url(client=client, user=user)
    # Mismo correo obligatorio en checkout / ficha (to_addr); el usuario se crea con él.
    login_email = (user.email or user.username or to_addr).strip().lower()

    ws = getattr(client, "workspace", None)
    contact_line = ""
    if (client.contact_name or "").strip():
        contact_line = f"Hola {(client.contact_name or '').strip()},"
    marketplace = ""
    if ws is not None:
        marketplace = (ws.marketplace_title or ws.name or "").strip() or (ws.slug or "")
    if not marketplace:
        marketplace = "Marketplace"
    accent = (getattr(ws, "primary_color", None) or "").strip() if ws else None
    subject, body, html_body, inline_logo = build_client_activation_transactional_email(
        marketplace_title=marketplace,
        company_name=client.company_name or "",
        contact_first_line=contact_line,
        activation_url=link,
        login_email=login_email,
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
            "No se envió correo de activación para cliente %s (orden %s). "
            "Configura el envío de correo y el remitente en Mi negocio o revisa el registro de errores. Enlace: %s",
            client.pk,
            order.pk,
            link,
        )
