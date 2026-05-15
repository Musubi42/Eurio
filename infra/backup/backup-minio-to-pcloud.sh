#!/usr/bin/env bash
# Weekly backup: tar the 3 MinIO buckets and push to pCloud, overwriting
# the previous archive (no versioning, single-archive policy per
# vision §"Décisions actées" #7).
#
# Invoked by the systemd timer defined in nix/eurio-vps.nix.
#
# Env (loaded from /etc/eurio/backup.env via NixOS EnvironmentFile):
#   NTFY_TOPIC      — ntfy.sh topic for success / failure pings
#   RCLONE_REMOTE   — rclone remote name (default: pcloud)
#   PCLOUD_PATH     — destination path (default: eurio-backup/eurio-minio.tar)
#   DATA_DIR        — MinIO data dir (default: /opt/eurio/infra/minio/data)
#   STAGE_DIR       — staging dir for the tar (default: /var/tmp)

set -euo pipefail

DATE=$(date -u +%FT%TZ)
LOG="${LOG:-/var/log/eurio-backup.log}"
NTFY_TOPIC="${NTFY_TOPIC:-}"
RCLONE_REMOTE="${RCLONE_REMOTE:-pcloud}"
PCLOUD_PATH="${PCLOUD_PATH:-eurio-backup/eurio-minio.tar}"
DATA_DIR="${DATA_DIR:-/opt/eurio/infra/minio/data}"
STAGE_DIR="${STAGE_DIR:-/var/tmp}"
TAR="${STAGE_DIR}/eurio-minio.tar"

notify() {
  [[ -z "${NTFY_TOPIC}" ]] && return 0
  curl -sf -d "$1" "https://ntfy.sh/${NTFY_TOPIC}" >/dev/null || true
}

trap 'notify "❌ Eurio MinIO backup FAILED at ${DATE}"; exit 1' ERR

{
  echo "============================================================"
  echo "Backup start: ${DATE}"
  echo "  data dir : ${DATA_DIR}"
  echo "  tar      : ${TAR}"
  echo "  remote   : ${RCLONE_REMOTE}:${PCLOUD_PATH}"

  # Sanity: data dir exists and contains the 3 buckets.
  for bucket in numista-canonical enrichment-raws enrichment-crops; do
    if [[ ! -d "${DATA_DIR}/${bucket}" ]]; then
      echo "ERROR: missing bucket dir ${DATA_DIR}/${bucket}" >&2
      exit 1
    fi
  done

  # Sanity: enough free space to stage the tar (assume tar ~= data size).
  data_kb=$(du -sk "${DATA_DIR}" | awk '{print $1}')
  free_kb=$(df -k --output=avail "${STAGE_DIR}" | tail -1)
  echo "  data size: $((data_kb/1024)) MiB"
  echo "  free stage: $((free_kb/1024)) MiB"
  if (( free_kb < data_kb + 1048576 )); then
    echo "ERROR: not enough free space in ${STAGE_DIR} (need ~${data_kb} KiB + 1 GiB headroom)" >&2
    exit 1
  fi

  # Tar the 3 buckets into a single archive.
  echo "  tarring…"
  tar cf "${TAR}" -C "${DATA_DIR}" \
      numista-canonical enrichment-raws enrichment-crops
  ls -lh "${TAR}"

  # Push to pCloud, overwriting any prior version.
  echo "  pushing to pCloud…"
  rclone copyto "${TAR}" "${RCLONE_REMOTE}:${PCLOUD_PATH}" \
      --progress --stats=30s

  size_human=$(rclone size "${RCLONE_REMOTE}:${PCLOUD_PATH}" 2>/dev/null \
                 | grep -oE '[0-9.]+ ?[KMGT]?(iB|B)' | head -1 || echo "?")

  rm -f "${TAR}"
  echo "Backup done: ${DATE} (remote size: ${size_human})"
  echo "============================================================"
  notify "✅ Eurio MinIO backup OK ${DATE} (${size_human})"
} >> "${LOG}" 2>&1
