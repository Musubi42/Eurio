"""Build the offline core (C3) from the canonical eurio.db, via the projection
builders — the same ones that feed Supabase (C2).

C3 is a strict SUBSET of C2: the light + stable data the app/proto can hold
offline.

**Pourquoi ça ne lit plus Supabase.** La version précédente lisait la
projection Supabase pour garantir `C3 ⊆ C2` *par construction*. Le raisonnement
était juste, mais il obtenait la propriété au lieu de la vérifier, et mettait
la **prod sur le chemin critique du build** : le 2026-08-16, le projet Supabase
étant injoignable, `go-task ml:build-app-core` échouait alors que toute la
matière était intacte sur le VPS. Un incident de disponibilité de la façade de
prod ne doit jamais empêcher de reconstruire un artefact de préprod.

La propriété est conservée, mais **calculée** : `--verify` compare le core
produit à ce que Supabase expose et échoue sur violation. C'est la règle que
`docs/work-in-progress/backup-pipeline/DONNEES.md` a tirée de `storage_status` —
*les invariants doivent être calculés, jamais lus*.

`C3 ⊆ C2` reste vrai par un chemin plus court : les deux naissent des **mêmes
builders** (`export.app_export.builders`), C3 n'étant qu'un sous-ensemble de
colonnes et de lignes de ce qu'ils produisent. Une transformation, deux
consommateurs.

Two serializations of the SAME projection are emitted:

    admin/packages/proto/public/data/app_core.json   # proto Vue (browser, nested per coin)
    app-android/src/main/assets/app_core.db           # Android (prebuilt SQLite, normalized)

What's IN the core (offline):
    - coin (identity + flat characteristics + mintage + variant + shared_reverse_id)
    - shared_reverse, design_group, mint, coin_mint_release
    - coin_name_i18n / coin_description_i18n  → FR + EN only
    - coin_topic                              → FR + EN only
    - coin_price                              → kind='market' only (baseline value)
    - coin_credit

What's NOT in the core (online / on-demand):
    - obverse images (Supabase Storage, fetched on demand)
    - other-language i18n (downloadable language packs)
    - catalogue prices (kind='catalogue' — "compléter sa collection" feature)

Usage::
    python -m export.build_app_core                  # canonique, aucun réseau
    python -m export.build_app_core --verify         # + contrôle C3 ⊆ Supabase
    python -m export.build_app_core --json-only

Codes de sortie : 0 ok · 1 erreur · 3 violation de `C3 ⊆ C2` · 4 Supabase
injoignable alors que `--verify` était demandé. Les codes 3 et 4 sont
distincts **exprès** : « la prod contredit le canonique » et « la prod ne
répond pas » demandent des gestes opposés, et les confondre est ce qui a fait
passer une panne de disponibilité pour un problème de build.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_ML_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ML_ROOT.parent
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

from export.app_export.io import get_pg_client  # noqa: E402

_JSON_PATH = _REPO_ROOT / "admin" / "packages" / "proto" / "public" / "data" / "app_core.json"
_DB_PATH = _REPO_ROOT / "app-android" / "src" / "main" / "assets" / "app_core.db"
_OFFLINE_LANGS = ("fr", "en")
_PAGE = 1000

# Columns pulled per table (Supabase → core). Order also drives SQLite schema.
_COIN_COLS = [
    "eurio_id", "country", "country_name", "year", "face_value_cents",
    "is_commemorative", "collector_only", "theme", "design_description", "mintage",
    "diameter_mm", "weight_g", "thickness_mm", "composition", "shape", "orientation",
    "edge_description", "edge_lettering", "obverse_lettering", "reverse_lettering",
    "demonetized", "demonetized_on", "design_group_id", "variant_kind",
    "canonical_eurio_id", "series_id", "shared_reverse_id",
]


def _fetch(client: httpx.Client, table: str, select: str, params: dict | None = None) -> list[dict]:
    """Paginated PostgREST GET (Range header), returns all rows."""
    out: list[dict] = []
    offset = 0
    base_params = dict(params or {})
    base_params["select"] = select
    while True:
        headers = {"Range-Unit": "items", "Range": f"{offset}-{offset + _PAGE - 1}"}
        resp = client.get(f"/{table}", params=base_params, headers=headers)
        resp.raise_for_status()
        page = resp.json()
        out.extend(page)
        if len(page) < _PAGE:
            return out
        offset += _PAGE


def _group_by(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


# ---------------------------------------------------------------------------
# Source canonique — les builders de la projection, sans réseau
# ---------------------------------------------------------------------------

# Colonnes retenues par table pour C3. `None` = toutes celles du builder.
# C'est la définition du sous-ensemble : ce qui n'est pas là ne part pas dans
# l'APK. Doit rester aligné avec les `select` PostgREST de `fetch_core`, dont
# `_subset_signature` vérifie l'équivalence.
_CORE_COLS: dict[str, list[str]] = {
    "coins": _COIN_COLS,
    "shared_reverse": ["id", "label", "asset_name", "map_version", "applies_to"],
    "design_group": ["id", "designation", "designation_i18n_json"],
    "mint": ["id", "country", "mark", "city", "display_name"],
    "coin_mint_release": ["id", "parent_type_id", "mint_year", "mint_id", "issue_type", "mintage"],
    "coin_credit": ["eurio_id", "role", "name", "position"],
    "coin_topic": ["eurio_id", "lang", "topic"],
    "coin_name_i18n": ["eurio_id", "lang", "title"],
    "coin_description_i18n": ["eurio_id", "lang", "title", "description"],
    "coin_price": [
        "eurio_id", "grade", "p_low", "p_mid", "p_high", "currency", "source", "sampled_at",
    ],
}


def _project(rows: list[dict], cols: list[str]) -> list[dict]:
    return [{c: r.get(c) for c in cols} for r in rows]


def fetch_core_from_canonical(con: Any) -> dict[str, Any]:
    """Construit C3 depuis eurio.db en réutilisant les builders de la projection.

    Aucun réseau. Les filtres reproduisent exactement ceux que les requêtes
    PostgREST appliquaient : langues hors-ligne, prix de marché seulement.
    """
    from export.app_export.run import _BUILDERS, _IMPORT_FAILED

    def rows(table: str) -> list[dict]:
        if table in _IMPORT_FAILED:
            # Un builder cassé produirait un core silencieusement amputé — la
            # panne muette que ce dépôt collectionne. On refuse de construire.
            raise SystemExit(
                f"error: le builder `{table}` a échoué à l'import "
                f"({_IMPORT_FAILED[table]}). Le core serait incomplet."
            )
        builder = _BUILDERS.get(table)
        if builder is None:
            raise SystemExit(f"error: aucun builder pour `{table}`.")
        return builder(con)

    langs = set(_OFFLINE_LANGS)
    core = {
        "coins": _project(rows("coin"), _CORE_COLS["coins"]),
        "shared_reverse": _project(rows("shared_reverse"), _CORE_COLS["shared_reverse"]),
        "design_group": _project(rows("design_group"), _CORE_COLS["design_group"]),
        "mint": _project(rows("mint"), _CORE_COLS["mint"]),
        "coin_mint_release": _project(rows("coin_mint_release"), _CORE_COLS["coin_mint_release"]),
        "coin_credit": _project(rows("coin_credit"), _CORE_COLS["coin_credit"]),
        "coin_topic": _project(
            [r for r in rows("coin_topic") if r.get("lang") in langs], _CORE_COLS["coin_topic"]
        ),
        "coin_name_i18n": _project(
            [r for r in rows("coin_name_i18n") if r.get("lang") in langs],
            _CORE_COLS["coin_name_i18n"],
        ),
        "coin_description_i18n": _project(
            [r for r in rows("coin_description_i18n") if r.get("lang") in langs],
            _CORE_COLS["coin_description_i18n"],
        ),
        "coin_price": _project(
            [r for r in rows("coin_price") if r.get("kind") == "market"], _CORE_COLS["coin_price"]
        ),
    }
    return core


def fetch_core(client: httpx.Client) -> dict[str, Any]:
    """Fetch the C3 subset from Supabase as plain row lists.

    Conservé comme **référence de comparaison** pour `--verify`, plus comme
    source de build.
    """
    lang_filter = f"in.({','.join(_OFFLINE_LANGS)})"
    return {
        "coins": _fetch(client, "coin", ",".join(_COIN_COLS)),
        "shared_reverse": _fetch(client, "shared_reverse", "id,label,asset_name,map_version,applies_to"),
        "design_group": _fetch(client, "design_group", "id,designation,designation_i18n_json"),
        "mint": _fetch(client, "mint", "id,country,mark,city,display_name"),
        "coin_mint_release": _fetch(
            client, "coin_mint_release",
            "id,parent_type_id,mint_year,mint_id,issue_type,mintage",
        ),
        "coin_credit": _fetch(client, "coin_credit", "eurio_id,role,name,position"),
        "coin_topic": _fetch(client, "coin_topic", "eurio_id,lang,topic", {"lang": lang_filter}),
        "coin_name_i18n": _fetch(client, "coin_name_i18n", "eurio_id,lang,title", {"lang": lang_filter}),
        "coin_description_i18n": _fetch(
            client, "coin_description_i18n", "eurio_id,lang,title,description", {"lang": lang_filter},
        ),
        "coin_price": _fetch(
            client, "coin_price",
            "eurio_id,grade,p_low,p_mid,p_high,currency,source,sampled_at",
            {"kind": "eq.market"},
        ),
    }


# ---------------------------------------------------------------------------
# JSON serialization (proto) — nested per coin for easy rendering
# ---------------------------------------------------------------------------

def build_json(core: dict[str, Any]) -> dict[str, Any]:
    names = _group_by(core["coin_name_i18n"], "eurio_id")
    descs = _group_by(core["coin_description_i18n"], "eurio_id")
    prices = _group_by(core["coin_price"], "eurio_id")
    credits = _group_by(core["coin_credit"], "eurio_id")
    topics = _group_by(core["coin_topic"], "eurio_id")
    releases = _group_by(core["coin_mint_release"], "parent_type_id")

    coins = []
    for c in core["coins"]:
        eid = c["eurio_id"]
        coin = dict(c)
        coin["names"] = {r["lang"]: r["title"] for r in names.get(eid, [])}
        coin["descriptions"] = {
            r["lang"]: {"title": r["title"], "description": r["description"]}
            for r in descs.get(eid, [])
        }
        coin["prices"] = [
            {k: r[k] for k in ("grade", "p_low", "p_mid", "p_high", "currency", "source", "sampled_at")}
            for r in prices.get(eid, [])
        ]
        coin["credits"] = [
            {k: r[k] for k in ("role", "name", "position")} for r in credits.get(eid, [])
        ]
        coin["topics"] = [
            {k: r[k] for k in ("lang", "topic")} for r in topics.get(eid, [])
        ]
        coin["mint_releases"] = [
            {k: r[k] for k in ("id", "mint_year", "mint_id", "issue_type", "mintage")}
            for r in releases.get(eid, [])
        ]
        coins.append(coin)

    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offline_langs": list(_OFFLINE_LANGS),
        "shared_reverse": core["shared_reverse"],
        "design_groups": [
            {"id": d["id"], "designation": d["designation"]} for d in core["design_group"]
        ],
        "mints": core["mint"],
        "coin_count": len(coins),
        "coins": coins,
    }


# ---------------------------------------------------------------------------
# SQLite serialization (Android) — normalized tables
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = """
CREATE TABLE shared_reverse (id TEXT PRIMARY KEY, label TEXT, asset_name TEXT, map_version INTEGER, applies_to TEXT);
CREATE TABLE design_group (id TEXT PRIMARY KEY, designation TEXT);
CREATE TABLE mint (id TEXT PRIMARY KEY, country TEXT, mark TEXT, city TEXT, display_name TEXT);
CREATE TABLE coin (
  eurio_id TEXT PRIMARY KEY, country TEXT, country_name TEXT, year INTEGER, face_value_cents INTEGER,
  is_commemorative INTEGER, collector_only INTEGER, theme TEXT, design_description TEXT, mintage INTEGER,
  diameter_mm REAL, weight_g REAL, thickness_mm REAL, composition TEXT, shape TEXT, orientation TEXT,
  edge_description TEXT, edge_lettering TEXT, obverse_lettering TEXT, reverse_lettering TEXT,
  demonetized INTEGER, demonetized_on TEXT, design_group_id TEXT, variant_kind TEXT,
  canonical_eurio_id TEXT, series_id TEXT, shared_reverse_id TEXT
);
CREATE TABLE coin_name_i18n (eurio_id TEXT, lang TEXT, title TEXT, PRIMARY KEY (eurio_id, lang));
CREATE TABLE coin_description_i18n (eurio_id TEXT, lang TEXT, title TEXT, description TEXT, PRIMARY KEY (eurio_id, lang));
CREATE TABLE coin_topic (eurio_id TEXT, lang TEXT, topic TEXT);
CREATE TABLE coin_credit (eurio_id TEXT, role TEXT, name TEXT, position INTEGER);
CREATE TABLE coin_mint_release (id TEXT PRIMARY KEY, parent_type_id TEXT, mint_year INTEGER, mint_id TEXT, issue_type TEXT, mintage INTEGER);
CREATE TABLE coin_price (eurio_id TEXT, grade TEXT, p_low INTEGER, p_mid INTEGER, p_high INTEGER, currency TEXT, source TEXT, sampled_at TEXT);
CREATE INDEX idx_core_coin_country_year ON coin(country, year);
CREATE INDEX idx_core_price_eurio ON coin_price(eurio_id);
CREATE INDEX idx_core_release_parent ON coin_mint_release(parent_type_id);
"""

# (table, columns) — columns must match the rows fetched/derived.
_SQLITE_TABLES = [
    ("shared_reverse", ["id", "label", "asset_name", "map_version", "applies_to"]),
    ("design_group", ["id", "designation"]),
    ("mint", ["id", "country", "mark", "city", "display_name"]),
    ("coin", _COIN_COLS),
    ("coin_name_i18n", ["eurio_id", "lang", "title"]),
    ("coin_description_i18n", ["eurio_id", "lang", "title", "description"]),
    ("coin_topic", ["eurio_id", "lang", "topic"]),
    ("coin_credit", ["eurio_id", "role", "name", "position"]),
    ("coin_mint_release", ["id", "parent_type_id", "mint_year", "mint_id", "issue_type", "mintage"]),
    ("coin_price", ["eurio_id", "grade", "p_low", "p_mid", "p_high", "currency", "source", "sampled_at"]),
]


def build_sqlite(core: dict[str, Any], path: Path) -> None:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(_SQLITE_SCHEMA)
        source = {
            "shared_reverse": core["shared_reverse"],
            "design_group": [{"id": d["id"], "designation": d["designation"]} for d in core["design_group"]],
            "mint": core["mint"],
            "coin": core["coins"],
            "coin_name_i18n": core["coin_name_i18n"],
            "coin_description_i18n": core["coin_description_i18n"],
            "coin_topic": core["coin_topic"],
            "coin_credit": core["coin_credit"],
            "coin_mint_release": core["coin_mint_release"],
            "coin_price": core["coin_price"],
        }
        for table, cols in _SQLITE_TABLES:
            rows = source[table]
            placeholders = ",".join("?" * len(cols))
            con.executemany(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
                [tuple(r.get(c) for c in cols) for r in rows],
            )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Vérification C3 ⊆ C2 — calculée, pas supposée
# ---------------------------------------------------------------------------

# `id` est une PK surrogate régénérée à chaque rafraîchissement complet de la
# projection : la comparer opposerait deux numérotations, pas deux contenus.
_SURROGATE = {"coin_credit", "coin_topic", "coin_price", "coin_mint_release"}


def _norm(v: Any) -> Any:
    """Ramène SQLite et JSON PostgREST sur un terrain commun.

    Sans ça, `8.5` (float SQLite) et `"8.5"` (numeric PostgREST sérialisé en
    chaîne) compteraient comme différents et la vérification crierait au loup
    sur des lignes identiques.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    s = str(v)
    try:
        return round(float(s), 6)
    except ValueError:
        pass
    # Horodatages : trois écritures pour le même instant se croisent ici —
    # `2026-05-29`, `2026-05-29T…Z` (SQLite) et `2026-05-29T…+00:00`
    # (PostgREST). Sans cette normalisation la vérification signalait 1 651
    # fausses divergences sur `coin_price.sampled_at` ; un contrôle qui crie au
    # loup finit par ne plus être lu. La date nue devient minuit UTC, ce qui est
    # exactement ce que fait Postgres en la promouvant en timestamptz.
    if len(s) >= 10 and s[4] == "-" and s[7] == "-" and (len(s) == 10 or s[10] in "T "):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return s
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return s


def _rowset(rows: list[dict], cols: list[str], drop_id: bool) -> set[tuple]:
    keys = [c for c in cols if not (drop_id and c == "id")]
    return {tuple(_norm(r.get(c)) for c in keys) for r in rows}


def verify_subset(core: dict[str, Any], remote: dict[str, Any]) -> list[str]:
    """Renvoie la liste des violations. Vide = `C3 ⊆ C2` tient."""
    problems = []
    for table, cols in _CORE_COLS.items():
        drop_id = table in _SURROGATE
        local = _rowset(core[table], cols, drop_id)
        dist = _rowset(remote[table], cols, drop_id)
        missing = local - dist
        status = "ok" if not missing else f"{len(missing)} ligne(s) absente(s) de Supabase"
        print(f"    {table:24} local={len(local):>6}  prod={len(dist):>6}  {status}")
        if missing:
            ex = sorted(str(m)[:90] for m in list(missing)[:2])
            problems.append(f"{table}: {len(missing)} ligne(s) hors projection — ex. {ex}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-only", action="store_true", help="Skip the SQLite artifact.")
    ap.add_argument(
        "--verify",
        action="store_true",
        help="Vérifie que le core produit est inclus dans la projection Supabase.",
    )
    ap.add_argument(
        "--source",
        choices=("canonical", "supabase"),
        default="canonical",
        help="Source du core. `supabase` ne sert qu'à reproduire l'ancien comportement.",
    )
    args = ap.parse_args()

    if args.source == "canonical":
        from export.app_export.io import announce_source, get_sqlite_con

        announce_source()
        con = get_sqlite_con()
        try:
            core = fetch_core_from_canonical(con)
        finally:
            con.close()
        print("  source: canonique (eurio.db via les builders de la projection)")
    else:
        client = get_pg_client()
        try:
            core = fetch_core(client)
        finally:
            client.close()
        print("  source: Supabase")

    counts = {k: len(v) for k, v in core.items()}
    print("  fetched:", ", ".join(f"{k}={v}" for k, v in counts.items()))

    if args.verify:
        print("  vérification C3 ⊆ Supabase :")
        try:
            client = get_pg_client()
            try:
                remote = fetch_core(client)
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001
            print(
                f"    Supabase injoignable ({exc.__class__.__name__}) — vérification "
                f"IMPOSSIBLE, pas invalidée.\n"
                f"    Les artefacts n'ont pas été écrits : on ne publie pas un core "
                f"non vérifié quand la vérification a été demandée.",
                file=sys.stderr,
            )
            return 4
        problems = verify_subset(core, remote)
        if problems:
            print("\n  VIOLATION de C3 ⊆ C2 — artefacts NON écrits :", file=sys.stderr)
            for p in problems:
                print(f"    · {p}", file=sys.stderr)
            print(
                "\n  La projection Supabase est en retard sur le canonique. "
                "Rejoue `python -m export.app_export.run --apply`.",
                file=sys.stderr,
            )
            return 3
        print("    ✓ inclusion vérifiée")

    payload = build_json(core)
    _JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    _JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    size_mb = _JSON_PATH.stat().st_size / 1_048_576
    print(f"  wrote {_JSON_PATH.relative_to(_REPO_ROOT)} ({size_mb:.1f} MB, {payload['coin_count']} coins)")

    if not args.json_only:
        build_sqlite(core, _DB_PATH)
        size_mb = _DB_PATH.stat().st_size / 1_048_576
        print(f"  wrote {_DB_PATH.relative_to(_REPO_ROOT)} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
