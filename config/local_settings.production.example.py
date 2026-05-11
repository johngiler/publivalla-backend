"""
Plantilla de producción para `local_settings.py` (mismo directorio).

Copia este archivo en el servidor como `config/local_settings.py` (no versionar),
o mantené el `local_settings.py` generado en el repo (gitignored).

Solo aplica ajustes de producción si hay `POSTGRES_DB` y **no** estás en SQLite
(`USE_SQLITE` distinto de true/1/yes), para no romper el .env local de desarrollo.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

POSTGRES_DB = os.environ.get("POSTGRES_DB", "").strip()
_USE_SQLITE = os.environ.get("USE_SQLITE", "").lower() in ("1", "true", "yes")

if POSTGRES_DB and not _USE_SQLITE:
    DEBUG = False
    SECRET_KEY = (
        os.environ.get("DJANGO_SECRET_KEY")
        or os.environ.get("SECRET_KEY")
        or "change-me-in-production"
    )

    # API único multi-tenant (mismo host para todos los owners).
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "api.publivalla.com"]
    _extra_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "") or os.environ.get("ALLOWED_HOSTS", "")
    if _extra_hosts.strip():
        for h in _extra_hosts.split(","):
            h = h.strip()
            if h and h not in ALLOWED_HOSTS:
                ALLOWED_HOSTS.append(h)

    CORS_ALLOW_ALL_ORIGINS = False
    # Incluir un origen por cada subdominio SPA; el API sigue siendo api.publivalla.com.
    CORS_ALLOWED_ORIGINS = [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "https://sambil.publivalla.com",
        "https://nobis.publivalla.com",
    ]
    _cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "") or os.environ.get("CORS_ORIGINS", "")
    if _cors_env.strip():
        for origin in _cors_env.split(","):
            origin = origin.strip()
            if origin and origin not in CORS_ALLOWED_ORIGINS:
                CORS_ALLOWED_ORIGINS.append(origin)

    CSRF_TRUSTED_ORIGINS = [
        "https://sambil.publivalla.com",
        "https://nobis.publivalla.com",
        "https://api.publivalla.com",
    ]
    _csrf_env = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
    if _csrf_env.strip():
        for origin in _csrf_env.split(","):
            origin = origin.strip()
            if origin and origin not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(origin)

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": POSTGRES_DB,
            "USER": os.environ.get("POSTGRES_USER", "sambil"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }

    STATIC_ROOT = BASE_DIR / "staticfiles"

    USE_X_FORWARDED_HOST = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Celery: correo de pedidos en worker (no bloquea Gunicorn). Ejemplo con Redis en el mismo host:
    # CELERY_BROKER_URL=redis://127.0.0.1:6379/0
    # CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
    # CELERY_TASK_ALWAYS_EAGER=false
    # Servicio systemd aparte: celery -A config worker -l info
    # Con broker activo, la «Probar conexión SMTP» en Mi negocio responde 202 y el resultado llega en segundo plano.
    #
    # Redis / Celery (cola obligatoria en producción):
    # CELERY_BROKER_URL=redis://127.0.0.1:6379/0
    # CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
    # CELERY_TASK_ALWAYS_EAGER=false
