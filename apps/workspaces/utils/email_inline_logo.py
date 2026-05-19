"""
Logo del workspace en correos transaccionales (adjunto inline + CID).

Los clientes de correo no muestran SVG de forma fiable en ``<img>``. El PNG dedicado
``logo_png_artifacts`` (Mi negocio) es el único recurso usado para inline/CID.
"""

from __future__ import annotations

from pathlib import Path

# Base del identificador; el adjunto y el ``cid:`` en HTML usan sufijo ``.png`` (Mailgun exige coincidencia exacta).
TENANT_TRANSACTIONAL_EMAIL_LOGO_CID = "tenant-email-logo"


def workspace_email_logo_inline_filename() -> str:
    """Nombre del adjunto inline; debe coincidir con ``src="cid:…"`` en el HTML."""
    return f"{TENANT_TRANSACTIONAL_EMAIL_LOGO_CID}.png"


def prepare_workspace_email_logo_for_inline(ws) -> tuple[bytes, str, str] | None:
    """
    Lee bytes del PNG del tenant para un único adjunto inline por mensaje.

    Retorna ``(raw_bytes, filename_disposition, mime)`` o ``None`` si no hay
    ``logo_png_artifacts`` usable.
    """
    if ws is None:
        return None
    f = getattr(ws, "logo_png_artifacts", None)
    if not f or not getattr(f, "name", None):
        return None
    path = Path(str(f.name))
    if path.suffix.lower() != ".png":
        return None
    try:
        f.open("rb")
        try:
            raw = f.read()
        finally:
            f.close()
    except OSError:
        return None
    if not raw:
        return None
    return (raw, workspace_email_logo_inline_filename(), "image/png")
