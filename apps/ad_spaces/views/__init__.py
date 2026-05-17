"""Vistas HTTP de tomas (catálogo y admin)."""

from apps.ad_spaces.views.admin_viewsets import AdSpaceAdminViewSet
from apps.ad_spaces.views.spaces import AdSpaceViewSet

__all__ = ["AdSpaceAdminViewSet", "AdSpaceViewSet"]
