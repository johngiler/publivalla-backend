#!/usr/bin/env bash
#
# Limpia artefactos locales del backend (caché Python y, opcionalmente, migraciones).
# Objetivo: dejar el árbol listo para regenerar (makemigrations / migrate) o un clone limpio.
#
# Uso:
#   ./scripts/reset_repo.sh              # solo __pycache__ y *.pyc / *.pyo
#   ./scripts/reset_repo.sh --migrations # además borra apps/*/migrations/*.py (no __init__.py)
#   ./scripts/reset_repo.sh -m
#   ./scripts/reset_repo.sh migrations
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

INCLUDE_MIGRATIONS=0

usage() {
  cat <<'EOF'
Uso: reset_repo.sh [opción]

Sin argumentos:
  Elimina directorios __pycache__ y archivos *.pyc / *.pyo bajo backend/ (excluye .venv y .git).

Con migraciones (cualquiera de estas formas):
  --migrations | -m | migrations | --with-migrations
  Además elimina los archivos .py en apps/*/migrations/, excepto __init__.py.

Después de borrar migraciones, regenerar con:
  python manage.py makemigrations
  python manage.py migrate
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h | --help)
      usage
      exit 0
      ;;
    --migrations | -m | migrations | --with-migrations)
      INCLUDE_MIGRATIONS=1
      ;;
    *)
      echo "[reset_repo] Opción desconocida: $arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# find(1) en macOS no admite -path con -prune como en GNU; excluimos .venv y .git por -name.
find_prune_venv_git() {
  find "$BACKEND_DIR" \
    \( -path "$BACKEND_DIR/.venv" -o -path "$BACKEND_DIR/.git" \) -prune \
    -o "$@" -print
}

echo "[reset_repo] Backend: $BACKEND_DIR"

pycache_dirs=0
while IFS= read -r dir; do
  [[ -z "$dir" ]] && continue
  rm -rf "$dir"
  pycache_dirs=$((pycache_dirs + 1))
done < <(find_prune_venv_git -type d -name __pycache__)

pyc_files=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  rm -f "$file"
  pyc_files=$((pyc_files + 1))
done < <(find_prune_venv_git \( -name '*.pyc' -o -name '*.pyo' \) -type f)

echo "[reset_repo] Eliminados: ${pycache_dirs} directorio(s) __pycache__, ${pyc_files} archivo(s) .pyc/.pyo"

if [[ "$INCLUDE_MIGRATIONS" -eq 1 ]]; then
  migration_files=0
  migrations_root="$BACKEND_DIR/apps"
  if [[ -d "$migrations_root" ]]; then
    while IFS= read -r file; do
      [[ -z "$file" ]] && continue
      rm -f "$file"
      migration_files=$((migration_files + 1))
    done < <(
      find "$migrations_root" -path '*/migrations/*.py' -type f ! -name '__init__.py' -print
    )
  fi
  echo "[reset_repo] Eliminados: ${migration_files} archivo(s) de migración en apps/*/migrations/"
  echo "[reset_repo] Recuerda: python manage.py makemigrations && python manage.py migrate"
else
  echo "[reset_repo] Migraciones intactas (usa --migrations para borrarlas también)"
fi

echo "[reset_repo] Listo."
