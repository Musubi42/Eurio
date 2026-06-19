#!/bin/sh
# Vérifie les secrets nécessaires aux assets MinIO (images, screenshots), puis
# exec uvicorn. Les migrations DB (CREATE TABLE IF NOT EXISTS) sont appliquées
# par le startup hook FastAPI dans server_serve.py — pas par cet entrypoint.
#
# Cold-start d'un VPS vierge : restore d'un backup (`infra/backup/eurio-backup.sh`),
# pas seed MinIO. Le pattern legacy (`bootstrap_canonical.py`) est supprimé
# en C2 de la refonte auth-redesign — cf. DESIGN.md §9.2.
set -eu

: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY missing — déploie via direnv ou sops exec-env}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY missing — déploie via direnv ou sops exec-env}"

exec "$@"
