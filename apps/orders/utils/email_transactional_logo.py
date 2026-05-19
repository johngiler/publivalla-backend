"""
Logo para correos transaccionales (PNG en Mi negocio).

Solo se usa ``Workspace.logo_png_artifacts``, vía ``prepare_workspace_email_logo_for_inline``.
El HTML del correo usa ``workspace_email_logo_header_row`` (CID + fondo base64).
"""

from __future__ import annotations

from apps.workspaces.utils.email_inline_logo import prepare_workspace_email_logo_for_inline


def prepare_workspace_logo_for_transactional_email(ws):
    """Alias con nombre histórico; delega en el PNG dedicado del workspace."""
    return prepare_workspace_email_logo_for_inline(ws)
