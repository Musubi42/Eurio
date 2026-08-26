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
#
# ── Exercice de restauration ────────────────────────────────────────────────
# Trois variables permettent de viser une instance MinIO ISOLÉE au lieu de la
# production. Sans elles, ce script était câblé en dur sur le conteneur
# `eurio-minio` et sur `infra/minio/` : impossible de s'en servir dans un
# exercice de restauration sans toucher la prod, alors que RESTAURATION.md §1
# en fait l'étape 3. Trouvé pendant l'exercice #1 du 2026-08-16.
#
#   MINIO_CONTAINER     nom du conteneur à piloter      (défaut: eurio-minio)
#   MINIO_SECRETS_DIR   où lire/écrire les identifiants (défaut: ./secrets)
#   MINIO_SKIP_COMPOSE  1 = ne pas démarrer le conteneur ni exiger le réseau
#                       `traefik` — l'appelant s'en charge (défaut: vide)

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${MINIO_SECRETS_DIR:-${INFRA_DIR}/secrets}"
POLICY_FILE="${INFRA_DIR}/policies/eurio-app-policy.json"
CONTAINER="${MINIO_CONTAINER:-eurio-minio}"

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

if [[ -n "${MINIO_SKIP_COMPOSE:-}" ]]; then
  echo "==> Steps 2-3/5: sautées (MINIO_SKIP_COMPOSE) — conteneur '${CONTAINER}' fourni par l'appelant"
else
  echo "==> Step 2/5: ensure docker network 'traefik' exists"
  if ! docker network inspect traefik >/dev/null 2>&1; then
    echo "ERROR: docker network 'traefik' does not exist." >&2
    echo "Make sure your Traefik container is running first." >&2
    exit 1
  fi

  echo "==> Step 3/5: bring up the MinIO container"
  ( cd "${INFRA_DIR}" && docker compose up -d )
fi

echo "    waiting for MinIO to accept connections…"
for i in $(seq 1 30); do
  if docker exec "${CONTAINER}" mc --version >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Step 4/5: create buckets and ACLs (via container's bundled mc)"
# We use the container's bundled `mc` so this script has zero host-side
# dependency on minio-client. Alias 'local' targets the in-container
# server on http://127.0.0.1:9000 with the root credentials.
docker exec "${CONTAINER}" mc alias set local http://127.0.0.1:9000 "${ROOT_USER}" "${ROOT_PWD}" >/dev/null
docker exec "${CONTAINER}" mc mb --ignore-existing local/numista-canonical
docker exec "${CONTAINER}" mc mb --ignore-existing local/enrichment-raws
docker exec "${CONTAINER}" mc mb --ignore-existing local/enrichment-crops
# Artefacts de build de l'APK (modèles TFLite, centroïdes, meta) — ADR-004.
# PRIVÉ : contrairement à numista-canonical, aucune policy anonyme n'est posée
# dessus (cf. Step 4). Ce ne sont pas des images publiques.
docker exec "${CONTAINER}" mc mb --ignore-existing local/model-artifacts
# Crops réservés à un corpus d'ÉVALUATION (juge-et-banc, D9). Un bucket à part,
# pas un préfixe dans enrichment-crops : c'est ce qui rend un crop d'éval
# PHYSIQUEMENT inatteignable pour une collecte d'entraînement, quel que soit son
# SQL. PRIVÉ, comme enrichment-crops — aucune policy anonyme.
docker exec "${CONTAINER}" mc mb --ignore-existing local/eval-corpus
# numista-canonical: anonymous read (served via eurio-images.musubi.dev)
docker exec "${CONTAINER}" mc anonymous set download local/numista-canonical
# Disable bucket versioning explicitly (vision §"Décisions actées" #8)
docker exec "${CONTAINER}" mc version suspend local/numista-canonical || true
docker exec "${CONTAINER}" mc version suspend local/enrichment-raws   || true
docker exec "${CONTAINER}" mc version suspend local/enrichment-crops  || true
docker exec "${CONTAINER}" mc version suspend local/model-artifacts   || true
docker exec "${CONTAINER}" mc version suspend local/eval-corpus       || true

echo "==> Step 5/5: create app user 'eurio-app' with scoped policy"
# Add user (silently no-ops if user already exists with same key).
docker exec "${CONTAINER}" mc admin user add local "${APP_USER}" "${APP_PWD}" >/dev/null
# Create policy from the JSON file (copy it into the container first).
docker cp "${POLICY_FILE}" "${CONTAINER}":/tmp/eurio-app-policy.json
docker exec "${CONTAINER}" mc admin policy create local eurio-app-policy /tmp/eurio-app-policy.json >/dev/null 2>&1 || \
  docker exec "${CONTAINER}" mc admin policy add    local eurio-app-policy /tmp/eurio-app-policy.json >/dev/null 2>&1 || true
docker exec "${CONTAINER}" mc admin policy attach local eurio-app-policy --user "${APP_USER}" >/dev/null 2>&1 || true
docker exec "${CONTAINER}" rm -f /tmp/eurio-app-policy.json

echo
echo "============================================================"
echo "MinIO bootstrap OK."
echo
echo "Buckets:"
docker exec "${CONTAINER}" mc ls local/ | sed 's/^/  /'
echo
echo "App credentials:"
echo "  MINIO_ACCESS_KEY=${APP_USER}"
echo "  MINIO_SECRET_KEY → ${SECRETS_DIR}/eurio_app_password (non affiché)"
echo
# Le mot de passe n'est plus imprimé. La source unique est `secrets/dev.env`
# (SOPS) depuis longtemps ; l'afficher le versait dans les journaux, dans
# l'historique du shell et dans les transcripts d'assistant — constaté pendant
# l'exercice de restauration du 2026-08-16, où il a fini dans une trace.
echo "Vérifier depuis un shell avec 'mc' :"
echo "  mc alias set eurio https://eurio-s3.musubi.dev '${APP_USER}' \"\$MINIO_SECRET_KEY\""
echo "  mc ls eurio/"
echo "============================================================"
