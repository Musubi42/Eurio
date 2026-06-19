#!/bin/sh
# Seed le canonique depuis MinIO si absent, puis exec uvicorn.
# Les secrets (MINIO_*) sont injectés en env par `sops exec-env … docker compose up`
# (cf. README.md). Pas de fichiers secrets sur disque — source unique = secrets/dev.env (SOPS).
set -eu

# Sans accès MinIO on ne peut pas seed le canonique → crash tôt.
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY missing — déploie via `sops exec-env`}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY missing — déploie via `sops exec-env`}"

# Seed eurio.db depuis MinIO au 1er boot (no-op si déjà présent dans le volume).
python -m serving.bootstrap_canonical

exec "$@"
