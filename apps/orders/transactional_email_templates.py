"""
Plantillas HTML para correos transaccionales (pedidos, activación).

Variables expuestas al contenido: solo datos útiles para quien recibe el correo
(referencia humana del pedido, nombres legibles, estados, enlace de acción).
Sin IDs internos ni jerga técnica en el cuerpo visible.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from pathlib import Path
from typing import Literal

from django.conf import settings

OrderStatusAudience = Literal["client", "admins", "all"]

_MODULE_DIR = Path(__file__).resolve().parent
_BUNDLED_LOGO_SVG = _MODULE_DIR / "pdf_branding" / "logotype.svg"
_REPO_ROOT = Path(settings.BASE_DIR).resolve().parent
_REPO_LOGO_SVG = _REPO_ROOT / "images" / "logos" / "logotype.svg"

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?([0-9a-fA-F]{2})?$")


def _safe(s: str) -> str:
    return html.escape((s or "").strip(), quote=True)


def _cta_background_hex(ws_primary: str | None) -> str:
    raw = (ws_primary or "").strip()
    if _HEX_COLOR.match(raw):
        return raw
    return "#18181b"


def _read_sambil_logotype_data_uri() -> str | None:
    """Mismo activo que los PDFs: SVG empaquetado o copia en el repo."""
    for candidate in (_BUNDLED_LOGO_SVG, _REPO_LOGO_SVG):
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            return (
                "data:image/svg+xml;charset=utf-8,"
                + urllib.parse.quote(text, safe="")
            )
    return None


def _render_transactional_shell(
    *,
    document_title: str,
    headline: str,
    lead: str,
    rows: list[tuple[str, str]],
    cta_url: str,
    cta_label: str,
    footer_note: str,
    accent_hex: str,
) -> str:
    logo = _read_sambil_logotype_data_uri()
    logo_block = (
        f'<img src="{logo}" width="200" alt="Sambil" '
        'style="display:block;margin:0 auto;max-width:200px;height:auto;border:0;outline:none;text-decoration:none;">'
        if logo
        else '<span style="font:700 18px/1.2 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#18181b;">Sambil</span>'
    )

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
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{_safe(document_title)}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f5;-webkit-text-size-adjust:100%;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f4f5;">
    <tr>
      <td align="center" style="padding:28px 14px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border-radius:16px;border:1px solid #e4e4e7;overflow:hidden;">
          <tr>
            <td style="padding:28px 24px 12px;text-align:center;background:#fafafa;border-bottom:1px solid #f4f4f5;">
              {logo_block}
            </td>
          </tr>
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
          <tr>
            <td style="padding:22px 24px 8px;">
              <a href="{_safe(cta_url)}" style="display:inline-block;padding:12px 20px;border-radius:12px;background:{accent};color:#ffffff;font:600 14px/1 system-ui,sans-serif;text-decoration:none;">
                {_safe(cta_label)}
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 24px 28px;border-top:1px solid #f4f4f5;font:12px/1.5 system-ui,sans-serif;color:#71717a;">
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
) -> tuple[str, str, str]:
    """
    Construye asunto, cuerpo texto plano y HTML para aviso de cambio de estado.

    Variables de negocio (todas cadenas legibles):
    - marketplace_title, order_code (vacío si aún no hay código público),
      previous_status_label, new_status_label, company_name, orders_url.
    """
    mp = (marketplace_title or "").strip() or "Marketplace"
    code = (order_code or "").strip()
    prev_l = (previous_status_label or "").strip() or "—"
    new_l = (new_status_label or "").strip() or "—"
    company = (company_name or "").strip() or "—"
    accent = _cta_background_hex(accent_hex)

    ref_phrase = f"Pedido {code}" if code else "Tu pedido"

    if audience == "client":
        subject = f"{mp}: tu pedido pasó a «{new_l}»"
        headline = "Actualización de tu pedido"
        lead = (
            f"El estado de {ref_phrase.lower()} cambió. Ahora figura como «{new_l}»."
            if code
            else f"El estado de tu pedido cambió. Ahora figura como «{new_l}»."
        )
        rows: list[tuple[str, str]] = [
            ("Estado anterior", prev_l),
            ("Estado actual", new_l),
        ]
        if code:
            rows.insert(0, ("Referencia", code))
        footer = (
            "Este mensaje es una notificación automática del marketplace. "
            "Si no esperabas este correo, revisa la actividad de tu cuenta."
        )
    elif audience == "admins":
        subject = f"{mp}: pedido de {company} — «{new_l}»"
        headline = "Cambio de estado en un pedido"
        lead = (
            f"La empresa «{company}» tiene un pedido que avanzó en el flujo. "
            f"El estado actual es «{new_l}»."
        )
        rows = [
            ("Empresa", company),
            ("Estado anterior", prev_l),
            ("Estado actual", new_l),
        ]
        if code:
            rows.insert(1, ("Referencia del pedido", code))
        footer = (
            "Notificación para el equipo del marketplace. "
            "Revisa el detalle en el panel si necesitas tomar acción."
        )
    else:
        subject = f"{mp}: actualización de pedido — «{new_l}»"
        headline = "Actualización de un pedido"
        lead = (
            f"Se registró un cambio de estado en un pedido del marketplace. "
            f"El estado actual es «{new_l}»."
        )
        rows = [
            ("Empresa", company),
            ("Estado anterior", prev_l),
            ("Estado actual", new_l),
        ]
        if code:
            rows.insert(1, ("Referencia del pedido", code))
        footer = "Notificación automática del sistema de pedidos."

    cta_label = "Ir a mis pedidos"
    html_body = _render_transactional_shell(
        document_title=subject,
        headline=headline,
        lead=lead,
        rows=rows,
        cta_url=orders_url,
        cta_label=cta_label,
        footer_note=footer,
        accent_hex=accent,
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
    lines.extend(
        [
            "",
            f"{cta_label}: {orders_url}",
            "",
            footer,
        ]
    )
    text_body = "\n".join(lines)
    return subject, text_body, html_body


def build_client_activation_transactional_email(
    *,
    marketplace_title: str,
    company_name: str,
    contact_first_line: str,
    activation_url: str,
    accent_hex: str | None,
) -> tuple[str, str, str]:
    """Correo de activación tras aprobación (misma envoltura visual)."""
    mp = (marketplace_title or "").strip() or "Marketplace"
    company = (company_name or "").strip() or "tu empresa"
    accent = _cta_background_hex(accent_hex)
    greet = (contact_first_line or "").strip()

    subject = f"{mp}: activa tu acceso al marketplace"
    headline = "Tu solicitud fue aprobada"
    lead_main = (
        f"Puedes crear tu contraseña para entrar con el correo de «{company}» "
        "y gestionar pedidos y reservas."
    )
    lead = f"{greet} {lead_main}".strip() if greet else lead_main

    rows = [("Empresa", company)]
    footer = (
        "El enlace caduca en 14 días. Si ya tienes cuenta, inicia sesión con tu correo. "
        "Este mensaje lo envía el sistema de notificaciones del marketplace."
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
    )

    text_lines = [headline, "", lead, "", f"Crear contraseña: {activation_url}", "", footer]
    return subject, "\n".join(text_lines), html_body
