#!/usr/bin/env bash
# Sambil: subir malls a /home/git/malls con slugs sin espacios ni caracteres raros.
#
# Estructura en servidor:
#   /home/git/malls/scr/images/   + catalog.pdf
#   /home/git/malls/sla/images/   + catalog.pdf
#   …
#
# Mac:
#   ./scripts/sambil_malls_upload_and_seed.sh upload-reset   # borra y sube todo
#   ./scripts/sambil_malls_upload_and_seed.sh audit-local
# Servidor:
#   ./scripts/sambil_malls_upload_and_seed.sh print-seed

set -euo pipefail

# Usa el alias de ~/.ssh/config (p. ej. publivalla-api → api.publivalla.com).
REMOTE_HOST="${REMOTE_HOST:-publivalla-api}"
IDENTITY_FILE="${IDENTITY_FILE:-$HOME/.ssh/id_rsa_v2}"
REMOTE_MALLS="${REMOTE_MALLS:-/home/git/malls}"
LOCAL_DOWNLOADS="${LOCAL_DOWNLOADS:-/Users/jcgiler/Downloads}"
BACKEND_REMOTE="${BACKEND_REMOTE:-/home/git/backend}"

# slug | carpeta imágenes en Downloads | nombre exacto del PDF en Downloads
MALL_ROWS=(
  "scr|Sambil Chacao|Sambil Caracas.pdf"
  "sla|Sambil La Candelaria|Sambil La Candelaria.pdf"
  "svl|Sambil Valencia|Sambil Valencia .pdf"
  "smr|Sambil Maracaibo|Sambil Maracaibo .pdf"
  "smg|Sambil Margarita|sambil Margarita.pdf"
  "sbr|Sambil Barquisimeto|Sambil Barquisimeto.pdf"
  "ssn|Sambil San Cristóbal|Sambil San Cristobal.pdf"
)

SSH_OPTS=(
  -o BatchMode=yes
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=120
  -o TCPKeepAlive=yes
  -o ConnectTimeout=30
)

ssh_cmd() {
  ssh "${SSH_OPTS[@]}" "${REMOTE_HOST}" "$@"
}

# Una sola cadena para rsync -e (evita trocear opciones SSH).
RSYNC_SSH=()
if [[ -f "${IDENTITY_FILE}" ]]; then
  RSYNC_SSH=(ssh -i "${IDENTITY_FILE}" "${SSH_OPTS[@]}")
else
  RSYNC_SSH=(ssh "${SSH_OPTS[@]}")
fi

RSYNC_RETRY_MAX="${RSYNC_RETRY_MAX:-4}"
RSYNC_RETRY_WAIT="${RSYNC_RETRY_WAIT:-12}"
MALL_PAUSE_SEC="${MALL_PAUSE_SEC:-6}"

rsync_retry() {
  local attempt=1
  local err=0
  while (( attempt <= RSYNC_RETRY_MAX )); do
    if rsync -avz --partial --timeout=300 -e "${RSYNC_SSH[*]}" "$@"; then
      return 0
    fi
    err=$?
    if (( attempt >= RSYNC_RETRY_MAX )); then
      return "${err}"
    fi
    echo "  rsync intento ${attempt}/${RSYNC_RETRY_MAX} falló; reintento en ${RSYNC_RETRY_WAIT}s…" >&2
    sleep "${RSYNC_RETRY_WAIT}"
    attempt=$((attempt + 1))
  done
  return "${err}"
}

# Subida de imágenes en un solo stream SSH (menos cortes que muchos archivos rsync).
tar_upload_images_stream() {
  local src_dir="$1"
  local remote_images="$2"
  local attempt=1
  export COPYFILE_DISABLE=1
  while (( attempt <= RSYNC_RETRY_MAX )); do
    if tar -C "${src_dir}" -czf - --no-xattrs . 2>/dev/null \
      | ssh "${SSH_OPTS[@]}" "${REMOTE_HOST}" "tar -xzf - -C '${remote_images}'"; then
      return 0
    fi
    if tar -C "${src_dir}" -czf - . \
      | ssh "${SSH_OPTS[@]}" "${REMOTE_HOST}" "tar -xzf - -C '${remote_images}'"; then
      return 0
    fi
    if (( attempt >= RSYNC_RETRY_MAX )); then
      return 1
    fi
    echo "  tar stream intento ${attempt}/${RSYNC_RETRY_MAX} falló; reintento en ${RSYNC_RETRY_WAIT}s…" >&2
    sleep "${RSYNC_RETRY_WAIT}"
    attempt=$((attempt + 1))
  done
}

# Archivo único + rsync --partial: mejor para carpetas grandes (p. ej. ssn ~120MB).
tar_upload_images_archive() {
  local src_dir="$1"
  local remote_images="$2"
  local archive_local="$3"
  local slug="$4"
  local remote_tgz="/tmp/sambil-${slug}-images.tar.gz"
  export COPYFILE_DISABLE=1
  echo "  empaquetando localmente…"
  if ! tar -C "${src_dir}" -czf "${archive_local}" --no-xattrs . 2>/dev/null; then
    tar -C "${src_dir}" -czf "${archive_local}" .
  fi
  rsync_retry "${archive_local}" "$(remote_target "${remote_tgz}")"
  ssh_cmd "tar -xzf '${remote_tgz}' -C '${remote_images}' && rm -f '${remote_tgz}'"
}

tar_upload_images() {
  local src_dir="$1"
  local remote_images="$2"
  local archive_local="$3"
  local slug="$4"
  local size_mb
  size_mb="$(du -sm "${src_dir}" | awk '{print $1}')"
  if [[ "${size_mb:-0}" -ge 80 ]]; then
    tar_upload_images_archive "${src_dir}" "${remote_images}" "${archive_local}" "${slug}"
  else
    tar_upload_images_stream "${src_dir}" "${remote_images}"
  fi
}

remote_target() {
  local path="$1"
  echo "${REMOTE_HOST}:${path}"
}

remote_reset() {
  echo "→ Reiniciando ${REMOTE_MALLS} en el servidor..."
  ssh_cmd "rm -rf '${REMOTE_MALLS}' && mkdir -p '${REMOTE_MALLS}' && chown -R git:git '${REMOTE_MALLS}'"
}

upload_one_mall() {
  local slug="$1"
  local local_dir="$2"
  local pdf_name="$3"
  local src_dir="${LOCAL_DOWNLOADS}/${local_dir}"
  local src_pdf="${LOCAL_DOWNLOADS}/${pdf_name}"
  local remote_base="${REMOTE_MALLS}/${slug}"
  local remote_images="${remote_base}/images"
  local staging=""
  staging="$(mktemp -d "${TMPDIR:-/tmp}/sambil-upload.XXXXXX")"

  if [[ ! -d "${src_dir}" ]]; then
    rm -rf "${staging}"
    echo "OMITIDO (sin carpeta): ${src_dir}" >&2
    return 0
  fi
  if [[ ! -f "${src_pdf}" ]]; then
    echo "OMITIDO (sin PDF): ${src_pdf}" >&2
    rm -rf "${staging}"
    return 0
  fi

  # PDF en ruta sin espacios ni comillas en el destino remoto.
  cp -f "${src_pdf}" "${staging}/catalog.pdf"

  echo "→ [${slug}] preparar remoto"
  ssh_cmd "mkdir -p '${remote_images}' && chown -R git:git '${remote_base}'"

  echo "→ [${slug}] imágenes: ${local_dir}"
  tar_upload_images "${src_dir}" "${remote_images}" "${staging}/images.tar.gz" "${slug}"

  echo "→ [${slug}] PDF → catalog.pdf"
  rsync_retry "${staging}/catalog.pdf" "$(remote_target "${remote_base}/catalog.pdf")"

  ssh_cmd "chown -R git:git '${remote_base}'" || echo "AVISO: chown ${slug} falló (los archivos ya están subidos)." >&2
  rm -rf "${staging}"
  sleep "${MALL_PAUSE_SEC}"
}

upload_all() {
  for row in "${MALL_ROWS[@]}"; do
    IFS='|' read -r slug local_dir pdf_name <<< "${row}"
    upload_one_mall "${slug}" "${local_dir}" "${pdf_name}" || {
      echo "ERROR en ${slug}; reintenta: $0 upload-one ${slug}" >&2
      return 1
    }
  done
  echo ""
  echo "Subida completa. Verifica:"
  ssh_cmd "find '${REMOTE_MALLS}' -maxdepth 2 | sort; echo '---'; du -sh ${REMOTE_MALLS}/* 2>/dev/null | sort"
}

upload_reset() {
  remote_reset
  sleep 5
  upload_all
}

upload_missing() {
  local slug remote_images count need_pdf need_imgs
  for row in "${MALL_ROWS[@]}"; do
    IFS='|' read -r slug _ _ <<< "${row}"
    remote_images="${REMOTE_MALLS}/${slug}/images"
    need_pdf=0
    need_imgs=0
    if ! ssh_cmd "test -s '${REMOTE_MALLS}/${slug}/catalog.pdf'"; then
      need_pdf=1
    fi
    if ! count="$(ssh_cmd "find '${remote_images}' -type f 2>/dev/null | wc -l")"; then
      echo "AVISO: no se pudo comprobar ${slug} (SSH); se omite." >&2
      continue
    fi
    count="${count//[[:space:]]/}"
    if [[ "${count:-0}" -lt 1 ]]; then
      need_imgs=1
    fi
    if [[ "${need_pdf}" -eq 0 && "${need_imgs}" -eq 0 ]]; then
      continue
    fi
    echo "→ subir ${slug} (pdf=${need_pdf}, imágenes=${need_imgs}, remoto=${count:-0} archivos)"
    upload_one "${slug}" || return 1
  done
  echo ""
  echo "Comprobación:"
  ssh_cmd "find '${REMOTE_MALLS}' -maxdepth 2 | sort; echo '---'; du -sh ${REMOTE_MALLS}/* 2>/dev/null | sort"
}

upload_one() {
  local slug="${1:-}"
  if [[ -z "${slug}" ]]; then
    echo "Uso: $0 upload-one <slug>   (scr sla svl smr smg sbr ssn)" >&2
    exit 1
  fi
  for row in "${MALL_ROWS[@]}"; do
    IFS='|' read -r s local_dir pdf_name <<< "${row}"
    if [[ "${s}" == "${slug}" ]]; then
      upload_one_mall "${s}" "${local_dir}" "${pdf_name}"
      return 0
    fi
  done
  echo "Slug desconocido: ${slug}" >&2
  exit 1
}

upload() {
  upload_reset
}

print_seed() {
  cat <<EOF
# Ejecutar en el servidor (${BACKEND_REMOTE}), uno por uno.
# Rutas sin espacios: /home/git/malls/<slug>/catalog.pdf y .../images/

EOF

  local n=1
  for row in "${MALL_ROWS[@]}"; do
    IFS='|' read -r slug local_dir pdf_name <<< "${row}"
  local pdf_path="${REMOTE_MALLS}/${slug}/catalog.pdf"
  local images_path="${REMOTE_MALLS}/${slug}/images"
  local prefix
  prefix="$(printf '%s' "${slug}" | tr '[:lower:]' '[:upper:]')"
  local extra="--center-slug ${slug} --code-prefix ${prefix} --center-name \"${local_dir}\""
  local label="${slug}"
  case "${slug}" in
    scr) label="Chacao (PDF Caracas, slug scr)" ;;
    sla) label="La Candelaria (slug sla)" ;;
    svl) label="Valencia (slug svl)" ;;
    smr) label="Maracaibo (slug smr)" ;;
    smg) label="Margarita (slug smg)" ;;
    sbr) label="Barquisimeto (slug sbr)" ;;
    ssn) label="San Cristóbal (slug ssn)" ;;
  esac

  echo "# --- ${n}) ${label} ---"
  echo "# Con catalog.pdf hace falta --center-slug, --code-prefix y --center-name (nombre en columna 2 del script)."
  echo "cd ${BACKEND_REMOTE} && .venv/bin/python manage.py audit_catalog_seed_images \\"
  echo "  --workspace-slug sambil \\"
  echo "  --pdf ${pdf_path} \\"
  echo "  --images-dir ${images_path} \\"
  echo "  ${extra}"
  echo ""
  echo "cd ${BACKEND_REMOTE} && .venv/bin/python manage.py seed_production_catalog \\"
  echo "  --workspace-slug sambil \\"
  echo "  --pdf ${pdf_path} \\"
  echo "  --images-dir ${images_path} \\"
  echo "  --force \\"
  echo "  ${extra}"
  echo ""
  n=$((n + 1))
  done
}

audit_local() {
  local root
  root="$(cd "$(dirname "$0")/.." && pwd)"
  cd "${root}"

  for row in "${MALL_ROWS[@]}"; do
    IFS='|' read -r slug local_dir pdf_name <<< "${row}"
    local prefix
    prefix="$(printf '%s' "${slug}" | tr '[:lower:]' '[:upper:]')"
    echo "======== ${slug} (${local_dir}) ========"
    .venv/bin/python manage.py audit_catalog_seed_images \
      --workspace-slug sambil \
      --pdf "${LOCAL_DOWNLOADS}/${pdf_name}" \
      --images-dir "${LOCAL_DOWNLOADS}/${local_dir}" \
      --center-slug "${slug}" \
      --code-prefix "${prefix}" \
      --center-name "${local_dir}" || true
    echo ""
  done
}

case "${1:-print-seed}" in
  upload-reset|upload) upload_reset ;;
  upload-only) upload_all ;;
  upload-missing) upload_missing ;;
  upload-one) upload_one "${2:-}" ;;
  print-seed) print_seed ;;
  audit-local) audit_local ;;
  *)
    echo "Uso: $0 upload-reset|upload|upload-only|upload-missing|upload-one <slug>|print-seed|audit-local"
    exit 1
    ;;
esac
