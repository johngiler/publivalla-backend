#!/usr/bin/env bash

set -e

export DEBIAN_FRONTEND=noninteractive

echo "[setup] Updating apt..."
apt-get update -qq

echo "[setup] Installing system packages..."
apt-get install -y \
  postgresql postgresql-contrib \
  nginx \
  certbot python3-certbot-nginx \
  python3 python3-venv python3-dev python3-pip \
  libpq-dev \
  git

echo "[setup] Ensuring user git and directory..."
id git 2>/dev/null || useradd -m -s /bin/bash git
mkdir -p /home/git/backend /home/git/backend/media
chown -R git:git /home/git
chmod 755 /home/git /home/git/backend
# Nginx lee /static y /media como www-data: grupo en esas carpetas + setgid (collectstatic hereda grupo).
chown git:www-data /home/git/backend/media
chmod 2775 /home/git/backend/media
usermod -a -G www-data git 2>/dev/null || true

echo "[setup] Allowing nginx to read letsencrypt challenges..."
mkdir -p /var/www/letsencrypt
chown -R www-data:www-data /var/www/letsencrypt

echo "[setup] Done. Next steps:"
echo "  1. Copiar código del backend a /home/git/backend (clone o rsync inicial)"
echo "  2. Copiar .env a /home/git/backend/.env"
echo "  3. Copiar config/settings/local_settings.production.example.py -> /home/git/backend/config/settings/local_settings.py"
echo "  4. Ejecutar scripts/init_db.sh (como root o postgres) para crear la base"
echo "  5. Como git: cd /home/git/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
echo "  6. migrate y: .venv/bin/python manage.py ensure_default_workspace  (workspace placeholder acme)"
echo "  7. Instalar scripts/nginx/nginx-api-http-only.conf, certbot, luego scripts/nginx/nginx-api.publivalla.com.conf, scripts/systemd/publivalla-api.service y scripts/systemd/publivalla-celery.service"
