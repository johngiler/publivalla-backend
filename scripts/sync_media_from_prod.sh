#!/usr/bin/env bash
#
# Pull media/ from production (publivalla-api) into the media/ next to this script's backend.
# One-way only: remote → local directory. Does not upload.
#
# Requires: rsync, SSH Host publivalla-api (same as deploy.sh).
# Remote path: /home/git/backend/media/ on api.publivalla.com.
#
# Usage (from backend/ or anywhere):
#   ./scripts/sync_media_from_prod.sh
#   ./scripts/sync_media_from_prod.sh --delete   # also remove local files absent on the remote
#   ./scripts/sync_media_from_prod.sh --dry-run
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE_HOST="publivalla-api"
REMOTE_PATH="/home/git/backend"
LOCAL_MEDIA="$BACKEND_DIR/media"
REMOTE_MEDIA="$REMOTE_HOST:$REMOTE_PATH/media/"

DELETE=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --delete)
      DELETE=1
      ;;
    --dry-run|-n)
      DRY_RUN=1
      ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      echo "Usage: $0 [--delete] [--dry-run]" >&2
      exit 1
      ;;
  esac
done

if ! command -v rsync >/dev/null 2>&1; then
  echo "ERROR: rsync not found." >&2
  exit 1
fi

mkdir -p "$LOCAL_MEDIA"

RSYNC_OPTS=(-avz -e ssh)
if [[ "$DELETE" -eq 1 ]]; then
  RSYNC_OPTS+=(--delete)
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_OPTS+=(--dry-run)
fi

echo "[sync_media] $REMOTE_MEDIA → $LOCAL_MEDIA/"
rsync "${RSYNC_OPTS[@]}" "$REMOTE_MEDIA" "$LOCAL_MEDIA/"

echo "[sync_media] Done."
