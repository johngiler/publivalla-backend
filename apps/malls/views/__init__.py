"""Vistas HTTP de centros comerciales (catálogo y admin)."""

from apps.malls.views.admin_viewsets import ShoppingCenterAdminViewSet
from apps.malls.views.centers import ShoppingCenterViewSet

__all__ = [
    "ShoppingCenterAdminViewSet",
    "ShoppingCenterViewSet",
]
