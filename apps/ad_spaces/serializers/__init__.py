"""Serializers DRF de `ad_spaces`; implementación en submódulos."""

from .admin_serializers import AdSpaceAdminSerializer
from apps.providers.serializers import CatalogMountingProviderSerializer

from .catalog import AdSpaceSerializer, MOUNTING_PROVIDERS_PAGE_SIZE
from .product_types import AdSpaceProductTypeSerializer

__all__ = (
    "AdSpaceAdminSerializer",
    "AdSpaceProductTypeSerializer",
    "AdSpaceSerializer",
    "CatalogMountingProviderSerializer",
    "MOUNTING_PROVIDERS_PAGE_SIZE",
)
