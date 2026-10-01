#!/usr/bin/env bash
#
# Dump the Postgres database configured in backend/.env
# Works on LOCAL / PRODUCTION (same .env contract).
#
# Usage (from backend/ or anywhere):
#   ./scripts/backup_db.sh
#
# Output: data/db/YYYYMMDD-HHMMSS.sql
#
# If container publivalla-postgres-local is running, dumps via docker exec so the
# dump tools match the server major version (avoids client/server SET mismatches).
# On the API server (native Postgres) it uses pg_dump on the host.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$BACKEND_DIR/.env"
OUT_DIR="$BACKEND_DIR/data/db"
DOCKER_CONTAINER="${PUBLIVALLA_PG_CONTAINER:-publivalla-postgres-local}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

# shellcheck source=/dev/null
set -a
source "$ENV_FILE"
set +a

for v in POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD; do
  if [[ -z "${!v:-}" ]]; then
    echo "ERROR: $v not set in .env" >&2
    exit 1
  fi
done

HOST="${POSTGRES_HOST:-127.0.0.1}"
PORT="${POSTGRES_PORT:-5432}"

mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_FILE="$OUT_DIR/${STAMP}.sql"

export PGPASSWORD="$POSTGRES_PASSWORD"

use_docker=0
if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$DOCKER_CONTAINER"; then
    use_docker=1
  fi
fi

echo "[backup_db] Dumping $POSTGRES_DB @ ${HOST}:${PORT} → $OUT_FILE"

if [[ "$use_docker" -eq 1 ]]; then
  echo "[backup_db] Using docker exec on $DOCKER_CONTAINER (matches server tools)"
  docker exec \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    "$DOCKER_CONTAINER" \
    pg_dump \
      --username="$POSTGRES_USER" \
      --dbname="$POSTGRES_DB" \
      --format=plain \
      --no-owner \
      --no-acl \
    >"$OUT_FILE"
else
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "ERROR: pg_dump not found. Install PostgreSQL client tools." >&2
    exit 1
  fi
  pg_dump \
    --host="$HOST" \
    --port="$PORT" \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --format=plain \
    --no-owner \
    --no-acl \
    --file="$OUT_FILE"
fi

SIZE="$(wc -c < "$OUT_FILE" | tr -d ' ')"
echo "[backup_db] Done (${SIZE} bytes)."
echo "$OUT_FILE"
