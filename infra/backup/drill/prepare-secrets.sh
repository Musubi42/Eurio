#!/usr/bin/env bash
# Exercice de restauration — étape 2 de RESTAURATION.md §1 : régénérer les
# identifiants d'infra DEPUIS SOPS, jamais les reprendre du serveur perdu.
# C'est ce que D-29 rend possible : clone + clé age = tout le nécessaire.
#
#   sops exec-env /opt/eurio/secrets/dev.env \
#     "bash infra/backup/drill/prepare-secrets.sh /opt/eurio-restore-test"
set -euo pipefail

WORK="${1:?usage: prepare-secrets.sh <répertoire-de-travail-jetable>}"
# Refuse d'écrire des secrets dans le dépôt : ce répertoire est jetable, il
# vit hors /opt/eurio (protocole §4 point 1).
case "$(readlink -f "$WORK")" in
  /opt/eurio|/opt/eurio/*) echo "❌ répertoire de travail interdit dans le dépôt : $WORK" >&2; exit 2 ;;
esac

umask 077
mkdir -p "$WORK"/{secrets,minio-data,api-data,review-data}
chmod 700 "$WORK/secrets"
cd "$WORK"

put() { printf '%s' "$2" > "secrets/$1"; chmod 600 "secrets/$1"; echo "  $1"; }

# MinIO : root pour le bootstrap, applicatif pour tout le reste.
put minio_root_user       "${MINIO_ROOT_USER:?absent de SOPS}"
put minio_root_password   "${MINIO_ROOT_PASSWORD:?absent de SOPS}"
put eurio_app_user        "${MINIO_ACCESS_KEY:?absent de SOPS}"
put eurio_app_password    "${MINIO_SECRET_KEY:?absent de SOPS}"
# eurio-review (pattern fichiers, cf. infra/review/entrypoint.sh).
put review_admin_token    "${REVIEW_ADMIN_TOKEN:?absent de SOPS}"
put review_session_secret "${REVIEW_SESSION_SECRET:?absent de SOPS}"

echo "→ 6 identifiants écrits depuis SOPS dans $WORK/secrets"
