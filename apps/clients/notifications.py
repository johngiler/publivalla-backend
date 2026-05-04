"""Correos y enlaces de activación de cuenta (cliente sin login en marketplace)."""

import logging
from urllib.parse import quote

from django.conf import settings
from django.core import signing

from apps.clients.models import Client
from apps.orders.email_notifications import send_workspace_transactional_email
from apps.orders.models import Order
from apps.users.models import UserProfile

logger = logging.getLogger(__name__)

CLIENT_ACTIVATE_SALT = "publivalla-client-activate-v1"


def client_has_marketplace_user(client: Client) -> bool:
    return UserProfile.objects.filter(
        client=client,
        role=UserProfile.Role.CLIENT,
    ).exists()


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
    - Si la empresa ya tiene usuario marketplace: solo log (el CRM puede notificar aparte).
    - Si no: envía correo con enlace para crear contraseña (mismo email de la ficha),
      usando la cuenta SMTP configurada en el workspace (Mi negocio), no DEFAULT_FROM_EMAIL.
    """
    client = order.client
    if client_has_marketplace_user(client):
        logger.info(
            "Orden %s aprobada; cliente %s ya tiene acceso marketplace.",
            order.pk,
            client.pk,
        )
        return

    token = build_client_activation_token(client.pk)
    base = getattr(settings, "FRONTEND_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
    link = f"{base}/activar-cuenta?token={quote(token)}"

    subject = f"Tu solicitud fue aprobada — {client.company_name}"
    greet = f"Hola {client.contact_name.strip()},\n\n" if client.contact_name.strip() else "Hola,\n\n"
    body = (
        greet
        + f"La solicitud asociada a tu empresa ({client.company_name}) fue aprobada.\n"
        + "Para acceder al marketplace con tu correo y gestionar tus órdenes, crea tu contraseña aquí:\n\n"
        + f"{link}\n\n"
        + "El enlace caduca en 14 días. Si ya creaste cuenta al comprar, inicia sesión con tu correo.\n"
    )

    to_addr = (client.email or "").strip()
    if not to_addr:
        logger.warning(
            "No se envía correo de activación: cliente %s sin correo en ficha. Enlace: %s",
            client.pk,
            link,
        )
        return

    ws = getattr(client, "workspace", None)
    if not send_workspace_transactional_email(
        ws,
        to_emails=[to_addr],
        subject=subject,
        body=body,
    ):
        logger.warning(
            "No se envió correo de activación para cliente %s (orden %s). "
            "Configura SMTP y remitente en Mi negocio o revisa el registro de errores. Enlace: %s",
            client.pk,
            order.pk,
            link,
        )
