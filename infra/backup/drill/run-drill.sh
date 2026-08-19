#!/usr/bin/env bash
# Exercice de restauration — de bout en bout, en une commande.
#
# Répond à UNE question, et à elle seule : « le VPS est perdu ; avec le dépôt
# Codeberg et ma clé age, est-ce que je récupère Eurio ? »
#
# Ce que le harnais du 2026-08-16 laissait à la main, et qui est ici :
#
#   - le `git clone` lui-même — l'exercice partait de /opt/eurio, donc ne
#     prouvait rien sur la suffisance du dépôt ;
#   - la CONSTRUCTION des images — il réutilisait les `:latest` déjà présentes
#     sur la machine, c'est-à-dire l'artefact que le sinistre emporte ;
#   - le rapatriement depuis pCloud — huit étapes de README-RESTORE.md.
#
# Isolation (les trois barrières de compose.yml, plus deux) :
#   4. les images construites sont taguées `:drill`, JAMAIS `:latest` — un
#      `docker build` qui écrase le tag de production serait un exercice qui
#      casse ce qu'il prétend savoir remonter ;
#   5. tout vit dans $WORK, hors du dépôt, et `prepare-secrets.sh` refuse
#      d'écrire dans /opt/eurio.
#
# Usage :
#   ./run-drill.sh all          # tout, dans l'ordre (~1 h 15)
#   ./run-drill.sh <étape>      # clone build pick restore up smoke
#   ./run-drill.sh status       # où en est l'exercice
#   ./run-drill.sh down         # détruit la stack et $WORK
#
# Chaque étape pose un marqueur dans $WORK/.state et se saute si déjà faite :
# un échec en étape 6 se reprend sans re-télécharger 6 Go. `--force` rejoue.
#
# Réglages :
#   WORK            répertoire jetable          (défaut: /opt/eurio-restore-test)
#   DRILL_REF       ref git à cloner            (défaut: la branche courante)
#   DRILL_EMAIL     email du PAT break-glass    (défaut: git config user.email)
#   DRILL_VERSION   version Duplicati à restaurer (défaut: la plus récente
#                   QUI PORTE UN MANIFESTE — cf. `pick`)
#   DRILL_DUPLICATI_CMD  binaire duplicati-cli  (défaut: via `nix shell`)
#
# Protocole complet : docs/work-in-progress/backup-pipeline/RESTAURATION.md §4
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGIN_REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
WORK="${WORK:-/opt/eurio-restore-test}"

case "$(readlink -f "$WORK")" in
  /opt/eurio|/opt/eurio/*)
    echo "❌ WORK interdit dans le dépôt : $WORK" >&2; exit 2 ;;
esac

REPO="$WORK/repo"
RESTORED="$WORK/restored"
STATE="$WORK/.state"
LOGS="$WORK/log"
PARAMS="$WORK/duplicati/params"
COMPOSE="$REPO/infra/backup/drill/compose.yml"

# La destination Duplicati stocke les chemins sous le bind du conteneur ;
# `restore` retire ce dossier de tête (README-RESTORE.md §1).
API_IMAGE="eurio-api:drill"
REVIEW_IMAGE="eurio-review:drill"

FORCE=""
[ "${2:-}" = "--force" ] && FORCE=1

say()  { echo -e "\n\033[1m▶ $*\033[0m"; }
ok()   { echo "  ✅ $*"; }
warn() { echo "  ⚠️  $*" >&2; }
die()  { echo "  ❌ $*" >&2; exit 1; }

done_p()  { [ -z "$FORCE" ] && [ -f "$STATE/$1" ]; }
mark()    { mkdir -p "$STATE"; date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE/$1"; }

# Toute étape qui touche à un secret passe par le fichier SOPS **du clone** :
# c'est lui qu'on prétend suffisant, pas celui de la machine survivante.
sops_env() {
  local envfile="$REPO/secrets/dev.env"
  [ -f "$envfile" ] || die "secrets/dev.env absent du clone — l'étape clone a-t-elle tourné ?"
  sops exec-env "$envfile" "$*"
}

dup() {
  if [ -n "${DRILL_DUPLICATI_CMD:-}" ]; then
    $DRILL_DUPLICATI_CMD "$@"
  else
    # Le conteneur `oim-duplicati` est justement ce que le sinistre emporte :
    # par défaut on prend le chemin du jour J, un Duplicati sorti de nixpkgs.
    # Vérifié le 2026-08-19 : le 2.3.0.1 de nixpkgs lit les archives écrites
    # par le 2.2.0 du conteneur (les 5 dlist se déchiffrent et se listent).
    nix shell nixpkgs#duplicati --command duplicati-cli "$@"
  fi
}

# ── 1. le dépôt, et rien d'autre ─────────────────────────────────────────────
step_clone() {
  say "1/6 — clone du canonique"
  if done_p clone; then ok "déjà cloné ($REPO)"; return 0; fi
  rm -rf "$REPO"
  mkdir -p "$WORK"; chmod 700 "$WORK"

  local remote url ref
  remote="$(git -C "$ORIGIN_REPO" remote | head -1)"
  url="$(git -C "$ORIGIN_REPO" remote get-url "$remote")"
  ref="${DRILL_REF:-$(git -C "$ORIGIN_REPO" rev-parse --abbrev-ref HEAD)}"
  echo "  $url @ $ref"

  git clone --depth 1 --branch "$ref" "$url" "$REPO" \
    || die "clone impossible — c'est le scénario du jour J qui échoue ici, pas l'exercice"
  ok "cloné : $(git -C "$REPO" rev-parse --short HEAD)"

  # La clé age est l'autre moitié du couple. Sans elle la sauvegarde est
  # irrécupérable (README-RESTORE.md §2) : on le prouve maintenant, pas dans
  # quarante minutes au moment de démarrer MinIO.
  sops -d "$REPO/secrets/dev.env" >/dev/null 2>&1 \
    || die "secrets du clone indéchiffrables — clé age absente de ~/.config/sops/age/keys.txt ?"
  ok "secrets du clone déchiffrables"

  local missing=0
  for f in infra/backup/drill/compose.yml infra/backup/drill/prepare-secrets.sh \
           infra/backup/drill/import-objects.sh infra/backup/drill/smoke.sh \
           infra/minio/bootstrap.sh infra/eurio-api/Dockerfile infra/review/Dockerfile; do
    [ -f "$REPO/$f" ] || { warn "absent du clone : $f"; missing=1; }
  done
  [ "$missing" = 0 ] || die "la ref « $ref » ne porte pas le harnais complet — DRILL_REF ?"

  # Le clone est la source de vérité de l'exercice : tout ce qui suit tourne
  # depuis lui. Un harnais modifié mais non poussé ne serait donc pas testé,
  # et pire, le compose du clone démarrerait les images `:latest` DE PRODUCTION
  # en croyant lancer celles de l'exercice.
  grep -q 'DRILL_API_IMAGE' "$REPO/infra/backup/drill/compose.yml" \
    || die "le compose de la ref « $ref » ignore DRILL_API_IMAGE : il démarrerait les images de production. Committer et pousser le harnais d'abord."
  mark clone
}

# ── 2. reconstruire l'application depuis ce clone ────────────────────────────
step_build() {
  say "2/6 — construction des images depuis le clone"
  if done_p build; then ok "déjà construites"; return 0; fi
  mkdir -p "$LOGS"

  # Tag `:drill`, jamais `:latest` : les images de production tournent.
  docker build -t "$API_IMAGE" \
    --build-context "ml=$REPO/ml" \
    -f "$REPO/infra/eurio-api/Dockerfile" "$REPO/infra/eurio-api" \
    > "$LOGS/build-api.log" 2>&1 \
    || die "build eurio-api échoué — $LOGS/build-api.log"
  ok "$API_IMAGE"

  docker build -t "$REVIEW_IMAGE" \
    --build-context "admin=$REPO/admin" \
    --build-context "ml=$REPO/ml" \
    --build-context "shared=$REPO/shared" \
    -f "$REPO/infra/review/Dockerfile" "$REPO/infra/review" \
    > "$LOGS/build-review.log" 2>&1 \
    || die "build eurio-review échoué — $LOGS/build-review.log"
  ok "$REVIEW_IMAGE"
  mark build
}

# ── 3. choisir la version — celle qui porte une sentinelle ───────────────────
step_pick() {
  say "3/6 — choix de la version à la destination"
  if done_p pick; then ok "version retenue : $(cat "$STATE/version")"; return 0; fi
  mkdir -p "$WORK/duplicati" "$LOGS"; chmod 700 "$WORK/duplicati"

  # Ni la destination ni la passphrase ne passent par argv : une couche qui
  # déguillemette l'URL fait disparaître tout ce qui suit `?`, et l'erreur
  # qui en résulte parle d'un secret provider inexistant (README-RESTORE.md §4).
  sops exec-env "$REPO/secrets/dev.env" 'bash -s' <<EOF || die "écriture du fichier de paramètres impossible"
set -eu
umask 077
cat > "$PARAMS" <<PARAMS
--target=pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/Eurio?authid=\${DUPLICATI_PCLOUD_AUTHID:?absent de SOPS}
--passphrase=\${DUPLICATI_EURIO_PASSPHRASE:?absent de SOPS}
--dbpath=$WORK/duplicati/local.sqlite
PARAMS
EOF
  ok "paramètres écrits (aucun secret dans argv, donc rien dans ps)"

  if [ -n "${DRILL_VERSION:-}" ]; then
    echo "$DRILL_VERSION" > "$STATE/version"
    warn "version imposée par DRILL_VERSION=$DRILL_VERSION — la sentinelle n'est pas contrôlée"
    mark pick; return 0
  fi

  dup find dummy://x --parameters-file="$PARAMS" 2>&1 | tee "$LOGS/find.log" | sed -n '/Listing filesets/,$p'

  # `stage` supprime manifest.json EN PREMIER et le réécrit en dernier. Un
  # staging sans manifeste est donc un staging mort — et Duplicati, planifié
  # indépendamment, le téléverse quand même. Constaté le 2026-08-16 sur la
  # version la plus récente : c'est celle qu'on aurait prise en urgence.
  local v="" found=""
  for v in 0 1 2 3 4; do
    echo "  version $v …"
    if dup find dummy://x '*manifest.json' --version="$v" --parameters-file="$PARAMS" 2>/dev/null \
         | grep -qE '^/eurio-source/manifest\.json '; then
      ok "version $v : manifeste présent"
      found="$v"; break
    fi
    warn "version $v : PAS de manifeste — invérifiable, on remonte d'un cran"
  done
  [ -n "$found" ] || die "aucune des 5 dernières versions ne porte de manifeste — incident, pas exercice"
  echo "$found" > "$STATE/version"
  mark pick
}

# ── 4. rapatrier ─────────────────────────────────────────────────────────────
step_restore() {
  say "4/6 — restauration depuis pCloud (~40 min)"
  if done_p restore; then ok "déjà restauré ($RESTORED)"; return 0; fi
  local v; v="$(cat "$STATE/version")"
  mkdir -p "$RESTORED" "$LOGS"

  # Index complet D'ABORD. Un `restore --version=N` sans base locale ne
  # reconstruit l'index que partiellement : les dlist des autres versions
  # restent sans fileset et Duplicati échoue sur sa propre incohérence
  # (DatabaseInconsistency), après avoir tout téléchargé.
  echo "  reconstruction de l'index (~15 min, ne restaure rien)"
  dup repair dummy://x --parameters-file="$PARAMS" > "$LOGS/repair.log" 2>&1 \
    || die "repair échoué — $LOGS/repair.log"
  ok "index reconstruit"

  echo "  restauration de la version $v"
  dup restore dummy://x '*' \
    --parameters-file="$PARAMS" \
    --restore-path="$RESTORED" \
    --restore-permissions=false --overwrite=true --version="$v" \
    > "$LOGS/restore.log" 2>&1 \
    || die "restore échoué — $LOGS/restore.log"

  [ -f "$RESTORED/manifest.json" ] || die "pas de manifeste dans la copie restaurée"
  [ -f "$RESTORED/eurio.db" ] || die "pas de eurio.db dans la copie restaurée"
  ok "$(du -sh "$RESTORED" | cut -f1) restaurés — manifeste du $(python3 -c \
      "import json;print(json.load(open('$RESTORED/manifest.json'))['created_utc'])")"
  mark restore
}

# ── 5. remonter la stack sur la copie ────────────────────────────────────────
step_up() {
  say "5/6 — stack isolée sur la donnée restaurée"
  if done_p up; then ok "déjà démarrée"; return 0; fi
  export DRILL_API_IMAGE="$API_IMAGE" DRILL_REVIEW_IMAGE="$REVIEW_IMAGE"

  echo "  identifiants d'infra, régénérés depuis SOPS (jamais repris du serveur perdu)"
  sops_env "bash $REPO/infra/backup/drill/prepare-secrets.sh $WORK" || die "prepare-secrets"

  echo "  MinIO isolé"
  sops_env "docker compose -f $COMPOSE --project-directory $WORK up -d minio" || die "up minio"
  sleep 5
  MINIO_CONTAINER=eurio-minio-drill MINIO_SECRETS_DIR="$WORK/secrets" MINIO_SKIP_COMPOSE=1 \
    bash "$REPO/infra/minio/bootstrap.sh" > "$LOGS/bootstrap.log" 2>&1 \
    || die "bootstrap MinIO — $LOGS/bootstrap.log"
  # Bucket legacy que bootstrap.sh ne crée pas (D-20).
  docker exec eurio-minio-drill mc mb --ignore-existing local/eurio-db >/dev/null 2>&1
  ok "buckets et policies créés depuis le dépôt"

  # Le store RÉFÉRENCÉ avant le référençant : à l'envers, le décalage
  # produirait des références pendantes au lieu d'orphelins (DONNEES.md §3).
  echo "  objets (compte applicatif eurio-app, jamais root — D-30)"
  bash "$REPO/infra/backup/drill/import-objects.sh" "$WORK" "$RESTORED/minio" \
    > "$LOGS/import.log" 2>&1 || die "import des objets — $LOGS/import.log"
  ok "objets réinjectés"

  # Sans -wal ni -shm : VACUUM INTO produit une base autonome. Les fichiers
  # restaurés peuvent être en lecture seule, l'API écrit.
  cp "$RESTORED/eurio.db"  "$WORK/api-data/eurio.db"     && chmod 644 "$WORK/api-data/eurio.db"
  cp "$RESTORED/review.db" "$WORK/review-data/review.db" && chmod 644 "$WORK/review-data/review.db"
  ok "bases posées"

  sops_env "docker compose -f $COMPOSE --project-directory $WORK up -d" || die "up"
  sleep 10
  ok "services démarrés"
  mark up
}

# ── 6. les contrôles ─────────────────────────────────────────────────────────
step_smoke() {
  say "6/6 — l'application sert-elle cette donnée ?"
  local email pat
  email="${DRILL_EMAIL:-$(git -C "$ORIGIN_REPO" config user.email)}"

  # Authentik n'existe pas dans l'exercice : `create-pat` se décrit lui-même
  # comme break-glass, c'est exactement son cas d'usage.
  pat="$(docker exec eurio-api-drill python -m serving.auth create-pat \
           --email "$email" --name drill 2>/dev/null | grep -oE 'eurio_[A-Za-z0-9_-]+' | head -1)"
  if [ -n "$pat" ]; then
    ok "PAT break-glass créé pour $email"
  else
    # L'auth est désactivée dans la stack d'exercice : les contrôles passeront
    # quand même. Mais il faut le DIRE, sinon le compte rendu laisse croire
    # qu'un chemin non exercé a été validé.
    warn "create-pat a échoué ($email absent de la base restaurée ?) — le chemin PAT n'est PAS exercé"
    pat="drill-auth-desactivee"
  fi

  local fail=0
  DRILL_PAT="$pat" EURIO_BACKUP_NOTIFY_CONF="$ORIGIN_REPO/infra/backup/notify.conf" \
    bash "$REPO/infra/backup/drill/smoke.sh" "$RESTORED" "$WORK" || fail=1

  say "invariants sur la copie restaurée (niveau 3)"
  python3 "$REPO/infra/backup/verify_invariants.py" "$RESTORED" \
    --baseline "$RESTORED/baseline-manifest.json" --repo-root "$REPO" || fail=1

  [ "$fail" = 0 ] && mark smoke
  return $fail
}

step_down() {
  say "destruction"
  docker compose -f "$COMPOSE" --project-directory "$WORK" down -v 2>/dev/null \
    || docker compose -p eurio-drill down -v 2>/dev/null
  docker rmi "$API_IMAGE" "$REVIEW_IMAGE" 2>/dev/null
  rm -rf "$WORK"
  ok "stack et $WORK détruits"
}

step_status() {
  echo "WORK = $WORK"
  for s in clone build pick restore up smoke; do
    if [ -f "$STATE/$s" ]; then echo "  ✅ $s   $(cat "$STATE/$s")"; else echo "  ⬜ $s"; fi
  done
  [ -f "$STATE/version" ] && echo "  version Duplicati retenue : $(cat "$STATE/version")"
  docker ps --filter name=-drill --format '  {{.Names}}  {{.Status}}'
}

case "${1:-all}" in
  all)     step_clone && step_build && step_pick && step_restore && step_up && step_smoke ;;
  clone)   step_clone ;;
  build)   step_build ;;
  pick)    step_pick ;;
  restore) step_restore ;;
  up)      step_up ;;
  smoke)   step_smoke ;;
  down)    step_down ;;
  status)  step_status ;;
  *) sed -n '/^# Usage :/,/^set -uo/p' "$0" | sed 's/^# \?//' ; exit 2 ;;
esac
