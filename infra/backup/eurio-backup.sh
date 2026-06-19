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
# shellcheck disable=SC2206
EURIO_BACKUP_BUCKETS=(${EURIO_BACKUP_BUCKETS:-eurio-db enrichment-crops enrichment-raws numista-canonical})
EURIO_BACKUP_DB_BUCKET="${EURIO_BACKUP_DB_BUCKET:-eurio-db}"
EURIO_BACKUP_DB_OBJECT="${EURIO_BACKUP_DB_OBJECT:-eurio.db}"
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

cmd_run() {
  load_age_key
  local start end b
  start=$(date -Is)
  echo "=== Eurio backup run  $start ==="
  echo "  src    : $EURIO_BACKUP_REMOTE_SRC:"
  echo "  dst    : $EURIO_BACKUP_REMOTE_DST: (rclone crypt over pcloud)"
  echo "  buckets: ${EURIO_BACKUP_BUCKETS[*]}"
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
  echo "=== Sanity sha256 DB ($EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT) ==="
  local tmp h1 h2
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  rclone copyto "$EURIO_BACKUP_REMOTE_SRC:$EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT" "$tmp/from-src.db"  >/dev/null 2>&1
  rclone copyto "$EURIO_BACKUP_REMOTE_DST:$EURIO_BACKUP_DB_BUCKET/$EURIO_BACKUP_DB_OBJECT" "$tmp/from-dst.db" >/dev/null 2>&1
  h1="$(sha256sum "$tmp/from-src.db" | awk '{print $1}')"
  h2="$(sha256sum "$tmp/from-dst.db" | awk '{print $1}')"
  echo "  source : $h1"
  echo "  backup : $h2"
  if [ "$h1" = "$h2" ]; then
    ok "sha256 source ≡ backup"
  else
    echo "❌ sha256 mismatch" >&2
    fail=1
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
