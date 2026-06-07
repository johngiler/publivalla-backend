"""Vistas HTTP de clientes (admin de empresas, catálogo «Mi empresa», favoritos)."""

from apps.clients.views.admin_clients import ClientViewSet, MyCompanyView
from apps.clients.views.my_company_brands import (
    MyCompanyBrandDetailView,
    MyCompanyBrandListCreateView,
)
from apps.clients.views.my_company_members import (
    MyCompanyMemberDetailView,
    MyCompanyMemberListCreateView,
)
from apps.clients.views.marketplace_client import (
    MyContractsView,
    MyFavoriteDetailView,
    MyFavoritesView,
)

__all__ = [
    "ClientViewSet",
    "MyCompanyBrandDetailView",
    "MyCompanyBrandListCreateView",
    "MyCompanyMemberDetailView",
    "MyCompanyMemberListCreateView",
    "MyCompanyView",
    "MyContractsView",
    "MyFavoriteDetailView",
    "MyFavoritesView",
]
