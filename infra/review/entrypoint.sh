#!/bin/sh
# Lit les secrets montés en /run/secrets/<name> (pattern infra/minio) et les
# exporte en variables d'environnement attendues par le code, puis exec la
# commande passée (uvicorn par défaut).
#
# Convention : pour chaque VAR, on accepte VAR_FILE pointant vers un fichier.
# Si VAR_FILE est posée, on lit le fichier et on exporte VAR.
set -eu

load_secret() {
    var_name=$1
    file_var_name="${var_name}_FILE"
    # POSIX indirect expansion via eval
    eval "file_path=\${${file_var_name}:-}"
    if [ -n "${file_path}" ] && [ -f "${file_path}" ]; then
        value=$(cat "${file_path}")
        # strip trailing newline
        value=$(printf '%s' "${value}")
        export "${var_name}=${value}"
    fi
}

load_secret REVIEW_ADMIN_TOKEN
load_secret REVIEW_SESSION_SECRET
load_secret MINIO_ACCESS_KEY
load_secret MINIO_SECRET_KEY

# Sanity-check : on refuse de démarrer sans les secrets critiques (mieux vaut
# crasher tôt qu'avoir un service en ligne sans HMAC de session).
: "${REVIEW_ADMIN_TOKEN:?REVIEW_ADMIN_TOKEN missing (set REVIEW_ADMIN_TOKEN_FILE)}"
: "${REVIEW_SESSION_SECRET:?REVIEW_SESSION_SECRET missing (set REVIEW_SESSION_SECRET_FILE)}"
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY missing (set MINIO_ACCESS_KEY_FILE)}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY missing (set MINIO_SECRET_KEY_FILE)}"

exec "$@"
