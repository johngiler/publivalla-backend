"""
Plantillas HTML para correos transaccionales (pedidos, activación).

Variables expuestas al contenido: solo datos útiles para quien recibe el correo
(referencia humana del pedido, nombres legibles, estados, enlace de acción).
Sin IDs internos ni jerga técnica en el cuerpo visible.

El logotipo en cabecera usa ``logo_png_artifacts`` (Mi negocio, PNG): adjunto inline (CID) para Gmail
y fondo base64 en la celda para Apple Mail; si no hay archivo usable se muestra el nombre del marketplace.
"""

from __future__ import annotations

import html
import re
from typing import Literal

from apps.orders.utils.email_transactional_logo import (
    prepare_workspace_logo_for_transactional_email,
)
from apps.workspaces.utils.email_inline_logo import (
    EMAIL_LOGO_HEAD_STYLES,
    workspace_email_logo_header_row,
)

OrderStatusAudience = Literal[
    "client",
    "client_submitted",
    "admins",
    "admin_peers",
    "admin_broadcast",
]

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?([0-9a-fA-F]{2})?$")


def _safe(s: str) -> str:
    return html.escape((s or "").strip(), quote=True)


def _cta_background_hex(ws_primary: str | None) -> str:
    raw = (ws_primary or "").strip()
    if _HEX_COLOR.match(raw):
        return raw
    return "#18181b"


def _append_order_status_rows(
    rows: list[tuple[str, str]],
    *,
    previous_status_label: str,
    new_status_label: str,
) -> None:
    """No muestra «Estado anterior» si venía de borrador o no hay etiqueta."""
    prev = (previous_status_label or "").strip()
    if prev and prev != "—":
        rows.append(("Estado anterior", prev))
    rows.append(("Estado actual", (new_status_label or "").strip() or "—"))


def _render_transactional_shell(
    *,
    document_title: str,
    headline: str,
    lead: str,
    rows: list[tuple[str, str]],
    cta_url: str | None,
    cta_label: str | None,
    footer_note: str,
    accent_hex: str,
    inline_logo: tuple[bytes, str, str] | None,
    tenant_logo_alt: str,
) -> str:
    logo_row = workspace_email_logo_header_row(inline_logo, alt=tenant_logo_alt)

    rows_html = ""
    for label, value in rows:
        if not (value or "").strip():
            continue
        rows_html += (
            '<tr><td style="padding:6px 0;border-bottom:1px solid #f4f4f5;">'
            f'<span style="display:block;font:600 12px/1.4 system-ui,sans-serif;color:#71717a;">{_safe(label)}</span>'
            f'<span style="display:block;margin-top:4px;font:15px/1.45 system-ui,sans-serif;color:#18181b;">{_safe(value)}</span>'
            "</td></tr>"
        )

    accent = _safe(accent_hex)
    cta_block = ""
    if (cta_url or "").strip() and (cta_label or "").strip():
        cta_block = f"""
          <tr>
            <td style="padding:22px 24px 8px;">
              <a href="{_safe(cta_url.strip())}" style="display:inline-block;padding:12px 20px;border-radius:12px;background:{accent};color:#ffffff;font:600 14px/1 system-ui,sans-serif;text-decoration:none;">
                {_safe(cta_label.strip())}
              </a>
            </td>
          </tr>"""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="x-apple-disable-message-reformatting">
  <title>{_safe(document_title)}</title>
  {EMAIL_LOGO_HEAD_STYLES}
</head>
<body style="margin:0;padding:0;background:#f4f4f5;-webkit-text-size-adjust:100%;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f4f5;">
    <tr>
      <td align="center" style="padding:28px 14px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;border-collapse:separate;border-spacing:0;background:#ffffff;border-radius:16px;border:1px solid #e4e4e7;overflow:hidden;">
          {logo_row}
          <tr>
            <td style="padding:24px 24px 8px;">
              <h1 style="margin:0;font:700 20px/1.25 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#18181b;">
                {_safe(headline)}
              </h1>
              <p style="margin:14px 0 0;font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#3f3f46;">
                {_safe(lead)}
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 4px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                {rows_html}
              </table>
            </td>
          </tr>
          {cta_block}
          <tr>
            <td style="padding:16px 24px 28px;border-top:1px solid #f4f4f5;border-radius:0 0 16px 16px;font:12px/1.5 system-ui,sans-serif;color:#71717a;">
              {_safe(footer_note)}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_order_status_transactional_email(
    *,
    marketplace_title: str,
    audience: OrderStatusAudience,
    order_code: str,
    previous_status_label: str,
    new_status_label: str,
    company_name: str,
    orders_url: str,
    accent_hex: str | None,
    workspace,
    client_has_marketplace_account: bool = True,
) -> tuple[str, str, str, tuple[bytes, str, str] | None]:
    """
    Construye asunto, cuerpo texto plano, HTML y datos del logo inline (o ``None``).

    ``workspace`` determina el logotipo del tenant en el HTML y el cuarto valor devuelto
    (bytes + nombre + MIME) para adjuntarlo al envío.

    Variables de negocio (todas cadenas legibles):
    - marketplace_title, order_code (vacío si aún no hay código público),
      previous_status_label, new_status_label, company_name, orders_url.
    - ``client_has_marketplace_account``: si es False y la audiencia es ``client`` o
      ``client_submitted``, no se incluye el botón «Ir a mis pedidos».
    """
    mp = (marketplace_title or "").strip() or "Marketplace"
    code = (order_code or "").strip()
    prev_l = (previous_status_label or "").strip()
    new_l = (new_status_label or "").strip() or "—"
    company = (company_name or "").strip() or "—"
    accent = _cta_background_hex(accent_hex)

    if audience == "client":
        subject = f"{mp}: tu pedido pasó a «{new_l}»"
        headline = "Actualización de tu pedido"
        lead = f"Tu pedido cambió de estado. Ahora figura como «{new_l}»."
        rows: list[tuple[str, str]] = []
        if code:
            rows.append(("Referencia", code))
        _append_order_status_rows(
            rows, previous_status_label=prev_l, new_status_label=new_l
        )
        if client_has_marketplace_account:
            footer = (
                "Este mensaje es una notificación automática del marketplace. "
                "Si no esperabas este correo, revisa la actividad de tu cuenta."
            )
        else:
            footer = (
                "Este mensaje es una notificación automática del marketplace. "
                "Si no esperabas este correo, contacta al equipo del marketplace."
            )
    elif audience == "client_submitted":
        subject = f"{mp}: recibimos tu solicitud"
        headline = "Solicitud enviada"
        if client_has_marketplace_account:
            lead = (
                "Ya recibimos tu solicitud en el marketplace. El equipo la revisará; "
                "si necesitan algún dato adicional, se pondrán en contacto contigo. "
                "Puedes consultar el estado del pedido cuando quieras desde tu cuenta. "
                "Gracias por tu paciencia mientras avanzamos en el proceso."
            )
            footer = (
                "Este mensaje confirma que tu envío quedó registrado. "
                "Si no realizaste esta solicitud, revisa la actividad de tu cuenta."
            )
        else:
            lead = (
                "Ya recibimos tu solicitud en el marketplace. El equipo la revisará; "
                "si necesitan algún dato adicional, se pondrán en contacto contigo. "
                "Cuando aprueben tu solicitud, recibirás un correo con los pasos para crear "
                "tu acceso al marketplace. Gracias por tu paciencia mientras avanzamos en el proceso."
            )
            footer = (
                "Este mensaje confirma que tu envío quedó registrado. "
                "Si no realizaste esta solicitud, contacta al equipo del marketplace."
            )
        rows = [
            ("Estado actual", new_l),
        ]
        if code:
            rows.insert(0, ("Referencia", code))
    elif audience == "admins":
        subject = f"{mp}: pedido de {company} — «{new_l}»"
        headline = "Cambio de estado en un pedido"
        lead = (
            f"La empresa «{company}» tiene un pedido que avanzó en el flujo. "
            f"El estado actual es «{new_l}»."
        )
        rows = [("Empresa", company)]
        if code:
            rows.insert(0, ("Referencia del pedido", code))
        _append_order_status_rows(
            rows, previous_status_label=prev_l, new_status_label=new_l
        )
        footer = (
            "Notificación para el equipo del marketplace. "
            "Revisa el detalle en el panel si necesitas tomar acción."
        )
    elif audience == "admin_peers":
        subject = f"{mp}: pedido de {company} — «{new_l}»"
        headline = "Cambio de estado en un pedido"
        lead = (
            f"Otro administrador del marketplace actualizó el flujo del pedido de «{company}». "
            f"El estado actual es «{new_l}»."
        )
        rows = [("Empresa", company)]
        if code:
            rows.insert(0, ("Referencia del pedido", code))
        _append_order_status_rows(
            rows, previous_status_label=prev_l, new_status_label=new_l
        )
        footer = (
            "Notificación para el equipo del marketplace. "
            "Revisa el detalle en el panel si necesitas tomar acción."
        )
    elif audience == "admin_broadcast":
        subject = f"{mp}: actualización de pedido — «{new_l}»"
        headline = "Actualización de un pedido"
        lead = (
            f"Se registró un cambio de estado en un pedido del marketplace. "
            f"El estado actual es «{new_l}»."
        )
        rows = [("Empresa", company)]
        if code:
            rows.insert(0, ("Referencia del pedido", code))
        _append_order_status_rows(
            rows, previous_status_label=prev_l, new_status_label=new_l
        )
        footer = "Notificación automática del sistema de pedidos."
    else:
        raise ValueError(f"audience de correo de pedido no soportada: {audience!r}")

    cta_label = (
        "Ir a mis pedidos"
        if audience in ("client", "client_submitted")
        else "Ir al panel de pedidos"
    )
    # Empresa sin usuario marketplace: correos informativos sin CTA; el único botón
    # para invitados es «Crear contraseña» en el correo de activación tras aprobación.
    include_cta = not (
        audience in ("client", "client_submitted")
        and not client_has_marketplace_account
    )
    inline_logo = prepare_workspace_logo_for_transactional_email(workspace)
    brand_alt = (
        (
            (getattr(workspace, "marketplace_title", None) or getattr(workspace, "name", None) or "")
            .strip()
            if workspace is not None
            else ""
        )
        or mp
    )
    html_body = _render_transactional_shell(
        document_title=subject,
        headline=headline,
        lead=lead,
        rows=rows,
        cta_url=orders_url if include_cta else None,
        cta_label=cta_label if include_cta else None,
        footer_note=footer,
        accent_hex=accent,
        inline_logo=inline_logo,
        tenant_logo_alt=brand_alt,
    )

    lines = [
        headline,
        "",
        lead,
        "",
    ]
    for label, value in rows:
        if (value or "").strip():
            lines.append(f"{label}: {value}")
    if include_cta:
        lines.extend(
            [
                "",
                f"{cta_label}: {orders_url}",
            ]
        )
    lines.extend(["", footer])
    text_body = "\n".join(lines)
    return subject, text_body, html_body, inline_logo


def build_client_activation_transactional_email(
    *,
    marketplace_title: str,
    company_name: str,
    contact_first_line: str,
    activation_url: str,
    login_email: str,
    accent_hex: str | None,
    workspace,
) -> tuple[str, str, str, tuple[bytes, str, str] | None]:
    """Correo de activación tras aprobación (misma envoltura visual y logo del ``workspace``)."""
    mp = (marketplace_title or "").strip() or "Marketplace"
    company = (company_name or "").strip() or "tu empresa"
    accent = _cta_background_hex(accent_hex)
    greet = (contact_first_line or "").strip()
    access_email = (login_email or "").strip()

    subject = f"{mp}: activa tu acceso al marketplace"
    headline = "Tu solicitud fue aprobada"
    if access_email:
        lead_main = (
            "Tu solicitud fue aprobada. Usa el botón de abajo para crear tu contraseña. "
            f"Para iniciar sesión en el marketplace, usa siempre este correo: {access_email}."
        )
    else:
        lead_main = (
            "Tu solicitud fue aprobada. Usa el botón de abajo para crear tu contraseña "
            "y gestionar pedidos y reservas en el marketplace."
        )
    lead = f"{greet} {lead_main}".strip() if greet else lead_main

    rows: list[tuple[str, str]] = []
    if access_email:
        rows.append(("Correo para iniciar sesión", access_email))
    rows.append(("Empresa", company))
    footer = (
        "El enlace caduca en 14 días. Inicia sesión con el correo indicado arriba y la contraseña "
        "que definas con el botón. Este mensaje lo envía el sistema de notificaciones del marketplace."
    )

    inline_logo = prepare_workspace_logo_for_transactional_email(workspace)
    brand_alt = (
        (
            (getattr(workspace, "marketplace_title", None) or getattr(workspace, "name", None) or "")
            .strip()
            if workspace is not None
            else ""
        )
        or mp
    )
    html_body = _render_transactional_shell(
        document_title=subject,
        headline=headline,
        lead=lead,
        rows=rows,
        cta_url=activation_url,
        cta_label="Crear contraseña",
        footer_note=footer,
        accent_hex=accent,
        inline_logo=inline_logo,
        tenant_logo_alt=brand_alt,
    )

    text_lines = [headline, "", lead, ""]
    for label, value in rows:
        if (value or "").strip():
            text_lines.append(f"{label}: {value}")
    text_lines.extend(["", f"Crear contraseña: {activation_url}", "", footer])
    return subject, "\n".join(text_lines), html_body, inline_logo


OrderClientActivityKind = Literal["payment_receipt", "negotiation_signed", "art_upload"]


def build_order_client_activity_admin_email(
    *,
    marketplace_title: str,
    company_name: str,
    order_code: str,
    activity: OrderClientActivityKind,
    orders_admin_url: str,
    accent_hex: str | None,
    workspace,
) -> tuple[str, str, str, tuple[bytes, str, str] | None]:
    """
    Aviso al equipo del marketplace cuando el cliente añade documentación al pedido
    (sin cambio de estado).
    """
    mp = (marketplace_title or "").strip() or "Marketplace"
    company = (company_name or "").strip() or "—"
    code = (order_code or "").strip()
    accent = _cta_background_hex(accent_hex)

    if activity == "payment_receipt":
        subject = f"{mp}: comprobante de pago — «{company}»"
        headline = "Comprobante de pago cargado"
        lead = (
            f"La empresa «{company}» subió o actualizó el comprobante de pago en un pedido. "
            "Revisa el archivo en el panel cuando puedas."
        )
    elif activity == "negotiation_signed":
        subject = f"{mp}: hoja de negociación firmada — «{company}»"
        headline = "Hoja de negociación firmada"
        lead = (
            f"La empresa «{company}» cargó o actualizó la hoja de negociación firmada. "
            "Puedes revisar el documento en el panel del pedido."
        )
    elif activity == "art_upload":
        subject = f"{mp}: nuevo archivo de arte — «{company}»"
        headline = "Archivo de arte subido"
        lead = (
            f"La empresa «{company}» adjuntó un archivo de arte a una línea del pedido. "
            "Revisa los adjuntos en el panel para continuar el flujo."
        )
    else:
        raise ValueError(f"actividad de cliente no soportada: {activity!r}")

    rows: list[tuple[str, str]] = [("Empresa", company)]
    if code:
        rows.insert(0, ("Referencia del pedido", code))
    footer = (
        "Notificación para el equipo del marketplace. "
        "Este aviso no implica un cambio automático de estado del pedido."
    )

    inline_logo = prepare_workspace_logo_for_transactional_email(workspace)
    brand_alt = (
        (
            (getattr(workspace, "marketplace_title", None) or getattr(workspace, "name", None) or "")
            .strip()
            if workspace is not None
            else ""
        )
        or mp
    )
    html_body = _render_transactional_shell(
        document_title=subject,
        headline=headline,
        lead=lead,
        rows=rows,
        cta_url=orders_admin_url,
        cta_label="Ir al panel de pedidos",
        footer_note=footer,
        accent_hex=accent,
        inline_logo=inline_logo,
        tenant_logo_alt=brand_alt,
    )

    lines = [headline, "", lead, ""]
    for label, value in rows:
        if (value or "").strip():
            lines.append(f"{label}: {value}")
    lines.extend(["", f"Ir al panel de pedidos: {orders_admin_url}", "", footer])
    return subject, "\n".join(lines), html_body, inline_logo
