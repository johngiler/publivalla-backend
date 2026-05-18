from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

# Texto para <title> y atributo alt del logo (sin mostrar «Django administration» en cabecera).
admin.site.site_header = _("Administración")
admin.site.site_title = _("Admin")
admin.site.index_title = _("Inicio")
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from apps.ad_spaces.views import AdSpaceAdminViewSet, AdSpaceViewSet
from apps.clients.views import (
    ClientViewSet,
    MyCompanyView,
    MyContractsView,
    MyFavoriteDetailView,
    MyFavoritesView,
)
from apps.malls.views import ShoppingCenterAdminViewSet, ShoppingCenterViewSet
from apps.availability.views import AvailabilityBlockAdminViewSet
from apps.providers.views import MountingProviderAdminViewSet
from apps.orders.views import (
    AdminMarketplaceContractsView,
    GuestCheckoutClientEmailCheckView,
    GuestCheckoutDatosValidateView,
    GuestCheckoutEmailCheckView,
    GuestCheckoutView,
    OrderViewSet,
)
from apps.users.views import (
    ActivateClientAccountView,
    MePasswordView,
    MeView,
    PasswordSetupIntentView,
    SetInitialPasswordView,
    UserAdminViewSet,
    ValidatePasswordView,
)
from apps.workspaces.views import (
    AdminDashboardActivityView,
    AdminDashboardStatsView,
    MyWorkspaceTransactionalRelayTestView,
    MyWorkspaceTransactionalSmtpTestStatusView,
    MyWorkspaceTransactionalSmtpTestView,
    MyWorkspaceView,
    WorkspaceCurrentView,
)

router = DefaultRouter()
router.register(r"centers", ShoppingCenterViewSet, basename="center")
router.register(r"spaces", AdSpaceViewSet, basename="space")
router.register(r"clients", ClientViewSet, basename="client")
router.register(r"orders", OrderViewSet, basename="order")

router.register(r"admin/centers", ShoppingCenterAdminViewSet, basename="admin-center")
router.register(
    r"admin/mounting-providers",
    MountingProviderAdminViewSet,
    basename="admin-mounting-provider",
)
router.register(r"admin/spaces", AdSpaceAdminViewSet, basename="admin-space")
router.register(
    r"admin/availability-blocks",
    AvailabilityBlockAdminViewSet,
    basename="admin-availability-block",
)
router.register(r"admin/users", UserAdminViewSet, basename="admin-user")

catalog_router = DefaultRouter()
catalog_router.register(r"centers", ShoppingCenterViewSet, basename="catalog-center")
catalog_router.register(r"spaces", AdSpaceViewSet, basename="catalog-space")

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "api/checkout/guest/check-email/",
        GuestCheckoutEmailCheckView.as_view(),
        name="guest-checkout-check-email",
    ),
    path(
        "api/checkout/guest/check-client-email/",
        GuestCheckoutClientEmailCheckView.as_view(),
        name="guest-checkout-check-client-email",
    ),
    path(
        "api/checkout/guest/validate-datos/",
        GuestCheckoutDatosValidateView.as_view(),
        name="guest-checkout-validate-datos",
    ),
    path("api/checkout/guest/", GuestCheckoutView.as_view(), name="guest-checkout"),
    path("api/auth/activate-client/", ActivateClientAccountView.as_view(), name="activate-client"),
    path("api/auth/validate-password/", ValidatePasswordView.as_view(), name="validate-password"),
    path(
        "api/auth/password-setup-intent/",
        PasswordSetupIntentView.as_view(),
        name="password-setup-intent",
    ),
    path(
        "api/auth/set-initial-password/",
        SetInitialPasswordView.as_view(),
        name="set-initial-password",
    ),
    path("api/", include(router.urls)),
    path("api/catalog/", include(catalog_router.urls)),
    path("api/me/company/", MyCompanyView.as_view(), name="my-company"),
    path("api/me/contracts/", MyContractsView.as_view(), name="my-contracts"),
    path("api/me/favorites/", MyFavoritesView.as_view(), name="my-favorites"),
    path(
        "api/me/favorites/<int:ad_space_id>/",
        MyFavoriteDetailView.as_view(),
        name="my-favorite-detail",
    ),
    path("api/me/workspace/", MyWorkspaceView.as_view(), name="me-workspace"),
    path(
        "api/me/workspace/test-transactional-smtp/status/<str:task_id>/",
        MyWorkspaceTransactionalSmtpTestStatusView.as_view(),
        name="me-workspace-test-transactional-smtp-status",
    ),
    path(
        "api/me/workspace/test-transactional-smtp/",
        MyWorkspaceTransactionalSmtpTestView.as_view(),
        name="me-workspace-test-transactional-smtp",
    ),
    path(
        "api/me/workspace/test-transactional-relay/",
        MyWorkspaceTransactionalRelayTestView.as_view(),
        name="me-workspace-test-transactional-relay",
    ),
    path("api/workspace/current/", WorkspaceCurrentView.as_view(), name="workspace-current"),
    path(
        "api/admin/dashboard/stats/",
        AdminDashboardStatsView.as_view(),
        name="admin-dashboard-stats",
    ),
    path(
        "api/admin/dashboard/activity/",
        AdminDashboardActivityView.as_view(),
        name="admin-dashboard-activity",
    ),
    path(
        "api/admin/contracts/",
        AdminMarketplaceContractsView.as_view(),
        name="admin-marketplace-contracts",
    ),
    path("api/auth/me/", MeView.as_view(), name="auth-me"),
    path("api/auth/me/password/", MePasswordView.as_view(), name="auth-me-password"),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
