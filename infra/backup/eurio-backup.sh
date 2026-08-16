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
#   eurio-backup.sh notify-test           # teste les anneaux de notification
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
MIRROR_BUCKETS=(${EURIO_BACKUP_BUCKETS-enrichment-crops enrichment-raws numista-canonical model-artifacts eurio-db})
# Espace libre exigé avant de lancer le miroir (Go). Le premier `sync` écrit
# ~6,3 Go ; un disque plein en cours de route laisserait un miroir tronqué que
# seul l'invariant de cohérence rattraperait, et après coup.
MIN_FREE_GB="${EURIO_BACKUP_MIN_FREE_GB:-10}"

# Points de notification (cf. notify.conf.example). Absents = anneaux
# desactives, et le script le dit — un anneau silencieusement absent serait
# exactement le defaut qu'on corrige.
NOTIFY_CONF="${EURIO_BACKUP_NOTIFY_CONF:-$SCRIPT_DIR/notify.conf}"
KUMA_STAGING_URL=""; KUMA_VERIFY_URL=""; HEALTHCHECKS_URL=""; KUMA_DRILL_URL=""
# shellcheck source=/dev/null
[ -f "$NOTIFY_CONF" ] && . "$NOTIFY_CONF"

# ── Helpers ──────────────────────────────────────────────────────────────────
die() { echo "❌ $*" >&2; exit 1; }
ok()  { echo "✅ $*"; }

# Le binaire curl, résolu explicitement — même piège que DOCKER_HOST.
#
# Le PATH d'un service systemd est celui déclaré dans `nix/eurio-vps.nix`, et
# RIEN d'autre : il ne contenait pas curl. Les quatre anneaux répondaient donc
# « INJOIGNABLE » à chaque exécution automatique alors qu'ils répondent 200
# depuis un shell interactif. Conséquence vécue le 2026-08-16 : la sentinelle a
# parfaitement détecté l'absence de manifeste, et personne ne l'a su.
#
# Résolu ici et pas seulement dans l'unité, pour que ça vaille aussi pour cron,
# un appel hors profil, ou un système où le rebuild n'a pas encore eu lieu.
CURL=""
resolve_curl() {
  if command -v curl >/dev/null 2>&1; then CURL="curl"; return 0; fi
  local c
  for c in /run/current-system/sw/bin/curl /usr/bin/curl /bin/curl; do
    [ -x "$c" ] && { CURL="$c"; return 0; }
  done
}
resolve_curl

# Battement de coeur vers un push monitor.
#
# Le job ne pousse PAS son etat : il pousse un battement, et c'est Kuma qui
# possede l'alerte (D-06). Detecter une absence est un travail de machine ;
# demander au dispositif d'annoncer sa propre mort ne marche pas.
#
# Une notification qui echoue ne fait JAMAIS echouer la sauvegarde — mais elle
# le dit. L'inverse (echouer la sauvegarde parce que Kuma est down) serait
# absurde ; le silence, lui, serait le defaut qu'on corrige.
#
# Le 5e parametre est le DIALECTE, et il n'est pas cosmetique :
#
#   kuma : l'etat passe en parametre de requete (?status=up|down).
#   hc   : healthchecks.io ignore les parametres de requete. L'etat est porte
#          par le CHEMIN — `<url>` = succes, `<url>/fail` = echec. Envoyer
#          `?status=down` a l'URL de base y enregistre donc un SUCCES : l'anneau
#          dirait « tout va bien » au moment precis ou tout va mal, et le test
#          afficherait un vert rassurant. C'est la panne silencieuse que ce
#          chantier entier combat, logee dans le detecteur lui-meme.
notify() {
  local url="$1" status="$2" msg="$3" label="$4" flavor="${5:-kuma}"
  if [ -z "$url" ]; then
    echo "   ⚠️  anneau « $label » non configuré (voir $NOTIFY_CONF) — aucune alerte ne partira"
    return 0
  fi
  if [ "$flavor" = "hc" ] && [ "$status" = "down" ]; then
    url="${url%/}/fail"
  fi
  if [ -z "$CURL" ]; then
    echo "   ⚠️  $label : curl INTROUVABLE — aucun anneau ne peut partir (PATH=$PATH)" >&2
    return 0
  fi
  if "$CURL" -fsS -m 15 --get "$url" \
       --data-urlencode "status=$status" \
       --data-urlencode "msg=$msg" >/dev/null 2>&1; then
    echo "   → $label : $status"
  else
    echo "   ⚠️  $label : notification INJOIGNABLE (le job continue)" >&2
  fi
}

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

# ── Docker rootless ──────────────────────────────────────────────────────────

# Le VPS fait tourner Docker en mode **rootless** : les conteneurs Eurio vivent
# sur la socket de l'utilisateur (`/run/user/<uid>/docker.sock`), pas sur celle
# de root. Un shell interactif l'apprend par `DOCKER_HOST`, posé dans le profil.
# Un service systemd **système** ne charge pas ce profil : `docker` retombe donc
# sur `/var/run/docker.sock`, où aucun conteneur Eurio n'existe.
#
# Symptôme vécu le 2026-08-16 : `docker exec eurio-api` répond
# « No such container: eurio-api » alors que `docker ps` le montre dans le shell.
# Le timer de staging avait tourné UNE fois et échoué ainsi ; zéro succès depuis
# son installation, et la notification d'alerte était elle-même injoignable —
# donc personne n'a rien su.
#
# On résout ici plutôt que dans l'unité systemd pour que ça vaille aussi pour
# cron, un appel manuel hors profil, ou une autre machine. Un `DOCKER_HOST`
# déjà posé gagne toujours : on ne fait que combler un vide.
resolve_docker_host() {
  [ -n "${DOCKER_HOST:-}" ] && return 0
  local sock="/run/user/$(id -u)/docker.sock"
  if [ -S "$sock" ]; then
    export DOCKER_HOST="unix://$sock"
    echo "    docker : socket rootless — DOCKER_HOST=$DOCKER_HOST"
  fi
}

# Vérifie qu'on parle bien au démon qui héberge les conteneurs attendus.
# `command -v docker` ne prouvait que la présence du binaire — pas qu'il
# s'adresse au bon démon, ce qui est exactement ce qui a échoué.
require_container() {
  local name="$1"
  docker inspect -f '{{.State.Running}}' "$name" >/dev/null 2>&1 \
    || die "conteneur '$name' introuvable sur ${DOCKER_HOST:-le démon par défaut}.
   Docker rootless ? Les conteneurs d'un autre utilisateur ne sont pas visibles.
   Vérifier : docker ps | grep $name"
}

# ── Sous-commandes ───────────────────────────────────────────────────────────

cmd_stage() {
  command -v docker >/dev/null 2>&1 || die "docker absent : impossible de snapshoter les bases."
  resolve_docker_host
  # Les deux conteneurs sont vérifiés AVANT de commencer : découvrir au
  # deuxième snapshot que le démon n'est pas le bon laisserait un staging
  # à moitié produit, que la sentinelle signalerait sans dire pourquoi.
  require_container "$EURIO_DB_CONTAINER"
  require_container "$REVIEW_DB_CONTAINER"

  local t1
  mkdir -p "$STAGING"

  # Un seul `stage` à la fois : deux passes concurrentes produiraient un
  # staging mi-ancien mi-neuf, que le sha du manifeste signalerait après coup
  # au lieu de l'empêcher.
  exec 9>"$LOCKFILE"
  flock -n 9 || die "un autre 'stage' est déjà en cours ($LOCKFILE)."

  # La notification part quoi qu'il arrive, y compris si `stage` meurt en
  # cours de route. Sans trap, un echec au milieu ne produirait AUCUN signal —
  # et le silence est indiscernable du succes.
  #
  # stage_rc est GLOBAL, jamais `local` : le trap EXIT s'execute APRES le
  # retour de cmd_stage, donc apres la disparition de toute variable locale.
  # En `local`, les deux sous-shells du trap echouaient sur `unbound variable`
  # (set -u) et notify partait avec un statut VIDE — que Kuma interprete comme
  # un succes. Le declencheur d'alerte annoncait donc « tout va bien » au
  # moment precis ou stage venait de mourir. Trouve en execution reelle, pas
  # par la suite de tests : elle n'exerce pas le chemin d'echec du trap.
  stage_rc=1
  trap 'notify "$KUMA_STAGING_URL" \
        "$([ $stage_rc -eq 0 ] && echo up || echo down)" \
        "$([ $stage_rc -eq 0 ] && echo "staging OK" || echo "stage a echoue (rc=$stage_rc)")" \
        "eurio-staging"' EXIT

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
  stage_rc=0
  ok "staging prêt — $(du -sh "$STAGING" | cut -f1)"
  echo "   Vérifier maintenant : $0 verify"
}

cmd_verify() {
  [ -d "$STAGING" ] || die "staging absent : $STAGING — lancer '$0 stage' d'abord."

  local rc=0
  python3 "$SCRIPT_DIR/verify_invariants.py" "$STAGING" \
    --baseline "$BASELINE" \
    --repo-root "$REPO_ROOT" \
    "$@" || rc=$?

  echo
  if [ "$rc" -eq 0 ]; then
    notify "$KUMA_VERIFY_URL" up "invariants OK" "eurio-verify"
    # healthchecks.io n'est pingé QUE si tout est vert. C'est un dead man's
    # switch hors site : son silence doit vouloir dire « quelque chose ne va
    # pas », jamais « le job a tourné mais les données sont mauvaises ».
    notify "$HEALTHCHECKS_URL" up "invariants OK" "healthchecks (hors site)" hc
  else
    notify "$KUMA_VERIFY_URL" down "invariants en defaut (rc=$rc)" "eurio-verify"
    echo "   healthchecks NON pingé : son silence est le signal."
  fi
  return "$rc"
}

# Un canal d'alerte non testé est une alerte qui n'existe pas. Ce n'est pas une
# formule : les 10 jobs Duplicati criaient dans une interface sans lecteur
# depuis neuf mois. Cette commande envoie un `down` réel sur chaque anneau —
# il DOIT arriver sur Discord.
cmd_notify_test() {
  echo "=== test des anneaux de notification ==="
  echo "    Un « down » réel part sur chaque anneau configuré."
  echo "    Il doit arriver sur Discord. Sinon l'anneau n'existe pas."
  echo
  notify "$KUMA_STAGING_URL"  down "TEST — ignorer" "eurio-staging"
  notify "$KUMA_VERIFY_URL"   down "TEST — ignorer" "eurio-verify"
  notify "$KUMA_DRILL_URL"    down "TEST — ignorer" "eurio-drill"
  notify "$HEALTHCHECKS_URL"  down "TEST — ignorer" "healthchecks (hors site)" hc
  echo
  echo "→ Vérifie Discord, puis relance 'stage' et 'verify' pour repasser au vert."
}

cmd_help() {
  sed -n '/^# Usage :/,/^$/p' "$0" | sed 's/^# \?//'
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "${1:-help}" in
  stage)          cmd_stage ;;
  verify)         shift; cmd_verify "$@" ;;
  notify-test)    cmd_notify_test ;;
  help|-h|--help) cmd_help ;;
  *) cmd_help; exit 2 ;;
esac
