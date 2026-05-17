"""Vistas HTTP de centros y proveedores (catálogo y admin)."""

from apps.malls.views.admin_viewsets import (
    MountingProviderAdminViewSet,
    ShoppingCenterAdminViewSet,
)
from apps.malls.views.centers import ShoppingCenterViewSet

__all__ = [
    "MountingProviderAdminViewSet",
    "ShoppingCenterAdminViewSet",
    "ShoppingCenterViewSet",
]
