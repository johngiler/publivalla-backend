"""Acceso al catálogo público de tomas (según modelo ShoppingCenter)."""


def shopping_center_allows_public_catalog(center) -> bool:
    """Centro activo con catálogo de marketplace habilitado en BD."""
    return bool(
        getattr(center, "marketplace_catalog_enabled", False)
        and getattr(center, "is_active", False)
    )
