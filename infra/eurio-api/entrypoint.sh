#!/bin/sh
# Charge les secrets fichiers (/run/secrets/<name>) → env, seed le canonique
# depuis MinIO si absent, puis exec uvicorn. Pattern identique à infra/review.
set -eu

load_secret() {
    var_name=$1
    eval "file_path=\${${var_name}_FILE:-}"
    if [ -n "${file_path}" ] && [ -f "${file_path}" ]; then
        export "${var_name}=$(cat "${file_path}")"
    fi
}

load_secret MINIO_ACCESS_KEY
load_secret MINIO_SECRET_KEY

# Sans accès MinIO on ne peut pas seed le canonique → crash tôt.
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY missing (set MINIO_ACCESS_KEY_FILE)}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY missing (set MINIO_SECRET_KEY_FILE)}"

# Seed eurio.db depuis MinIO au 1er boot (no-op si déjà présent dans le volume).
python -m serving.bootstrap_canonical

exec "$@"
