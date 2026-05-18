"""
Configuración Django — API del marketplace multi-tenant (Publivalla).
"""
import os
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-only")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in ("1", "true", "yes")
# development | production — para logging, checks y futuras reglas (DEBUG sigue viniendo de DJANGO_DEBUG).
DJANGO_ENV = os.environ.get("DJANGO_ENV", "development").strip().lower()
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]
# En DEBUG: subdominios multi-tenant local sin listar cada slug en DJANGO_ALLOWED_HOSTS.
if DEBUG:
    for _suffix in (".localhost", ".lvh.me"):
        if _suffix not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_suffix)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "apps.common.apps.CommonConfig",
    "apps.workspaces.apps.WorkspacesConfig",
    "apps.users.apps.UsersConfig",
    "apps.malls.apps.MallsConfig",
    "apps.providers.apps.ProvidersConfig",
    "apps.ad_spaces.apps.AdSpacesConfig",
    "apps.availability.apps.AvailabilityConfig",
    "apps.clients.apps.ClientsConfig",
    "apps.orders.apps.OrdersConfig",
    "apps.bidding.apps.BiddingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.common.middleware.MediaCrossOriginResourcePolicyMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.workspaces.middleware.TenantMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

if os.environ.get("USE_SQLITE", "").lower() in ("1", "true", "yes"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "publivalla"),
            "USER": os.environ.get("POSTGRES_USER", "publivalla"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
_static_source = BASE_DIR / "static"
STATICFILES_DIRS = [_static_source] if _static_source.is_dir() else []
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Opcional: URL base única del SPA si no aplica `{slug}.{TENANT_BASE_DOMAIN}` (poco habitual).
# En lo normal los enlaces de correo usan ``apps.workspaces.tenant.spa_public_base_url(workspace)``.
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "").strip().rstrip("/")

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@localhost")

# SaaS Publivalla: slug del workspace (tenant) cuando no hay otro contexto (subdominio / header).
# El valor por defecto «acme» es solo convención de desarrollo; en prod suele fijarse por env.
DEFAULT_WORKSPACE_SLUG = os.environ.get(
    "DEFAULT_WORKSPACE_SLUG", "acme").strip().lower() or "acme"
# Dominio apex del producto (ej. publivalla.com). `{slug}.TENANT_BASE_DOMAIN` identifica al owner.
# El API puede ser siempre api.publivalla.com; el tenant se infiere por Origin/Referer del SPA.
# Vacío + DEBUG: el backend infiere apex `localhost` (Origin tipo http://nobis.localhost:3000).
# En producción definí siempre el apex real (p. ej. publivalla.com).
TENANT_BASE_DOMAIN = os.environ.get("TENANT_BASE_DOMAIN", "").strip().lower()

if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOWED_ORIGINS = []
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        o.strip()
        for o in os.environ.get(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if o.strip()
    ]
    _csrf_origins = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
    if _csrf_origins.strip():
        CSRF_TRUSTED_ORIGINS = [
            o.strip() for o in _csrf_origins.split(",") if o.strip()
        ]

# Cabeceras del SPA (`clientTenantSlug`) cuando el API va en host sin subdominio (p. ej. 127.0.0.1:8000).
CORS_ALLOW_HEADERS = (*default_headers, "x-workspace-slug", "x-tenant-slug")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.users.authentication.TenantJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_PAGINATION_CLASS": "apps.common.utils.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_RATES": {
        "guest_checkout": "30/hour",
        "guest_checkout_email": "120/hour",
        "activate_client": "20/hour",
        "validate_password": "120/hour",
        "password_setup_intent": "60/hour",
        "set_initial_password": "30/hour",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "TOKEN_OBTAIN_SERIALIZER": "apps.users.serializers.CustomTokenObtainPairSerializer",
    "TOKEN_REFRESH_SERIALIZER": "apps.users.serializers.CustomTokenRefreshSerializer",
}

# Overrides locales / servidor: `config/settings/local_settings.py` (no versionar).
try:
    from .local_settings import *  # noqa: F403
except ImportError:
    pass

# Celery — correos de pedidos / activación tras `transaction.on_commit`; prueba SMTP en Mi negocio vía worker.
# Sin `CELERY_BROKER_URL`, `CELERY_TASK_ALWAYS_EAGER=True` en Celery, pero el dominio de pedidos **no** usa ese
# camino para correo: `apps/orders/tasks.py` envía en un hilo daemon (PATCH no espera al SMTP). Con broker real,
# las tareas van a la cola y las ejecuta el worker.
CELERY_BROKER_URL = (os.environ.get("CELERY_BROKER_URL") or "").strip()
CELERY_RESULT_BACKEND = (
    (os.environ.get("CELERY_RESULT_BACKEND")
     or "").strip() or CELERY_BROKER_URL or "rpc://"
)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", "120"))
CELERY_TASK_SOFT_TIME_LIMIT = int(
    os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "90"))
CELERY_TASK_EAGER_PROPAGATES = True
_explicit_eager = (os.environ.get("CELERY_TASK_ALWAYS_EAGER",
                   "").lower() in ("1", "true", "yes"))
CELERY_TASK_ALWAYS_EAGER = _explicit_eager or (not CELERY_BROKER_URL)

# En producción, siempre usar Redis/Celery (sin fallback).
if not DEBUG and (os.environ.get("DJANGO_ENV") or "").strip().lower() == "production":
    if not CELERY_BROKER_URL:
        raise RuntimeError(
            "Falta CELERY_BROKER_URL en producción. Configura Redis/Celery para ejecutar "
            "correos transaccionales por cola."
        )
    if CELERY_TASK_ALWAYS_EAGER:
        raise RuntimeError(
            "CELERY_TASK_ALWAYS_EAGER no puede estar activo en producción cuando se exige cola."
        )

# CORS: en producción, cualquier SPA de tenant en `https://{slug}.{TENANT_BASE_DOMAIN}` (workspaces de Publivalla)
# sin listar cada origen en `CORS_ALLOWED_ORIGINS`. Requiere `TENANT_BASE_DOMAIN` (p. ej. publivalla.com).
if not DEBUG and TENANT_BASE_DOMAIN:
    import re as _re_cors

    _apex_esc = _re_cors.escape(TENANT_BASE_DOMAIN.strip().lower())
    _spa_tenant_pattern = rf"^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?\.{_apex_esc}$"
    _cur = list(globals().get("CORS_ALLOWED_ORIGIN_REGEXES") or [])
    if _spa_tenant_pattern not in _cur:
        CORS_ALLOWED_ORIGIN_REGEXES = _cur + [_spa_tenant_pattern]
