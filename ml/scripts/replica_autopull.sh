#!/bin/sh
# Auto-pull de la réplique eurio.db (Direction A — transparence de sync).
#
# Appelé par les timers machine (launchd sur Mac, systemd user sur PC NixOS,
# cf. docs/work-in-progress/local-sync/replica-auto-sync.md) toutes les ~2 min.
# Charge le devShell via direnv (fournit sqlite3_rsync + EURIO_API_* pour le
# fallback) puis lance le pull transport auto : sqlite3_rsync incrémental
# (~3 s, pages modifiées seules) avec la clé dédiée ~/.ssh/eurio_replica,
# fallback GET /db/replica. Aucune donnée locale à perdre : les écritures
# partent au VPS via POST /ingest/*, ce script ne fait que RAFRAÎCHIR la vue.
#
# Sort en erreur (code ≠ 0) si le pull échoue — visible dans les logs du
# timer, jamais bloquant pour l'utilisateur.

set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIRENV_BIN="${DIRENV_BIN:-$(command -v direnv || echo "/etc/profiles/per-user/$(whoami)/bin/direnv")}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] pull-replica…"
cd "$ROOT/ml"
"$DIRENV_BIN" exec "$ROOT" "$ROOT/ml/.venv/bin/python" -m client.replica
# Stamp de passage : mtime de la réplique = dernier CHANGEMENT de contenu ;
# ce fichier = dernier pull RÉUSSI (même sans changement). Lu par --status.
touch "$ROOT/ml/state/.replica-last-pull"
