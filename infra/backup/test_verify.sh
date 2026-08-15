#!/usr/bin/env bash
#
# Test NÉGATIF de la suite d'invariants.
#
# Une suite de tests qui ne sort jamais en erreur ne prouve rien — c'est
# exactement le piège qu'on corrige : un dispositif qui rapporte « vert » sans
# qu'on ait jamais vérifié qu'il sait rapporter « rouge ».
#
# Chaque cas fabrique un staging volontairement cassé et exige que
# `verify_invariants.py` le détecte. Un cas qui passerait au vert est un
# invariant inopérant.
#
# Usage : test_verify.sh    (sortie 0 = tous les cas se comportent comme attendu)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  exec nix shell nixpkgs#python3 --command "$0" "$@"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

# Fabrique un staging minimal mais VALIDE, que chaque cas abîme ensuite.
make_fixture() {
  local dir="$1"
  mkdir -p "$dir"
  python3 - "$dir" <<'PY'
import sqlite3, sys
d = sys.argv[1]
con = sqlite3.connect(f"{d}/eurio.db")
con.executescript("""
  create table coins (eurio_id text primary key);
  create table coin_names_i18n (eurio_id text, lang text);
  create table coin_canonical_images (eurio_id text, url text);
  create table image_assets (storage_path text, sha256 text);
  create table source_images (storage_path text, sha256 text);
  create table review_queue (id integer primary key);
  create table _schema_migrations (filename text, applied_at integer);
""")
con.execute("insert into coins values ('xx-2026-2eur-canari')")
con.executemany("insert into coin_names_i18n values (?,?)",
                [("xx-2026-2eur-canari", l) for l in ("fr", "en")])
con.execute("insert into coin_canonical_images values ('xx-2026-2eur-canari','http://x/o.png')")
con.executemany("insert into review_queue values (?)", [(i,) for i in range(100)])
con.commit(); con.close()

con = sqlite3.connect(f"{d}/review.db")
con.executescript("""
  create table review_items (id integer primary key);
  create table decisions (id integer primary key);
  create table reviewers (id integer primary key);
  create table meta (k text);
""")
con.executemany("insert into review_items values (?)", [(i,) for i in range(50)])
con.commit(); con.close()
PY
  python3 "$SCRIPT_DIR/build_manifest.py" "$dir" --t1 "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
}

# expect_fail <nom> <motif attendu dans la sortie> -- <commande...>
expect_fail() {
  local name="$1" pattern="$2"; shift 3
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "  🔴 $name — le verify a répondu VERT alors qu'il devait échouer"
    FAIL=$((FAIL+1)); return
  fi
  if ! grep -qi -- "$pattern" <<<"$out"; then
    echo "  🔴 $name — échec correct (rc=$rc) mais message inattendu (motif « $pattern » absent)"
    FAIL=$((FAIL+1)); return
  fi
  echo "  ✅ $name — détecté (rc=$rc)"
  PASS=$((PASS+1))
}

expect_pass() {
  local name="$1"; shift
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "  🔴 $name — devait passer, rc=$rc"
    echo "$out" | sed 's/^/       /' | tail -8
    FAIL=$((FAIL+1)); return
  fi
  echo "  ✅ $name"
  PASS=$((PASS+1))
}

V() { python3 "$SCRIPT_DIR/verify_invariants.py" "$@"; }

echo "=== Test négatif de la suite d'invariants ==="
echo

# Cas 0 — référence : un staging sain doit passer. Sans ce cas, un script qui
# échoue systématiquement passerait tous les tests négatifs.
make_fixture "$WORK/sain"
expect_pass "[0] staging sain accepté" V "$WORK/sain"

# Cas 1 — base tronquée. LE cas qui motive tout le niveau 3 : sha cohérent,
# integrity_check ok, et pourtant les données ont disparu.
make_fixture "$WORK/tronque"
cp "$WORK/tronque/manifest.json" "$WORK/baseline-tronque.json"
python3 - "$WORK/tronque" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"{sys.argv[1]}/eurio.db")
con.execute("delete from review_queue")          # 100 → 0
con.commit(); con.close()
PY
python3 "$SCRIPT_DIR/build_manifest.py" "$WORK/tronque" --t1 "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
expect_fail "[1] base tronquée (100 → 0 lignes)" "non-décroissance" -- \
  V "$WORK/tronque" --baseline "$WORK/baseline-tronque.json"

# Cas 2 — base VIDE mais structurellement parfaite. `integrity_check` répond
# `ok` sur une base vide : seul le canari la rejette.
make_fixture "$WORK/vide"
python3 - "$WORK/vide" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"{sys.argv[1]}/eurio.db")
for t in ("coins", "coin_names_i18n", "coin_canonical_images", "review_queue"):
    con.execute(f"delete from {t}")
con.commit(); con.close()
PY
python3 "$SCRIPT_DIR/build_manifest.py" "$WORK/vide" --t1 "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
expect_fail "[2] base vide mais valide" "canari" -- V "$WORK/vide"

# Cas 3 — schéma désaligné : migrations du dépôt non appliquées.
make_fixture "$WORK/schema"
expect_fail "[3] migrations du dépôt non appliquées" "migrations" -- \
  V "$WORK/schema" --repo-root "$REPO_ROOT"

# Cas 4 — corruption après écriture du manifeste (contrôle d'atomicité).
make_fixture "$WORK/altere"
printf 'corruption' >> "$WORK/altere/eurio.db"
expect_fail "[4] fichier modifié après le manifeste" "sha256" -- V "$WORK/altere"

# Cas 5 — staging figé : tous les autres invariants passent.
make_fixture "$WORK/perime"
python3 - "$WORK/perime" <<'PY'
import json, sys
p = f"{sys.argv[1]}/manifest.json"
m = json.load(open(p))
m["created_utc"] = "2026-01-01T03:00:00Z"
json.dump(m, open(p, "w"), indent=2)
PY
expect_fail "[5] staging périmé (fraîcheur)" "fraîcheur" -- V "$WORK/perime"

# Cas 6 — manifeste absent : `stage` n'a pas terminé.
make_fixture "$WORK/sans-manifeste"
rm -f "$WORK/sans-manifeste/manifest.json"
expect_fail "[6] manifeste absent (stage incomplet)" "manifeste absent" -- V "$WORK/sans-manifeste"

# Cas 7 — une base manquante du staging.
make_fixture "$WORK/incomplet"
rm -f "$WORK/incomplet/review.db"
expect_fail "[7] base absente du staging" "absent" -- V "$WORK/incomplet"

# Cas 8 — l'acquittement humain lève la décroissance, et elle seule.
expect_pass "[8] --accept-baseline acquitte la décroissance" \
  V "$WORK/tronque" --baseline "$WORK/baseline-tronque.json" --accept-baseline

echo
echo "=== $PASS réussis, $FAIL en défaut ==="
[ "$FAIL" -eq 0 ] || exit 1
echo "✅ la suite d'invariants sait dire NON — elle prouve quelque chose."
