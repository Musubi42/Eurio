#!/usr/bin/env bash
#
# Eurio MinIO backup → pCloud (rclone crypt, clé Age).
#
# Architecture (voir infra/backup/README.md) :
#   - Source     : MinIO `eurio-s3.musubi.dev` (4 buckets)
#   - Destination: pCloud, dossier `backups/serverOimNix/Eurio/`
#   - Chiffrement: rclone `crypt` (contenu chiffré, noms de fichiers en clair)
#   - Secret     : clé privée Age, lue au runtime depuis ~/.config/eurio-backup/age-key.txt
#                  (jamais dans le Nix store, jamais committée)
#
# Le script ne contient AUCUN secret. Il lit la clé Age sur disque au runtime
# et la passe à rclone via env vars (RCLONE_CONFIG_<NAME>_PASSWORD).
#
# Usage :
#   eurio-backup.sh keygen                # one-time: générer la clé Age
#   eurio-backup.sh run                   # backup les 4 buckets
#   eurio-backup.sh verify                # check --one-way + sha256 DB
#   eurio-backup.sh upload-readme         # uploade README-RESTORE.md sur pCloud (clair)
#   eurio-backup.sh rclone <args...>      # escape hatch (rclone avec env vars set)
#
# Restauration : voir README-RESTORE.md (à la racine du backup pCloud).

set -euo pipefail

# ── Self-reexec dans un nix shell si rclone/age manquants en PATH ────────────
# Permet au script d'être portable sur tout système Nix sans setup préalable.
if ! command -v rclone >/dev/null 2>&1 || ! command -v age-keygen >/dev/null 2>&1; then
  exec nix shell nixpkgs#rclone nixpkgs#age --command "$0" "$@"
fi

# ── Config (overridable via env) ─────────────────────────────────────────────
EURIO_BACKUP_AGE_KEY="${EURIO_BACKUP_AGE_KEY:-$HOME/.config/eurio-backup/age-key.txt}"
EURIO_BACKUP_REMOTE_SRC="${EURIO_BACKUP_REMOTE_SRC:-minio}"
EURIO_BACKUP_REMOTE_DST="${EURIO_BACKUP_REMOTE_DST:-pcloud_crypt}"
# Buckets MinIO = IMAGES uniquement (Modèle B / R2 : la DB n'est plus dans MinIO).
# shellcheck disable=SC2206
EURIO_BACKUP_BUCKETS=(${EURIO_BACKUP_BUCKETS:-enrichment-crops enrichment-raws numista-canonical})
# Canonique eurio.db : sauvegardé DIRECTEMENT depuis le conteneur eurio-api du VPS
# (writer unique, Model B/R2) → pCloud crypt, sous le même chemin `eurio-db/eurio.db`
# (layout de restauration inchangé). Plus de détour MinIO.
EURIO_BACKUP_DB_BUCKET="${EURIO_BACKUP_DB_BUCKET:-eurio-db}"
EURIO_BACKUP_DB_OBJECT="${EURIO_BACKUP_DB_OBJECT:-eurio.db}"
EURIO_BACKUP_DB_CONTAINER="${EURIO_BACKUP_DB_CONTAINER:-eurio-api}"
EURIO_BACKUP_DB_PATH="${EURIO_BACKUP_DB_PATH:-/var/lib/eurio/eurio.db}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Helpers ──────────────────────────────────────────────────────────────────
die() { echo "❌ $*" >&2; exit 1; }
ok()  { echo "✅ $*"; }

load_age_key() {
  [ -f "$EURIO_BACKUP_AGE_KEY" ] || die "Clé Age absente : $EURIO_BACKUP_AGE_KEY
   → Restaurer depuis Bitwarden (entry 'Eurio backup Age key') ou bout de papier.
   → Voir infra/backup/README-RESTORE.md."

  local age_secret age_salt
  age_secret="$(grep '^AGE-SECRET-KEY-' "$EURIO_BACKUP_AGE_KEY" || true)"
  [ -n "$age_secret" ] || die "Format invalide : pas de ligne 'AGE-SECRET-KEY-' dans $EURIO_BACKUP_AGE_KEY"

  # Salt dérivé déterministe : sha256(secret + suffixe). Permet à rclone crypt
  # d'avoir un password2 distinct du password sans secret supplémentaire.
  age_salt="$(printf '%s-salt' "$age_secret" | sha256sum | awk '{print $1}')"

  # rclone obscure pour env var (encodage non secret mais format attendu par rclone).
  export RCLONE_CONFIG_PCLOUD_CRYPT_PASSWORD
  export RCLONE_CONFIG_PCLOUD_CRYPT_PASSWORD2
  RCLONE_CONFIG_PCLOUD_CRYPT_PASSWORD="$(rclone obscure "$age_secret")"
  RCLONE_CONFIG_PCLOUD_CRYPT_PASSWORD2="$(rclone obscure "$age_salt")"
}

# ── Subcommands ──────────────────────────────────────────────────────────────

cmd_keygen() {
  if [ -f "$EURIO_BACKUP_AGE_KEY" ]; then
    die "Clé Age existe déjà : $EURIO_BACKUP_AGE_KEY
   → Si tu veux régénérer (ATTENTION : invalide TOUT le backup chiffré existant),
     supprimer le fichier manuellement d'abord."
  fi
  local dir
  dir="$(dirname "$EURIO_BACKUP_AGE_KEY")"
  mkdir -p "$dir"
  chmod 700 "$dir"
  age-keygen -o "$EURIO_BACKUP_AGE_KEY"
  chmod 400 "$EURIO_BACKUP_AGE_KEY"
  echo
  ok "Clé générée : $EURIO_BACKUP_AGE_KEY"
  echo
  echo "📋 SAUVEGARDER LA CLÉ MAINTENANT :"
  echo "   1. Bitwarden — entry suggérée 'Eurio backup Age key'"
  echo "      → copier le contenu intégral du fichier"
  echo "   2. Papier (optionnel) — noter la ligne AGE-SECRET-KEY-1..."
  echo
  echo "   Sans cette clé, le backup pCloud est IRRÉCUPÉRABLE."
  echo
  echo "── Contenu de la clé ──"
  cat "$EURIO_BACKUP_AGE_KEY"
  echo "──────────────────────"
}

# Snapshot cohérent du canonique eurio.db (VACUUM INTO sous WAL, dans le conteneur)
# → pCloud crypt sous `eurio-db/eurio.db` (+ `.sha256` sidecar pour le verify).
# Model B / R2 : la DB n'est plus dans MinIO, on la sauvegarde direct du writer.
backup_canonical_db() {
  echo ">>> canonical eurio.db  $(date -Is)"
  command -v docker >/dev/null 2>&1 || die "docker absent : impossible de snapshot le canonique."
  local tmp snap sha
  tmp="$(mktemp -d)"
  snap="$tmp/eurio.db"
  # VACUUM INTO un chemin neuf DANS le conteneur (échoue si la cible existe).
  docker exec "$EURIO_BACKUP_DB_CONTAINER" sh -c \
    "rm -f /tmp/eurio-backup-snap.db && python -c \"import sqlite3; sqlite3.connect('$EURIO_BACKUP_DB_PATH').execute('VACUUM INTO \\\"/tmp/eurio-backup-snap.db\\\"')\"" \
    || die "VACUUM INTO du canonique a échoué."
  docker cp "$EURIO_BACKUP_DB_CONTAINER:/tmp/eurio-backup-snap.db" "$snap" || die "docker cp du snapshot a échoué."
  docker exec "$EURIO_BACKUP_DB_CONTAINER" rm -f /tmp/eurio-backup-snap.db || true
  sha="$(sha256sum "$snap" | awk '{print $1}')"
  echo "$sha" > "$tmp/eurio.db.sha256"
  rclone copyto "$snap" "$EURIO_BACKUP_REMOTE_DST:$EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT"
  rclone copyto "$tmp/eurio.db.sha256" "$EURIO_BACKUP_REMOTE_DST:$EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT.sha256"
  rm -rf "$tmp"
  echo "<<< canonical eurio.db  sha=${sha:0:12}…  $(date -Is)"
}

cmd_run() {
  load_age_key
  local start end b
  start=$(date -Is)
  echo "=== Eurio backup run  $start ==="
  echo "  src    : $EURIO_BACKUP_REMOTE_SRC: (images) + conteneur $EURIO_BACKUP_DB_CONTAINER (canonique)"
  echo "  dst    : $EURIO_BACKUP_REMOTE_DST: (rclone crypt over pcloud)"
  echo "  buckets: ${EURIO_BACKUP_BUCKETS[*]}"
  echo
  backup_canonical_db
  echo
  for b in "${EURIO_BACKUP_BUCKETS[@]}"; do
    echo ">>> $b  $(date -Is)"
    rclone copy "$EURIO_BACKUP_REMOTE_SRC:$b" "$EURIO_BACKUP_REMOTE_DST:$b/" \
      --fast-list --transfers 8 --stats=10s --stats-one-line
    echo "<<< $b  rc=$?  $(date -Is)"
  done
  end=$(date -Is)
  echo "=== Eurio backup run END  $end ==="
}

cmd_verify() {
  load_age_key
  echo "=== Eurio backup verify  $(date -Is) ==="
  local b fail=0
  for b in "${EURIO_BACKUP_BUCKETS[@]}"; do
    echo "--- $b ---"
    echo -n "  source : "; rclone size "$EURIO_BACKUP_REMOTE_SRC:$b" 2>&1 | tail -2 | tr '\n' ' '; echo
    echo -n "  backup : "; rclone size "$EURIO_BACKUP_REMOTE_DST:$b" 2>&1 | tail -2 | tr '\n' ' '; echo
    if rclone check "$EURIO_BACKUP_REMOTE_SRC:$b" "$EURIO_BACKUP_REMOTE_DST:$b" --one-way 2>&1 | tail -5; then
      :
    else
      fail=1
    fi
  done

  echo
  echo "=== Sanity sha256 canonique ($EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT) ==="
  # Model B/R2 : le canonique change en continu → on ne compare PAS à une source
  # vivante. On vérifie que le BACKUP est intact/restaurable : sha recalculé du
  # fichier sauvegardé ≡ sidecar `.sha256` poussé en même temps que lui.
  local tmp got want
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  rclone copyto "$EURIO_BACKUP_REMOTE_DST:$EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT" "$tmp/backup.db" >/dev/null 2>&1
  rclone copyto "$EURIO_BACKUP_REMOTE_DST:$EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT.sha256" "$tmp/backup.db.sha256" >/dev/null 2>&1
  if [ ! -s "$tmp/backup.db" ] || [ ! -s "$tmp/backup.db.sha256" ]; then
    echo "❌ backup canonique introuvable (lance d'abord 'run')" >&2
    fail=1
  else
    got="$(sha256sum "$tmp/backup.db" | awk '{print $1}')"
    want="$(tr -d '[:space:]' < "$tmp/backup.db.sha256")"
    echo "  backup   : $got"
    echo "  sidecar  : $want"
    if [ "$got" = "$want" ]; then
      ok "sha256 backup ≡ sidecar (restaurable)"
    else
      echo "❌ sha256 mismatch (backup corrompu)" >&2
      fail=1
    fi
  fi

  [ "$fail" -eq 0 ] && ok "verify OK" || die "verify FAIL"
}

cmd_upload_readme() {
  load_age_key
  local readme="$SCRIPT_DIR/README-RESTORE.md"
  [ -f "$readme" ] || die "README-RESTORE.md introuvable : $readme"
  # Uploader EN CLAIR sur pCloud, à la racine du backup (et non via crypt).
  # → on contourne pcloud_crypt et on écrit directement sur pcloud:
  local target="pcloud:backups/serverOimNix/Eurio/README-RESTORE.md"
  echo "Uploading $readme → $target (CLAIR, hors crypt)"
  rclone copyto "$readme" "$target"
  ok "README-RESTORE.md publié en clair sur pCloud : $target"
}

cmd_rclone() {
  load_age_key
  exec rclone "$@"
}

cmd_help() {
  sed -n '2,/^set -euo/p' "$0" | sed -n '/^# Usage/,/^#$/p' | sed 's/^# \?//'
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "${1:-help}" in
  keygen)        cmd_keygen ;;
  run)           cmd_run ;;
  verify)        cmd_verify ;;
  upload-readme) cmd_upload_readme ;;
  rclone)        shift; cmd_rclone "$@" ;;
  help|-h|--help) cmd_help ;;
  *) cmd_help; exit 2 ;;
esac
