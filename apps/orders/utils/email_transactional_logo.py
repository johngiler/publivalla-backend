"""
Logo para correos transaccionales (adjunto CID).

Solo se usa ``Workspace.logo_png_artifacts`` (PNG en Mi negocio), vía
``prepare_workspace_email_logo_for_inline``. El logotipo vectorial en ``logo`` /
``logo_mark`` queda para web; no se rasteriza en el servidor.
"""

from __future__ import annotations

from apps.workspaces.utils.email_inline_logo import prepare_workspace_email_logo_for_inline


def prepare_workspace_logo_for_transactional_email(ws):
    """Alias con nombre histórico; delega en el PNG dedicado del workspace."""
    return prepare_workspace_email_logo_for_inline(ws)
