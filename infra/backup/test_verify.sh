#!/usr/bin/env bash
#
# Test NÉGATIF de la suite d'invariants.
#
# Une suite de tests qui ne sort jamais en erreur ne prouve rien — c'est
# exactement le piège qu'on corrige : un dispositif qui rapporte « vert » sans
# qu'on ait jamais vérifié qu'il sait rapporter « rouge ».
#
# Chaque cas fabrique un staging volontairement cassé et exige que
# `verify_invariants.py` le détecte, ET sur le bon invariant. Un cas qui
# passerait au vert, ou qui rougirait pour une autre raison que celle visée,
# est un invariant inopérant.
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

BUILD="$SCRIPT_DIR/build_manifest.py"
V() { python3 "$SCRIPT_DIR/verify_invariants.py" "$@"; }
remanifest() { python3 "$BUILD" "$1" --t1 "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null; }

# Fabrique un staging minimal mais VALIDE, que chaque cas abîme ensuite.
# Les migrations du dépôt y sont enregistrées : sans elles, tous les cas
# rougiraient sur l'invariant de migrations et masqueraient ce qu'ils testent.
make_fixture() {
  local dir="$1"
  mkdir -p "$dir"
  python3 - "$dir" "$REPO_ROOT" <<'PY'
import os, sqlite3, sys
d, repo = sys.argv[1], sys.argv[2]

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
coins = [f"xx-2026-{i:03d}-canari" for i in range(40)]
con.executemany("insert into coins values (?)", [(c,) for c in coins])
con.executemany("insert into coin_names_i18n values (?,?)",
                [(c, l) for c in coins for l in ("fr", "en")])
con.executemany("insert into coin_canonical_images values (?,?)",
                [(c, "http://x/o.png") for c in coins])
con.executemany("insert into review_queue values (?)", [(i,) for i in range(100)])

migrations_dir = os.path.join(repo, "ml", "serving", "migrations")
if os.path.isdir(migrations_dir):
    applied = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    con.executemany("insert into _schema_migrations values (?,0)", [(m,) for m in applied])
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
  remanifest "$dir"
}

# expect_fail <nom> <motif ANCRÉ sur la ligne rouge attendue> -- <commande...>
#
# Vérifie trois choses, pas une : le code de retour, l'invariant précisément
# visé, ET qu'aucun autre invariant ne rougit. Sans le troisième contrôle, un
# cas peut échouer pour une raison, matcher le motif d'une autre, et passer —
# le test serait alors satisfait sans que l'invariant visé fonctionne.
expect_fail() {
  local name="$1" pattern="$2"; shift 3
  local out rc reds
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "  🔴 $name — le verify a répondu VERT alors qu'il devait échouer"
    FAIL=$((FAIL+1)); return
  fi
  if ! grep -qE -- "$pattern" <<<"$out"; then
    echo "  🔴 $name — échec (rc=$rc) mais pas sur l'invariant visé (« $pattern » absent)"
    grep "🔴" <<<"$out" | sed 's/^/       /'
    FAIL=$((FAIL+1)); return
  fi
  reds="$(grep -c '^  🔴' <<<"$out")"
  if [ "${reds:-0}" -gt 1 ]; then
    echo "  ⚠️  $name — détecté, mais $reds invariants rouges : le cas n'isole pas ce qu'il teste"
    grep '^  🔴' <<<"$out" | sed 's/^/       /'
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
    tail -8 <<<"$out" | sed 's/^/       /'
    FAIL=$((FAIL+1)); return
  fi
  echo "  ✅ $name"
  PASS=$((PASS+1))
}

echo "=== Test négatif de la suite d'invariants ==="
echo

# Cas 0 — référence : un staging sain doit passer. Sans ce cas, un script qui
# échoue systématiquement passerait tous les tests négatifs.
make_fixture "$WORK/sain"
expect_pass "[0] staging sain accepté" V "$WORK/sain" --repo-root "$REPO_ROOT"

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
remanifest "$WORK/tronque"
expect_fail "[1] base tronquée (100 → 0 lignes)" "non-décroissance" -- \
  V "$WORK/tronque" --baseline "$WORK/baseline-tronque.json" --repo-root "$REPO_ROOT"

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
remanifest "$WORK/vide"
expect_fail "[2] base vide mais valide" "canari" -- V "$WORK/vide" --repo-root "$REPO_ROOT"

# Cas 3 — amputation massive SANS baseline : le canari doit tenir tout seul.
# Une pièce unique laisserait passer une base dont 99 % des traductions ont
# disparu, si celle qu'on interroge fait partie du 1 % survivant.
make_fixture "$WORK/ampute"
python3 - "$WORK/ampute" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"{sys.argv[1]}/eurio.db")
con.execute("delete from coin_names_i18n where eurio_id <> 'xx-2026-000-canari'")
con.commit(); con.close()
PY
remanifest "$WORK/ampute"
expect_fail "[3] 97 % des traductions perdues, sans baseline" "canari" -- \
  V "$WORK/ampute" --repo-root "$REPO_ROOT"

# Cas 4 — corruption après écriture du manifeste (contrôle d'atomicité).
make_fixture "$WORK/altere"
printf 'corruption' >> "$WORK/altere/eurio.db"
expect_fail "[4] fichier modifié après le manifeste" "sha256" -- \
  V "$WORK/altere" --repo-root "$REPO_ROOT"

# Cas 5 — staging figé : tous les autres invariants passent.
make_fixture "$WORK/perime"
python3 - "$WORK/perime" <<'PY'
import json, sys
p = f"{sys.argv[1]}/manifest.json"
m = json.load(open(p))
m["created_utc"] = "2026-01-01T03:00:00Z"
json.dump(m, open(p, "w"), indent=2)
PY
expect_fail "[5] staging périmé (fraîcheur)" "fraîcheur" -- V "$WORK/perime" --repo-root "$REPO_ROOT"

# Cas 6 — manifeste absent : `stage` n'a pas terminé.
make_fixture "$WORK/sans-manifeste"
rm -f "$WORK/sans-manifeste/manifest.json"
expect_fail "[6] manifeste absent (stage incomplet)" "manifeste absent" -- V "$WORK/sans-manifeste"

# Cas 7 — une base manquante du staging, le manifeste la décrivant encore.
make_fixture "$WORK/incomplet"
rm -f "$WORK/incomplet/review.db"
expect_fail "[7] base absente du staging" "absent du disque" -- \
  V "$WORK/incomplet" --repo-root "$REPO_ROOT"

# Cas 8 — DROP d'une table surveillée. Une table disparue supprime plus de
# lignes que n'importe quel delete. Trou trouvé par la revue du 2026-08-15 :
# 8 tables sur 16 pouvaient disparaître en restant vertes.
make_fixture "$WORK/drop"
cp "$WORK/drop/manifest.json" "$WORK/baseline-drop.json"
python3 - "$WORK/drop" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"{sys.argv[1]}/eurio.db")
con.execute("drop table review_queue"); con.commit(); con.close()
PY
remanifest "$WORK/drop"
expect_fail "[8] table surveillée SUPPRIMÉE" "TABLE ABSENTE" -- \
  V "$WORK/drop" --baseline "$WORK/baseline-drop.json" --repo-root "$REPO_ROOT"

# Cas 9 — base obligatoire retirée du manifeste ET du staging. Le manifeste
# n'a pas le droit d'être la seule autorité sur son propre périmètre.
make_fixture "$WORK/hors-perimetre"
rm -f "$WORK/hors-perimetre/review.db"
python3 - "$WORK/hors-perimetre" <<'PY'
import json, sys
p = f"{sys.argv[1]}/manifest.json"
m = json.load(open(p)); m["files"].pop("review.db", None)
json.dump(m, open(p, "w"), indent=2)
PY
expect_fail "[9] base obligatoire absente du manifeste" "absent du manifeste" -- \
  V "$WORK/hors-perimetre" --repo-root "$REPO_ROOT"

# Cas 10 — migration inconnue du dépôt : base plus récente que le code.
make_fixture "$WORK/migration-inconnue"
python3 - "$WORK/migration-inconnue" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"{sys.argv[1]}/eurio.db")
con.execute("insert into _schema_migrations values ('0099_inconnue_du_depot.sql',0)")
con.commit(); con.close()
PY
remanifest "$WORK/migration-inconnue"
expect_fail "[10] migration inconnue du dépôt" "inconnues du dépôt" -- \
  V "$WORK/migration-inconnue" --repo-root "$REPO_ROOT"

# Cas 11 — migrations PARTIELLEMENT appliquées : le cas réaliste d'une
# migration interrompue, plus dangereux que le cas dégénéré 0/5.
make_fixture "$WORK/migration-partielle"
python3 - "$WORK/migration-partielle" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"{sys.argv[1]}/eurio.db")
last = con.execute("select filename from _schema_migrations order by filename desc limit 1").fetchone()
con.execute("delete from _schema_migrations where filename = ?", (last[0],))
con.commit(); con.close()
PY
remanifest "$WORK/migration-partielle"
expect_fail "[11] migration manquante (dernière non appliquée)" "non appliquées" -- \
  V "$WORK/migration-partielle" --repo-root "$REPO_ROOT"

# Cas 12 — sources figées : le staging est frais, les données ne bougent plus.
make_fixture "$WORK/source-figee"
python3 - "$WORK/source-figee" <<'PY'
import json, sys
p = f"{sys.argv[1]}/manifest.json"
m = json.load(open(p))
m["files"]["eurio.db"]["source_mtime_utc"] = "2024-01-01T00:00:00Z"
json.dump(m, open(p, "w"), indent=2)
PY
expect_fail "[12] sources figées depuis plus d'un an" "vivacité" -- \
  V "$WORK/source-figee" --repo-root "$REPO_ROOT"

# Cas 13 — base réellement corrompue : doit produire un invariant ROUGE, pas un
# traceback. Un vérificateur qui explose ne rend aucun verdict.
make_fixture "$WORK/corrompu"
python3 - "$WORK/corrompu" <<'PY'
import os, sys
# On abime le MILIEU du fichier (pages de donnees, pas l'en-tete) avec des
# octets non nuls, puis on re-manifeste : le sha sera cohérent, donc c'est
# `integrity_check` qui doit trancher — et il ne doit pas exploser en le faisant.
p = f"{sys.argv[1]}/eurio.db"
data = bytearray(open(p, "rb").read())
mid = len(data) // 2
data[mid:mid + 4096] = os.urandom(min(4096, len(data) - mid))
open(p, "wb").write(bytes(data))
PY
remanifest "$WORK/corrompu"
expect_fail "[13] base corrompue → rouge, pas de traceback" "integrity_check|exception" -- \
  V "$WORK/corrompu" --repo-root "$REPO_ROOT"

# Cas 14 — l'acquittement humain lève la décroissance. `expect_pass` ne
# vérifierait que rc=0 : on exige AUSSI que la ligne rouge reste affichée,
# sinon le cas passerait même si l'invariant ne détectait plus rien.
if out="$(V "$WORK/tronque" --baseline "$WORK/baseline-tronque.json" \
            --repo-root "$REPO_ROOT" --accept-baseline 2>&1)" \
   && grep -q "non-décroissance" <<<"$out"; then
  echo "  ✅ [14] --accept-baseline acquitte la décroissance (et la signale encore)"
  PASS=$((PASS+1))
else
  echo "  🔴 [14] --accept-baseline : rc≠0 ou la décroissance n'est plus signalée"
  FAIL=$((FAIL+1))
fi

# Cas 15 — --accept-baseline ne doit JAMAIS absoudre un autre invariant.
expect_fail "[15] --accept-baseline n'absout pas un autre invariant" "canari" -- \
  V "$WORK/vide" --repo-root "$REPO_ROOT" --accept-baseline

echo
echo "=== $PASS réussis, $FAIL en défaut ==="
[ "$FAIL" -eq 0 ] || exit 1
echo "✅ la suite d'invariants sait dire NON — elle prouve quelque chose."
