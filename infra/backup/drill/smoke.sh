#!/usr/bin/env bash
# Niveau 4 — « l'application démarrerait-elle sur la donnée restaurée ? »
#
# Le niveau 3 (invariants) regarde des fichiers. Ici on demande à l'application
# elle-même de servir cette donnée, y compris le chemin qui traverse les deux
# stores : une URL présignée émise par l'API, résolue contre le MinIO restauré,
# avec la policy du compte applicatif — et dont on compare les octets au
# fichier restauré.
set -uo pipefail

API=http://127.0.0.1:18042
# PAT « break-glass » créé sur la copie restaurée (serving.auth create-pat) :
# l'authentification fait partie de ce qu'on restaure, autant l'exercer.
AUTH=(-H "Authorization: Bearer ${DRILL_PAT:?DRILL_PAT manquant}")
REVIEW=http://127.0.0.1:18048
RESTORED="${1:?usage: smoke.sh <répertoire-restauré> <répertoire-de-travail>}"
WORK="${2:?usage: smoke.sh <répertoire-restauré> <répertoire-de-travail>}"
fail=0
ok()   { echo "  ✅ $*"; }
ko()   { echo "  ❌ $*"; fail=1; }

echo "=== 1. l'application répond ==="
code=$(curl -s -o /tmp/h.json -w '%{http_code}' -m 10 "${AUTH[@]}" "$API/healthz")
[ "$code" = 200 ] && ok "GET /healthz → 200 $(cat /tmp/h.json)" || ko "GET /healthz → $code"

echo "=== 2. elle sert la donnée restaurée ==="
code=$(curl -s -o /tmp/coins.json -w '%{http_code}' -m 30 "${AUTH[@]}" "$API/coins?limit=5")
if [ "$code" = 200 ]; then
  n=$(python3 -c "import json;d=json.load(open('/tmp/coins.json'));print(d.get('total') or len(d.get('items',[])))" 2>/dev/null)
  ok "GET /coins → 200, total annoncé : $n"
else
  ko "GET /coins → $code $(head -c 200 /tmp/coins.json)"
fi

echo "=== 3. un crop traverse DB → API → URL signée → MinIO restauré ==="
read -r EURIO_ID ASSET_ID STORAGE_PATH <<<"$(python3 - "$RESTORED/eurio.db" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
row = con.execute("""
    SELECT eurio_id, id, storage_path
      FROM image_assets
     WHERE storage_path IS NOT NULL AND eurio_id IS NOT NULL
     LIMIT 1
""").fetchone()
print(*row if row else ("", "", ""))
PY
)"

if [ -z "${EURIO_ID:-}" ]; then
  ko "aucun crop exploitable dans la base restaurée"
else
  echo "     pièce $EURIO_ID · asset $ASSET_ID · objet $STORAGE_PATH"
  code=$(curl -s -o /tmp/assets.json -w '%{http_code}' -m 30 "${AUTH[@]}" "$API/coins/$EURIO_ID/assets?include_unresolved=true&limit=200")
  if [ "$code" != 200 ]; then
    ko "GET /coins/$EURIO_ID/assets → $code $(head -c 200 /tmp/assets.json)"
  else
    url=$(python3 - <<PY
import json
d = json.load(open('/tmp/assets.json'))
items = d.get('items') or d.get('assets') or []
m = [a for a in items if a.get('id') == "$ASSET_ID"] or items
print(m[0]['file_url'] if m else '')
PY
)
    case "$url" in
      http*127.0.0.1:19000*) ok "l'API a signé une URL vers le MinIO de l'exercice" ;;
      "")   ko "aucune URL d'asset dans la réponse" ;;
      /*)   ko "URL relative — la signature a échoué côté API (repli), MinIO injoignable ou creds fausses : $url" ;;
      *)    ko "URL signée vers un hôte inattendu : ${url%%\?*}" ;;
    esac
    if [ -n "$url" ]; then
      code=$(curl -s -o /tmp/obj.bin -w '%{http_code}' -m 60 "$url")
      if [ "$code" = 200 ]; then
        got=$(sha256sum /tmp/obj.bin | cut -d' ' -f1)
        want=$(sha256sum "$RESTORED/minio/enrichment-crops/$STORAGE_PATH" | cut -d' ' -f1)
        [ "$got" = "$want" ] && ok "objet servi ≡ octet pour octet le fichier restauré" \
                             || ko "l'objet servi diffère du fichier restauré"
      else
        ko "l'URL signée renvoie $code — policy eurio-app insuffisante ?"
      fi
    fi
  fi
fi

echo "=== 4. eurio-review sur la review.db restaurée ==="
RT=$(cat "$WORK/secrets/review_admin_token")
code=$(curl -s -o /tmp/rv.json -w '%{http_code}' -m 15 "$REVIEW/health")
[ "$code" = 200 ] && ok "GET /health → 200 $(cat /tmp/rv.json)" || ko "GET /health → $code"
code=$(curl -s -o /tmp/rf.json -w '%{http_code}' -m 15 -H "X-Admin-Token: $RT" "$REVIEW/admin/flow")
if [ "$code" = 200 ]; then
  ok "GET /admin/flow → 200 $(head -c 120 /tmp/rf.json)"
else
  ko "GET /admin/flow → $code"
fi

echo
[ $fail -eq 0 ] && echo "✅ niveau 4 : l'application sert la donnée restaurée" \
                || echo "🔴 niveau 4 : au moins un contrôle a échoué"
exit $fail
