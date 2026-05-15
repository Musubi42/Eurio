#!/usr/bin/env bash
# Bootstrap MinIO: generate root credentials, start the container, create
# buckets + ACLs, create the application user `eurio-app` with a scoped
# policy, then print the credentials to give to direnv.
#
# Idempotent: re-running is safe. Only generates secrets the first time
# (does not overwrite). Buckets and policies are created with `mc mb -p`
# and `mc admin policy create` which silently no-op on existing entries.
#
# Usage (from /opt/eurio):
#     ./infra/minio/bootstrap.sh
#
# Pre-reqs:
#   - Docker + docker compose plugin
#   - `mc` (minio-client) on PATH OR nix-shell with minio-client
#   - Network `traefik` exists (Traefik docker container running)
#
# Spec: docs/harmonisation-images/server-kickoff.md §"Étapes d'implémentation"

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${INFRA_DIR}/secrets"
POLICY_FILE="${INFRA_DIR}/policies/eurio-app-policy.json"

mkdir -p "${SECRETS_DIR}"
chmod 700 "${SECRETS_DIR}"

gen_secret() {
  local name="$1" value="$2"
  local path="${SECRETS_DIR}/${name}"
  if [[ ! -s "${path}" ]]; then
    printf '%s' "${value}" > "${path}"
    chmod 600 "${path}"
    echo "  generated ${name}"
  else
    echo "  kept existing ${name}"
  fi
}

echo "==> Step 1/5: ensure secrets exist"
gen_secret minio_root_user     "eurio-root"
gen_secret minio_root_password "$(openssl rand -base64 32 | tr -d '/+=' | head -c 40)"
gen_secret eurio_app_user      "eurio-app"
gen_secret eurio_app_password  "$(openssl rand -base64 32 | tr -d '/+=' | head -c 40)"

ROOT_USER=$(<"${SECRETS_DIR}/minio_root_user")
ROOT_PWD=$(<"${SECRETS_DIR}/minio_root_password")
APP_USER=$(<"${SECRETS_DIR}/eurio_app_user")
APP_PWD=$(<"${SECRETS_DIR}/eurio_app_password")

echo "==> Step 2/5: ensure docker network 'traefik' exists"
if ! docker network inspect traefik >/dev/null 2>&1; then
  echo "ERROR: docker network 'traefik' does not exist." >&2
  echo "Make sure your Traefik container is running first." >&2
  exit 1
fi

echo "==> Step 3/5: bring up the MinIO container"
( cd "${INFRA_DIR}" && docker compose up -d )

echo "    waiting for MinIO to accept connections…"
for i in $(seq 1 30); do
  if docker exec eurio-minio mc --version >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Step 4/5: create buckets and ACLs (via container's bundled mc)"
# We use the container's bundled `mc` so this script has zero host-side
# dependency on minio-client. Alias 'local' targets the in-container
# server on http://127.0.0.1:9000 with the root credentials.
docker exec eurio-minio mc alias set local http://127.0.0.1:9000 "${ROOT_USER}" "${ROOT_PWD}" >/dev/null
docker exec eurio-minio mc mb --ignore-existing local/numista-canonical
docker exec eurio-minio mc mb --ignore-existing local/enrichment-raws
docker exec eurio-minio mc mb --ignore-existing local/enrichment-crops
# numista-canonical: anonymous read (served via eurio-images.musubi.dev)
docker exec eurio-minio mc anonymous set download local/numista-canonical
# Disable bucket versioning explicitly (vision §"Décisions actées" #8)
docker exec eurio-minio mc version suspend local/numista-canonical || true
docker exec eurio-minio mc version suspend local/enrichment-raws   || true
docker exec eurio-minio mc version suspend local/enrichment-crops  || true

echo "==> Step 5/5: create app user 'eurio-app' with scoped policy"
# Add user (silently no-ops if user already exists with same key).
docker exec eurio-minio mc admin user add local "${APP_USER}" "${APP_PWD}" >/dev/null
# Create policy from the JSON file (copy it into the container first).
docker cp "${POLICY_FILE}" eurio-minio:/tmp/eurio-app-policy.json
docker exec eurio-minio mc admin policy create local eurio-app-policy /tmp/eurio-app-policy.json >/dev/null 2>&1 || \
  docker exec eurio-minio mc admin policy add    local eurio-app-policy /tmp/eurio-app-policy.json >/dev/null 2>&1 || true
docker exec eurio-minio mc admin policy attach local eurio-app-policy --user "${APP_USER}" >/dev/null 2>&1 || true
docker exec eurio-minio rm -f /tmp/eurio-app-policy.json

echo
echo "============================================================"
echo "MinIO bootstrap OK."
echo
echo "Buckets:"
docker exec eurio-minio mc ls local/ | sed 's/^/  /'
echo
echo "App credentials (put these in your direnv .envrc):"
echo "  export MINIO_ENDPOINT=https://eurio-s3.musubi.dev"
echo "  export MINIO_ACCESS_KEY=${APP_USER}"
echo "  export MINIO_SECRET_KEY=${APP_PWD}"
echo
echo "Verify from a shell with 'mc' installed:"
echo "  mc alias set eurio https://eurio-s3.musubi.dev '${APP_USER}' '${APP_PWD}'"
echo "  mc ls eurio/"
echo "============================================================"
