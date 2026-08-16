#!/usr/bin/env bash
# Exercice de restauration — étape 4 de RESTAURATION.md §1 : réinjecter les
# objets dans le MinIO de l'exercice, AVANT de poser les bases (le store
# référencé d'abord ; l'inverse produirait des références pendantes).
#
# On écrit avec le compte applicatif `eurio-app` et sa policy, jamais avec le
# compte root : un exercice qui remonte MinIO en root ne teste pas le chemin de
# permissions réel de la production, il le contourne (D-30).
#
#   bash infra/backup/drill/import-objects.sh \
#     /opt/eurio-restore-test /chemin/restauré/minio
set -euo pipefail

WORK="${1:?usage: import-objects.sh <répertoire-de-travail> <restauré>/minio}"
SRC="${2:?usage: import-objects.sh <répertoire-de-travail> <restauré>/minio}"
PORT="${DRILL_S3_PORT:-19000}"

export RCLONE_CONFIG=/dev/null
RC=(rclone
  --s3-provider Minio
  --s3-endpoint "http://127.0.0.1:${PORT}"
  --s3-access-key-id "$(<"$WORK/secrets/eurio_app_user")"
  --s3-secret-access-key "$(<"$WORK/secrets/eurio_app_password")"
)

for bucket in "$SRC"/*/; do
  name="$(basename "$bucket")"
  echo "→ $name"
  "${RC[@]}" sync "$bucket" ":s3:$name" \
    --transfers 12 --checkers 16 --fast-list --stats=30s --stats-one-line
done

echo "→ import terminé"
