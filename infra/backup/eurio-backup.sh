#!/usr/bin/env bash
#
# Eurio — production et vérification du staging de sauvegarde.
#
# Architecture (voir docs/work-in-progress/backup-pipeline/ARCHITECTURE.md) :
#
#   Duplicati est le MOTEUR UNIQUE : transport, chiffrement, rétention,
#   historique. Ce script ne parle pas au distant. Il produit seulement un
#   répertoire de staging que Duplicati ramasse à 03:00 UTC.
#
#   Pourquoi un staging plutôt que pointer Duplicati sur les binds : Duplicati
#   sauvegarde des chemins de fichiers, or ni `eurio.db` (SQLite en WAL) ni
#   MinIO (format objet interne) n'ont le système de fichiers pour surface
#   valide. On matérialise donc des artefacts cohérents et vérifiables.
#
#   staging/
#   ├── eurio.db        VACUUM INTO depuis le conteneur eurio-api      (T1)
#   ├── review.db       VACUUM INTO depuis le conteneur eurio-review   (T1)
#   ├── minio/          miroir rclone par API S3                       (T2) — lot 3
#   └── manifest.json   écrit EN DERNIER : sentinelle + intégrité + comptages
#
#   L'ordre T1 puis T2 n'est pas cosmétique : on capture le store RÉFÉRENÇANT
#   avant le store RÉFÉRENCÉ, pour que le décalage inévitable entre les deux
#   snapshots ne produise que des orphelins (bénins) et jamais des références
#   pendantes (corruption silencieuse à la restauration). Cf. DONNEES.md §3.
#
# Usage :
#   eurio-backup.sh stage                 # produit le staging
#   eurio-backup.sh verify [args...]      # vérifie les invariants du staging
#   eurio-backup.sh help
#
# Restauration : voir README-RESTORE.md.

set -euo pipefail

# ── Self-reexec dans un nix shell si les outils manquent ─────────────────────
# Permet au script d'être portable sur tout système Nix sans setup préalable.
if ! command -v python3 >/dev/null 2>&1 || ! command -v rclone >/dev/null 2>&1; then
  exec nix shell nixpkgs#python3 nixpkgs#rclone --command "$0" "$@"
fi

# ── Config (overridable via env) ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STAGING="${EURIO_BACKUP_STAGING:-$SCRIPT_DIR/staging}"
# La référence vit DANS le staging : sans elle, la non-décroissance est
# inopérante — or c'est le critère d'acceptation d'une restauration (D-13).
# Hors staging, elle disparaîtrait avec la machine qu'elle sert à restaurer.
BASELINE="${EURIO_BACKUP_BASELINE:-$STAGING/baseline-manifest.json}"
# Verrou d'exécution : hors staging, un fichier de verrou n'a rien à faire
# dans l'artefact de sauvegarde.
LOCKFILE="${EURIO_BACKUP_LOCK:-$SCRIPT_DIR/.stage.lock}"

# Bases canoniques : conteneur, chemin dans le conteneur, nom dans le staging.
# ⚠️ Il existe DEUX review.db sur le VPS. Le bon est celui du conteneur
#    eurio-review ; celui de infra/eurio-api/data/ est un résidu de 49 ko sans
#    table `reviewers`. Cf. ETAT-DES-LIEUX.md §1.
EURIO_DB_CONTAINER="${EURIO_DB_CONTAINER:-eurio-api}"
EURIO_DB_PATH="${EURIO_DB_PATH:-/var/lib/eurio/eurio.db}"
REVIEW_DB_CONTAINER="${REVIEW_DB_CONTAINER:-eurio-review}"
REVIEW_DB_PATH="${REVIEW_DB_PATH:-/var/lib/eurio/review.db}"

# Miroir MinIO : lu par l'API S3, jamais depuis le répertoire de données.
# La disposition sur disque de MinIO (`xl.meta` + parts) est un format interne :
# on ne peut pas calculer le sha256 d'un objet sans le réassembler, donc un
# répertoire brut serait invérifiable. Cf. DECISIONS.md D-03.
# Vider la liste (EURIO_BACKUP_BUCKETS=) désactive le miroir : le manifeste
# sortira sans bloc `minio` et `verify` le signalera comme contrôle inopérant.
MINIO_REMOTE="${EURIO_BACKUP_MINIO_REMOTE:-minio}"
# shellcheck disable=SC2206
MIRROR_BUCKETS=(${EURIO_BACKUP_BUCKETS-enrichment-crops enrichment-raws numista-canonical eurio-db})
# Espace libre exigé avant de lancer le miroir (Go). Le premier `sync` écrit
# ~6,3 Go ; un disque plein en cours de route laisserait un miroir tronqué que
# seul l'invariant de cohérence rattraperait, et après coup.
MIN_FREE_GB="${EURIO_BACKUP_MIN_FREE_GB:-10}"

# ── Helpers ──────────────────────────────────────────────────────────────────
die() { echo "❌ $*" >&2; exit 1; }
ok()  { echo "✅ $*"; }

# Snapshot cohérent d'une SQLite en WAL : VACUUM INTO vers un chemin neuf DANS
# le conteneur (la commande échoue si la cible existe), puis docker cp.
# Une copie fichier serait corrompue : le WAL vit à côté de la base.
snapshot_db() {
  local container="$1" src="$2" dest="$3" label="$4"
  local tmp_in_container="/tmp/eurio-stage-$(basename "$dest")"

  docker exec "$container" sh -c "rm -f '$tmp_in_container'" \
    || die "$label : impossible de nettoyer le temporaire dans $container."

  # stdout redirigé : cette fonction ne doit écrire QUE le mtime, qui est
  # capturé par substitution de commande. Une ligne parasite le corromprait.
  docker exec "$container" python -c "
import sqlite3
sqlite3.connect('$src').execute('VACUUM INTO \"$tmp_in_container\"')
" >/dev/null || die "$label : VACUUM INTO a échoué."

  docker cp "$container:$tmp_in_container" "$dest" >/dev/null \
    || die "$label : docker cp a échoué."
  docker exec "$container" rm -f "$tmp_in_container" || true

  # mtime de la SOURCE VIVANTE, pas du snapshot : c'est lui qui dit si les
  # données bougent encore (invariant de vivacité, cf. DECISIONS.md D-17).
  # Un échec ici est bruyant : sans mtime, l'invariant est muet, et un
  # invariant muet qui se lit comme un invariant vert est le défaut qu'on corrige.
  docker exec "$container" python -c "
import os
print(int(os.path.getmtime('$src')))
" || die "$label : relevé du mtime de la source impossible."
}

# Miroir d'un bucket MinIO vers le staging, par l'API S3.
#
# `sync` et non `copy` : le miroir doit être un point-dans-le-temps FIDÈLE, y
# compris pour les suppressions. L'historique n'est pas son travail — c'est
# celui de la rétention Duplicati (D-05). Un miroir qui accumulerait les objets
# supprimés divergerait de la source et rendrait l'invariant d'orphelins muet.
mirror_bucket() {
  local bucket="$1" dest="$2"
  local -a filters=()

  # `eurio-db` est un bucket legacy (data-layer-unification phase 5 prévoit sa
  # suppression). On garde ses artefacts ML — chers à reproduire, ils viennent
  # de runs d'entraînement — mais on EXCLUT sa copie de `eurio.db`, figée au
  # 2026-06-29 : c'est un doublon périmé de ce que le staging capture déjà en
  # frais, et deux `eurio.db` dans une sauvegarde sont un piège de restauration.
  if [ "$bucket" = "eurio-db" ]; then
    filters+=(--exclude "eurio.db" --exclude "eurio.db.*")
  fi

  rclone sync "$MINIO_REMOTE:$bucket" "$dest/$bucket" \
    --fast-list --transfers 8 --stats=30s --stats-one-line \
    "${filters[@]}" \
    || die "miroir du bucket $bucket : rclone sync a échoué."
}

# ── Sous-commandes ───────────────────────────────────────────────────────────

cmd_stage() {
  command -v docker >/dev/null 2>&1 || die "docker absent : impossible de snapshoter les bases."

  local t1
  mkdir -p "$STAGING"

  # Un seul `stage` à la fois : deux passes concurrentes produiraient un
  # staging mi-ancien mi-neuf, que le sha du manifeste signalerait après coup
  # au lieu de l'empêcher.
  exec 9>"$LOCKFILE"
  flock -n 9 || die "un autre 'stage' est déjà en cours ($LOCKFILE)."

  t1="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "=== staging  $t1"
  echo "    destination : $STAGING"
  echo

  # Le manifeste est la sentinelle : on le retire d'abord, pour qu'un staging
  # interrompu en cours de route soit détectable (manifeste absent) plutôt que
  # de laisser un manifeste périmé décrire des fichiers neufs.
  rm -f "$STAGING/manifest.json"

  local mtime_eurio mtime_review
  echo ">>> eurio.db"
  mtime_eurio="$(snapshot_db "$EURIO_DB_CONTAINER" "$EURIO_DB_PATH" "$STAGING/eurio.db" "eurio.db")"
  echo ">>> review.db"
  mtime_review="$(snapshot_db "$REVIEW_DB_CONTAINER" "$REVIEW_DB_PATH" "$STAGING/review.db" "review.db")"

  local -a manifest_args=("$STAGING" --t1 "$t1")
  [ -n "$mtime_eurio" ]  && manifest_args+=(--source-mtime "eurio.db=$mtime_eurio")
  [ -n "$mtime_review" ] && manifest_args+=(--source-mtime "review.db=$mtime_review")

  # ── Miroir MinIO — APRÈS les bases, jamais avant ──────────────────────────
  # Le décalage entre les deux captures est inévitable ; il n'est pas
  # symétrique. Bases puis MinIO ⇒ le miroir est un sur-ensemble de ce que la
  # base référence ⇒ orphelins (bénins). L'ordre inverse produirait des
  # références pendantes, soit une corruption silencieuse à la restauration.
  # Cf. DONNEES.md §3 et DECISIONS.md D-04.
  if [ "${#MIRROR_BUCKETS[@]}" -gt 0 ]; then
    local free_gb
    free_gb="$(df -BG --output=avail "$STAGING" | tail -1 | tr -dc '0-9')"
    [ "${free_gb:-0}" -ge "$MIN_FREE_GB" ] \
      || die "espace libre insuffisant : ${free_gb} Go < ${MIN_FREE_GB} Go exigés."

    echo
    echo ">>> miroir MinIO (${MIRROR_BUCKETS[*]})"
    mkdir -p "$STAGING/minio"
    local bucket
    for bucket in "${MIRROR_BUCKETS[@]}"; do
      echo "  --- $bucket"
      mirror_bucket "$bucket" "$STAGING/minio"
    done
    manifest_args+=(--minio-root "$STAGING/minio" --t2 "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
  fi

  echo
  echo ">>> manifeste"
  python3 "$SCRIPT_DIR/build_manifest.py" "${manifest_args[@]}" || die "construction du manifeste échouée."

  echo
  ok "staging prêt — $(du -sh "$STAGING" | cut -f1)"
  echo "   Vérifier maintenant : $0 verify"
}

cmd_verify() {
  [ -d "$STAGING" ] || die "staging absent : $STAGING — lancer '$0 stage' d'abord."
  python3 "$SCRIPT_DIR/verify_invariants.py" "$STAGING" \
    --baseline "$BASELINE" \
    --repo-root "$REPO_ROOT" \
    "$@"
}

cmd_help() {
  sed -n '/^# Usage :/,/^$/p' "$0" | sed 's/^# \?//'
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "${1:-help}" in
  stage)          cmd_stage ;;
  verify)         shift; cmd_verify "$@" ;;
  help|-h|--help) cmd_help ;;
  *) cmd_help; exit 2 ;;
esac
