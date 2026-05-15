#!/usr/bin/env bash
# One-shot rsync of the local image filesystem from the dev Mac to this
# VPS, before the migration script (`migrate_to_minio`) reads them.
#
# Designed to be run FROM THE MAC (push to the VPS), not from the VPS.
# Reason: SSH on the VPS doesn't necessarily have credentials to pull
# from the Mac, but the Mac always has credentials to push to the VPS.
#
# Usage (from the Mac, in any directory):
#
#   ./rsync-from-mac.sh [--apply]
#
# Default is dry-run. Pass --apply to actually transfer.
#
# What gets synced:
#   ml/datasets/                  ← canonical Numista referential
#   ml/state/sources/             ← scraped raws + crops (the bulk)
#
# What does NOT get synced:
#   ml/cache/                     ← transient augmentation outputs (vision §P5)
#   ml/state/training.db*         ← per-machine, never shared
#   ml/state/sources_runs.json    ← per-machine state (sources-refacto D-06)
#   anything else under ml/state/
#
# Idempotent — re-running only sends deltas. Use --delete to mirror
# (be careful: removes files on the VPS that are absent on the Mac).
#
# Spec: docs/harmonisation-images/vision.md §"Architecture cible"

set -euo pipefail

# ── Configurable ────────────────────────────────────────────────────────────
# Edit these three lines to match your local setup.

VPS_HOST="${VPS_HOST:-vps}"                 # SSH alias for the VPS
VPS_USER="${VPS_USER:-dontpanic}"           # remote user
MAC_REPO="${MAC_REPO:-${HOME}/dev/eurio}"   # repo path on the Mac

# These rarely change.
VPS_REPO="${VPS_REPO:-/opt/eurio}"

# ── ────────────────────────────────────────────────────────────────────────

APPLY=""
DELETE=""
for arg in "$@"; do
  case "${arg}" in
    --apply)  APPLY="yes" ;;
    --delete) DELETE="--delete" ;;
    -h|--help)
      sed -n '1,40p' "$0" | grep -E '^#' | sed 's/^# *//' | head -40
      exit 0
      ;;
    *) echo "unknown arg: ${arg}" >&2; exit 1 ;;
  esac
done

DRY_FLAG="--dry-run"
[[ -n "${APPLY}" ]] && DRY_FLAG=""

# Sanity: source dirs exist on the Mac.
for sub in ml/datasets ml/state/sources; do
  if [[ ! -d "${MAC_REPO}/${sub}" ]]; then
    echo "WARN: ${MAC_REPO}/${sub} does not exist on this Mac — skipping." >&2
  fi
done

if [[ -z "${APPLY}" ]]; then
  echo ">>> DRY-RUN (pass --apply to transfer)"
fi
echo "    Mac : ${MAC_REPO}/ml/{datasets,state/sources}"
echo "    VPS : ${VPS_USER}@${VPS_HOST}:${VPS_REPO}/ml/{datasets,state/sources}"
[[ -n "${DELETE}" ]] && echo "    --delete is ON (will remove VPS files absent on Mac)"
echo

# Common rsync flags:
#   -a archive (perms, times, links — but not owner since users differ)
#   -h human-readable progress
#   -v verbose
#   --info=progress2 single-line progress
#   --partial keep partial file on interruption (resume next run)
#   --no-owner --no-group don't try to preserve uid/gid across machines
COMMON=(-a -h -v --info=progress2 --partial --no-owner --no-group ${DELETE} ${DRY_FLAG})

if [[ -d "${MAC_REPO}/ml/datasets" ]]; then
  echo "── ml/datasets/ ──────────────────────────────────────────────"
  rsync "${COMMON[@]}" \
    "${MAC_REPO}/ml/datasets/" \
    "${VPS_USER}@${VPS_HOST}:${VPS_REPO}/ml/datasets/"
fi

if [[ -d "${MAC_REPO}/ml/state/sources" ]]; then
  echo
  echo "── ml/state/sources/ (raws + crops) ─────────────────────────"
  # Ensure the parent dir exists on the VPS.
  ssh "${VPS_USER}@${VPS_HOST}" "mkdir -p ${VPS_REPO}/ml/state/sources"
  rsync "${COMMON[@]}" \
    "${MAC_REPO}/ml/state/sources/" \
    "${VPS_USER}@${VPS_HOST}:${VPS_REPO}/ml/state/sources/"
fi

echo
if [[ -z "${APPLY}" ]]; then
  echo ">>> DRY-RUN complete. Re-run with --apply to actually transfer."
else
  echo ">>> Sync done. Next: from the VPS, run:"
  echo "    cd ${VPS_REPO}/ml && ../.venv/bin/python -m scripts.migrate_to_minio inventory"
fi
