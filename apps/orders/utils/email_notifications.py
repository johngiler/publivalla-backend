"""
Correos transaccionales del marketplace (cambio de estado de pedido, documentación del cliente, etc.).

**Multitenant (Publivalla):** cada envío usa el ``Workspace`` del pedido (owner / tenant del marketplace):
remitente y relay de «Mi negocio», título del marketplace, color de acento, logo PNG (Mi negocio) y
enlaces al SPA del subdominio de ese workspace. No hay branding ni relay global de plataforma
en estos mensajes.
"""

from __future__ import annotations

import logging
from typing import cast
from urllib.parse import urlencode
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

from django.core.mail import EmailMultiAlternatives, get_connection

from apps.orders.models import Order, OrderStatus
from apps.orders.utils.mailgun_sender import send_mailgun_text_email
from apps.orders.utils.transactional_email_templates import (
    OrderClientActivityKind,
    OrderStatusAudience,
    build_order_client_activity_admin_email,
    build_order_status_transactional_email,
    build_payment_installment_due_reminder_email,
    format_installment_due_date_label,
)
from apps.workspaces.utils.email_inline_logo import workspace_email_logo_inline_filename
from apps.users.models import UserProfile
from apps.workspaces.tenant import spa_public_base_url

logger = logging.getLogger(__name__)

_CLIENT_ACTIVITY_KEYS = frozenset(
    {"payment_receipt", "negotiation_signed", "art_upload"}
)


def _order_reference_for_list_filter(order: Order) -> str:
    """Referencia pública del pedido para ``?search=`` (cliente) o ``?q=`` (panel admin)."""
    return (order.code or "").strip().lstrip("#")


def _order_client_orders_url(order: Order) -> str:
    """Vista «Mis pedidos» del marketplace (cuenta cliente), filtrada por referencia si existe."""
    ws = getattr(getattr(order, "client", None), "workspace", None)
    base = spa_public_base_url(ws)
    ref = _order_reference_for_list_filter(order)
    if ref:
        return f"{base}/cuenta/pedidos?{urlencode({'search': ref})}"
    return f"{base}/cuenta/pedidos"


def _order_admin_orders_url(order: Order) -> str:
    """Sección Pedidos del panel admin del mismo tenant, filtrada por referencia si existe."""
    ws = getattr(getattr(order, "client", None), "workspace", None)
    base = spa_public_base_url(ws)
    ref = _order_reference_for_list_filter(order)
    if ref:
        return f"{base}/dashboard/pedidos?{urlencode({'q': ref})}"
    return f"{base}/dashboard/pedidos"


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


def _order_guest_submitted_dispatches(
    order: Order,
) -> list[tuple[list[str], OrderStatusAudience]]:
    """
    Checkout invitado (sin sesión) u otro envío sin actor al pasar a «Enviada».

    Siempre avisa a **todos** los administradores del workspace (sin quitar correos que
    coincidan con el de la empresa) y confirma al cliente.
    """
    if order.client.workspace is None:
        return []
    out: list[tuple[list[str], OrderStatusAudience]] = []
    admin_addrs = _emails_marketplace_admins(order, exclude_user_id=None)
    if admin_addrs:
        out.append((admin_addrs, "admins"))
    client_addrs = _emails_client_company(order)
    if client_addrs:
        out.append((client_addrs, "client_submitted"))
    return out


def _order_status_broadcast_dispatches(
    order: Order,
    *,
    to_status: str,
) -> list[tuple[list[str], OrderStatusAudience]]:
    """
    Sin actor identificable: empresa (enlace a cuenta cliente) y equipo (enlace al panel admin),
    en envíos separados para que el CTA coincida con el portal de cada destinatario.
    """
    ws = order.client.workspace
    if ws is None:
        return []
    client_addrs = _emails_client_company(order)
    admin_addrs = _emails_marketplace_admins(order, exclude_user_id=None)
    client_set = {a.strip().lower() for a in client_addrs if (a or "").strip()}
    admin_only = [
        a
        for a in admin_addrs
        if (a or "").strip() and a.strip().lower() not in client_set
    ]
    out: list[tuple[list[str], OrderStatusAudience]] = []
    if client_addrs:
        client_audience: OrderStatusAudience = (
            "client_submitted"
            if (to_status or "").strip() == OrderStatus.SUBMITTED
            else "client"
        )
        out.append((client_addrs, client_audience))
    if admin_only:
        out.append((admin_only, "admin_broadcast"))
    return out


def _order_status_email_dispatches(
    order: Order,
    actor_id: int | None,
    *,
    to_status: str,
) -> list[tuple[list[str], OrderStatusAudience]]:
    """
    Destinatarios y variante de plantilla por envío (puede haber más de un correo).

    - Admin marketplace del mismo workspace → empresa cliente (plantilla «cliente») y el resto
      de administradores del owner (plantilla «admin_peers»), sin notificar al propio actor.
    - Cliente marketplace del pedido → solo otros administradores (plantilla «admins»), sin el actor.
    - Sin actor (checkout invitado) al pasar a «Enviada» → equipo completo («admins») + empresa.
    - Sin actor en otros estados → empresa y admins por separado («admin_broadcast»).
    - Cliente que envía la solicitud (→ «Enviada») → admins y correo de confirmación a la empresa.
    """
    to_s = (to_status or "").strip()
    if actor_id is None:
        if to_s == OrderStatus.SUBMITTED:
            return _order_guest_submitted_dispatches(order)
        return _order_status_broadcast_dispatches(order, to_status=to_status)

    try:
        profile = UserProfile.objects.only(
            "role", "workspace_id", "client_id"
        ).get(user_id=actor_id)
    except UserProfile.DoesNotExist:
        if to_s == OrderStatus.SUBMITTED:
            return _order_guest_submitted_dispatches(order)
        return _order_status_broadcast_dispatches(order, to_status=to_status)

    ws_id = order.client.workspace_id
    if profile.role == UserProfile.Role.ADMIN and profile.workspace_id == ws_id:
        out: list[tuple[list[str], OrderStatusAudience]] = []
        client_addrs = _emails_client_company(order)
        admin_addrs = _emails_marketplace_admins(
            order, exclude_user_id=actor_id)
        client_set = {a.strip().lower()
                      for a in client_addrs if (a or "").strip()}
        admin_addrs = [
            a
            for a in admin_addrs
            if (a or "").strip() and a.strip().lower() not in client_set
        ]
        if client_addrs:
            client_audience: OrderStatusAudience = (
                "client_submitted"
                if (to_status or "").strip() == OrderStatus.SUBMITTED
                else "client"
            )
            out.append((client_addrs, client_audience))
        if admin_addrs:
            out.append((admin_addrs, "admin_peers"))
        return out

    if (
        profile.role == UserProfile.Role.CLIENT
        and profile.client_id == order.client_id
    ):
        out: list[tuple[list[str], OrderStatusAudience]] = []
        admins_only = _emails_marketplace_admins(
            order, exclude_user_id=actor_id)
        if admins_only:
            out.append((admins_only, "admins"))
        if (to_status or "").strip() == OrderStatus.SUBMITTED:
            client_addrs = _emails_client_company(order)
            if client_addrs:
                out.append((client_addrs, "client_submitted"))
        return out

    if to_s == OrderStatus.SUBMITTED:
        return _order_guest_submitted_dispatches(order)
    return _order_status_broadcast_dispatches(order, to_status=to_status)


def _mime_part_workspace_inline_logo(
    inline_logo: tuple[bytes, str, str],
) -> MIMEImage | MIMEBase | None:
    """Una parte MIME image/webp|png|jpeg|gif con Content-ID del logo del tenant."""
    data, filename, ctype = inline_logo
    main, _, sub = ctype.partition("/")
    if main != "image":
        return None
    if sub in ("png", "jpeg", "gif"):
        part: MIMEImage | MIMEBase = MIMEImage(data, _subtype=sub)
    elif sub == "webp":
        part = MIMEBase("image", "webp")
        part.set_payload(data)
        encoders.encode_base64(part)
    else:
        logger.warning("MIME de logo inline no soportado: %s", ctype)
        return None
    cid_name = workspace_email_logo_inline_filename()
    part.add_header("Content-ID", f"<{cid_name}>")
    part.add_header("Content-Disposition", "inline", filename=cid_name)
    return part


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
    inline_logo: tuple[bytes, str, str] | None = None,
) -> bool:
    """
    Envía un correo con la configuración transaccional del workspace (Mi negocio): SMTP o API (Mailgun).

    ``body`` es texto plano; ``html_body`` opcional se envía como alternativa multipart / campo HTML en Mailgun.

    ``inline_logo`` (bytes, nombre CID, MIME) se adjunta inline para clientes que usan ``cid:`` en el HTML;
    la plantilla también incluye fondo base64 en la cabecera para Apple Mail.

    Retorna False si falta remitente, relay incompleto, no hay destinatarios o el envío falló.
    """
    if ws is None:
        return False
    method = (getattr(ws, "transactional_email_method", "")
              or "smtp").strip().lower()
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
        provider = (getattr(ws, "transactional_email_provider", "")
                    or "mailgun").strip().lower()
        if provider != "mailgun":
            return False
        api_key = (getattr(ws, "transactional_email_api_key", "") or "").strip()
        domain = (
            getattr(ws, "transactional_email_mailgun_domain", "") or "").strip()
        region = (
            getattr(ws, "transactional_email_mailgun_region", "") or "us").strip()
        mg_inline = (
            [(inline_logo[1], inline_logo[0], inline_logo[2])]
            if inline_logo
            else None
        )
        return send_mailgun_text_email(
            api_key=api_key,
            domain=domain,
            region=region,
            from_email=from_email,
            to_emails=recipients,
            subject=subject,
            text=body,
            html=html_body,
            inline_images=mg_inline,
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
        if inline_logo:
            msg.mixed_subtype = "related"
            part = _mime_part_workspace_inline_logo(inline_logo)
            if part is not None:
                msg.attach(part)
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception(
            "Fallo al enviar correo transaccional del workspace (slug=%s).",
            getattr(ws, "slug", None),
        )
        return False


def try_send_order_client_activity_admin_emails(
    order: Order,
    *,
    activity: str,
    actor_id: int | None = None,
) -> None:
    """
    Avisa por correo a los administradores del workspace cuando el cliente añade documentación
    al pedido sin que cambie el estado (comprobante, hoja firmada, arte).
    """
    key = (activity or "").strip()
    if key not in _CLIENT_ACTIVITY_KEYS:
        logger.warning(
            "Actividad de cliente desconocida para correo admin: %s", activity)
        return
    ws = order.client.workspace
    if ws is None:
        return
    if not (ws.transactional_email_from_address or "").strip():
        return
    recipients = _emails_marketplace_admins(order, exclude_user_id=actor_id)
    if not recipients:
        logger.info(
            "Pedido %s — actividad %s: no hay administradores con correo para notificar.",
            order.pk,
            key,
        )
        return
    marketplace = (ws.marketplace_title or ws.name or "").strip() or ws.slug
    accent = (getattr(ws, "primary_color", None) or "").strip() or None
    admin_url = _order_admin_orders_url(order)
    subject, body, html_body, inline_logo = build_order_client_activity_admin_email(
        marketplace_title=marketplace,
        company_name=(order.client.company_name or "").strip(),
        order_code=(order.code or "").strip(),
        activity=cast(OrderClientActivityKind, key),
        orders_admin_url=admin_url,
        accent_hex=accent,
        workspace=ws,
    )
    if not send_workspace_transactional_email(
        ws,
        to_emails=recipients,
        subject=subject,
        body=body,
        html_body=html_body,
        inline_logo=inline_logo,
    ):
        logger.warning(
            "No se envió el correo de actividad de cliente (pedido %s, %s).",
            order.pk,
            key,
        )


def try_send_order_status_emails(
    order: Order,
    from_status: str,
    to_status: str,
    *,
    actor_id: int | None = None,
    skip_client_status_email: bool = False,
) -> None:
    """
    Envía un correo cuando cambia el estado del pedido (SMTP del workspace).

    Destinatarios según ``actor_id``: cliente del pedido notifica a administradores (sin el actor)
    y, si el estado pasa a «Enviada», también envía confirmación al correo de la empresa;
    administrador del owner notifica a la empresa cliente y a los demás administradores (sin el actor);
    sin actor o perfil no reconocible → correo a la empresa (enlace a cuenta) y otro al equipo
    (enlace al panel de pedidos), si hay destinatarios en cada grupo.
    """
    if from_status == to_status:
        return
    if (to_status or "").strip() == OrderStatus.DRAFT:
        return
    ws = order.client.workspace
    if ws is None:
        return
    from_addr = (ws.transactional_email_from_address or "").strip()
    if not from_addr:
        return

    dispatches = _order_status_email_dispatches(
        order, actor_id, to_status=to_status)
    if not dispatches:
        logger.info(
            "Pedido %s → %s: no hay destinatarios con correo (cliente o admins).",
            order.pk,
            to_status,
        )
        return

    from apps.clients.utils.marketplace_user import client_has_marketplace_user
    from apps.orders.services.order_hold_services import order_display_status_label

    if str(to_status) == str(order.status):
        to_label = order_display_status_label(order)
    else:
        try:
            to_label = OrderStatus(to_status).label
        except ValueError:
            to_label = to_status

    from_s = (from_status or "").strip()
    if not from_s or from_s == OrderStatus.DRAFT:
        from_label = ""
    elif from_s == OrderStatus.SUBMITTED:
        from_label = "Reservado"
    else:
        try:
            from_label = OrderStatus(from_s).label
        except ValueError:
            from_label = from_s

    marketplace = (ws.marketplace_title or ws.name or "").strip() or ws.slug
    accent = (getattr(ws, "primary_color", None) or "").strip() or None

    mounting_groups = None
    if (to_status or "").strip() == OrderStatus.CLIENT_APPROVED:
        from apps.orders.utils.order_mounting_provider_email import (
            order_mounting_provider_groups_by_center,
        )

        mounting_groups = order_mounting_provider_groups_by_center(order)

    any_failed = False
    for recipients, audience in dispatches:
        if not recipients:
            continue
        if skip_client_status_email and audience in ("client", "client_submitted"):
            logger.info(
                "Pedido %s → %s: omitido correo de estado al cliente (activación primera vez).",
                order.pk,
                to_status,
            )
            continue
        orders_url = (
            _order_client_orders_url(order)
            if audience in ("client", "client_submitted")
            else _order_admin_orders_url(order)
        )
        subject, body, html_body, inline_logo = build_order_status_transactional_email(
            marketplace_title=marketplace,
            audience=audience,
            order_code=(order.code or "").strip(),
            previous_status_label=from_label,
            new_status_label=to_label,
            company_name=(order.client.company_name or "").strip(),
            orders_url=orders_url,
            accent_hex=accent,
            workspace=ws,
            client_has_marketplace_account=client_has_marketplace_user(order.client),
            to_status=to_status,
            mounting_provider_groups=mounting_groups
            if audience == "client"
            else None,
        )
        if not send_workspace_transactional_email(
            ws,
            to_emails=recipients,
            subject=subject,
            body=body,
            html_body=html_body,
            inline_logo=inline_logo,
        ):
            any_failed = True

    if any_failed:
        logger.warning(
            "No se envió al menos un correo de cambio de estado (pedido %s, %s → %s); "
            "revisa el relay de correo del workspace o el registro de errores anterior.",
            order.pk,
            from_status,
            to_status,
        )


def try_send_payment_installment_due_reminder_emails(
    installment,
    *,
    days_before: int,
) -> bool:
    """
    Recordatorio de vencimiento de cuota (cliente y administradores del workspace).

    Marca éxito solo si cada grupo con correo configurado recibió el mensaje.
    """
    from apps.orders.services.payment_plan_services import (
        format_months_label,
        installment_has_invoice,
    )

    if days_before not in (1, 2):
        logger.warning(
            "Días antes de vencimiento no soportados para recordatorio: %s",
            days_before,
        )
        return False

    order = installment.plan.order
    ws = order.client.workspace
    if ws is None:
        return False
    if not (ws.transactional_email_from_address or "").strip():
        return False

    months = sorted((m.year, m.month) for m in installment.months.all())
    period_label = format_months_label(months)
    has_invoice = installment_has_invoice(installment)
    total_count = installment.plan.installments.count()
    marketplace = (ws.marketplace_title or ws.name or "").strip() or ws.slug
    accent = (getattr(ws, "primary_color", None) or "").strip() or None
    amount_usd = f"{installment.amount:,.2f}"
    due_date_label = format_installment_due_date_label(installment.due_date)
    order_code = (order.code or "").strip()
    company = (order.client.company_name or "").strip()

    client_emails = _emails_client_company(order)
    admin_emails = _emails_marketplace_admins(order)
    if not client_emails and not admin_emails:
        logger.info(
            "Cuota %s (pedido %s): sin destinatarios para recordatorio %s días antes.",
            installment.pk,
            order.pk,
            days_before,
        )
        return False

    client_ok: bool | None = None
    admin_ok: bool | None = None

    if client_emails:
        subject, body, html_body, inline_logo = (
            build_payment_installment_due_reminder_email(
                audience="client",
                marketplace_title=marketplace,
                company_name=company,
                order_code=order_code,
                installment_sequence=installment.sequence,
                installment_total=total_count,
                period_label=period_label,
                amount_usd=amount_usd,
                due_date_label=due_date_label,
                days_before=days_before,
                has_invoice=has_invoice,
                action_url=_order_client_orders_url(order),
                accent_hex=accent,
                workspace=ws,
            )
        )
        client_ok = send_workspace_transactional_email(
            ws,
            to_emails=client_emails,
            subject=subject,
            body=body,
            html_body=html_body,
            inline_logo=inline_logo,
        )

    if admin_emails:
        subject, body, html_body, inline_logo = (
            build_payment_installment_due_reminder_email(
                audience="admin",
                marketplace_title=marketplace,
                company_name=company,
                order_code=order_code,
                installment_sequence=installment.sequence,
                installment_total=total_count,
                period_label=period_label,
                amount_usd=amount_usd,
                due_date_label=due_date_label,
                days_before=days_before,
                has_invoice=has_invoice,
                action_url=_order_admin_orders_url(order),
                accent_hex=accent,
                workspace=ws,
            )
        )
        admin_ok = send_workspace_transactional_email(
            ws,
            to_emails=admin_emails,
            subject=subject,
            body=body,
            html_body=html_body,
            inline_logo=inline_logo,
        )

    if client_emails and not client_ok:
        logger.warning(
            "No se envió recordatorio de cuota al cliente (pedido %s, cuota %s).",
            order.pk,
            installment.pk,
        )
        return False
    if admin_emails and not admin_ok:
        logger.warning(
            "No se envió recordatorio de cuota a administradores (pedido %s, cuota %s).",
            order.pk,
            installment.pk,
        )
        return False

    return True
