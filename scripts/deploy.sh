#!/usr/bin/env bash
#
# Deploy Publivalla backend to api.publivalla.com (publivalla-api).
# Requires: rsync, SSH config Host publivalla-api -> api.publivalla.com, root on remote.
# Target: /home/git/backend (gunicorn via publivalla-api.service).
#
# Server-only files (never overwritten by rsync):
#   .env, .env.production, config/settings/local_settings.py, .venv,
#   db.sqlite3, media/, data/, staticfiles/
#
# Usage:
#   ./scripts/deploy.sh              # full deploy (sync + migrate + restarts)
#   ./scripts/deploy.sh --sync-only  # rsync + chown only (no migrate / collectstatic / restarts)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE_HOST="publivalla-api"
REMOTE_PATH="/home/git/backend"
SYNC_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --sync-only) SYNC_ONLY=1 ;;
    -h|--help)
      echo "Usage: $0 [--sync-only]"
      echo "  --sync-only   rsync + chown only (skip migrate, collectstatic, service restarts)"
      echo "After a full deploy, publivalla-api (gunicorn) restarts always; celery and daphne ask [y/N] (default: no)."
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--sync-only]" >&2
      exit 2
      ;;
  esac
done

RSYNC_EXCLUDE=(
  --exclude ".venv"
  --exclude "__pycache__"
  --exclude "*.pyc"
  --exclude ".env"
  --exclude ".env.production"
  --exclude "config/settings/local_settings.py"
  --exclude "db.sqlite3"
  --exclude "staticfiles"
  --exclude "static"
  --exclude "media"
  --exclude "data"
  --exclude ".git"
  --exclude ".DS_Store"
  --exclude "*.log"
)

cd "$BACKEND_DIR"

echo "[deploy] Syncing backend -> $REMOTE_HOST:$REMOTE_PATH"
rsync -avz --delete "${RSYNC_EXCLUDE[@]}" -e ssh "$BACKEND_DIR/" "$REMOTE_HOST:$REMOTE_PATH/"

echo "[deploy] Fixing ownership on remote..."
# Código bajo git:git; no tocar staticfiles/media aquí (siguen git:www-data entre deploys).
ssh "$REMOTE_HOST" "find $REMOTE_PATH -path $REMOTE_PATH/staticfiles -prune -o -path $REMOTE_PATH/media -prune -o -print0 | xargs -0 -r chown git:git"
# Nginx (www-data) debe poder atravesar el home de git (si no, 403 en /static/ del admin).
ssh "$REMOTE_HOST" "chmod 755 /home/git /home/git/backend"

if [[ "$SYNC_ONLY" -eq 1 ]]; then
  echo "[deploy] Sync-only done (skipped migrate / collectstatic / restarts)."
  exit 0
fi

REMOTE_SETUP="
set -e
cd $REMOTE_PATH

if [[ ! -f .env ]]; then
  echo 'ERROR: $REMOTE_PATH/.env missing on the server.' >&2
  exit 1
fi
if [[ ! -f config/settings/local_settings.py ]]; then
  echo 'ERROR: config/settings/local_settings.py missing. Copy local_settings.production.py on the server.' >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo '[deploy] Creating Python venv...'
  sudo -u git python3 -m venv .venv
fi

sudo -u git .venv/bin/pip install -q -r requirements.txt
sudo -u git .venv/bin/python manage.py check
sudo -u git .venv/bin/python manage.py migrate --noinput
sudo -u git .venv/bin/python manage.py collectstatic --noinput --clear 2>/dev/null || true
"

echo "[deploy] Remote: venv, check, migrate, collectstatic..."
ssh "$REMOTE_HOST" "$REMOTE_SETUP"

# Estáticos y media: propietario git, grupo www-data (Nginx), setgid en dirs.
ssh "$REMOTE_HOST" "for d in $REMOTE_PATH/staticfiles $REMOTE_PATH/media; do [ -d \"\$d\" ] || continue; chown -R git:www-data \"\$d\"; find \"\$d\" -type d -exec chmod 2775 {} \\;; find \"\$d\" -type f -exec chmod 664 {} \\;; done"

echo "[deploy] Restarting publivalla-api.service (gunicorn)..."
if ssh "$REMOTE_HOST" "systemctl is-enabled publivalla-api.service >/dev/null 2>&1"; then
  ssh "$REMOTE_HOST" "systemctl restart publivalla-api.service"
else
  echo "[deploy] WARN: publivalla-api.service systemd unit not installed. On server run:"
  echo "cp scripts/systemd/publivalla-api.service /etc/systemd/system/publivalla-api.service"
  echo "systemctl daemon-reload"
  echo "systemctl enable publivalla-api.service"
  echo "systemctl start publivalla-api.service"
fi

# Daphne — optional restart (default: no). The unit is not installed yet.
read -r -p "[deploy] ¿Reiniciar daphne (WebSockets)? [y/N] " RESTART_DAPHNE
if [[ "${RESTART_DAPHNE}" =~ ^[yY]$ ]]; then
  echo "[deploy] Restarting publivalla-daphne.service (WebSockets)..."
  if ssh "$REMOTE_HOST" "systemctl is-enabled publivalla-daphne.service >/dev/null 2>&1"; then
    ssh "$REMOTE_HOST" "systemctl restart publivalla-daphne.service"
  else
    echo "[deploy] WARN: publivalla-daphne.service not installed yet."
    echo "When the unit exists on the server:"
    echo "cp scripts/systemd/publivalla-daphne.service /etc/systemd/system/publivalla-daphne.service"
    echo "systemctl daemon-reload && systemctl enable --now publivalla-daphne.service"
  fi
else
  echo "[deploy] Daphne left running (no restart)."
fi

if ssh "$REMOTE_HOST" "systemctl is-active nginx >/dev/null 2>&1"; then
  ssh "$REMOTE_HOST" "systemctl reload nginx"
fi

read -r -p "[deploy] ¿Reiniciar celery? [y/N] " RESTART_CELERY
if [[ "${RESTART_CELERY}" =~ ^[yY]$ ]]; then
  echo "[deploy] Restarting publivalla-celery.service..."
  if ssh "$REMOTE_HOST" "systemctl is-enabled publivalla-celery.service >/dev/null 2>&1"; then
    ssh "$REMOTE_HOST" "systemctl restart publivalla-celery.service"
  else
    echo "[deploy] WARN: publivalla-celery.service not installed. On server run:"
    echo "cp scripts/systemd/publivalla-celery.service /etc/systemd/system/publivalla-celery.service"
    echo "systemctl daemon-reload && systemctl enable --now publivalla-celery.service"
  fi
else
  echo "[deploy] Celery worker left running (no restart)."
fi

echo "[deploy] Done. https://api.publivalla.com"
