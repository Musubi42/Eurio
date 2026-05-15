"""Migration script: V1 `coins` → V2 multi-source ref schema.

Chunk 2c du plan référentiel V2 (cf. docs/research/referential-v2.md §8).
À utiliser une fois la migration SQL appliquée (20260515_referential_v2.sql).

Ce que fait ce script
---------------------
1. Lit toutes les lignes de la table `coins` (= niveau Type V2, toutes denoms).
2. Pour chaque coin, transforme :
     - `cross_refs` JSON → N lignes `coin_source_refs`
3. N'INSÈRE PAS de variants ni de mint_releases — Chunk 3 (apply audit
   decisions) s'en chargera ensuite.

Mode `--dry-run` obligatoire pour audit visuel des chiffres avant write.

Idempotence
-----------
La table `coin_source_refs` a un PK (source, native_id) et un UNIQUE
(coin_type_id, source, native_id). Re-run = idempotent : les rows existantes
ne sont pas dupliquées (upsert on_conflict='source,native_id').

Mapping cross_refs → coin_source_refs
-------------------------------------
Champ JSON dans coins.cross_refs    → source       native_id        native_url
─────────────────────────────────────────────────────────────────────────────
"numista_id": 102697                 → numista     "102697"         null
"wikipedia_url": "https://..."       → wikipedia   <url>            <url>
"joue_code": "EU-2017/L 217/12"      → joue        <code>           null
"mdp_product_id" / "mdp_skus" (arr)  → mdp         <sku>            null
"mdp_url" / "mdp_urls" (arr)         → mdp         <url>            <url>
"lmdlp_skus" (array)                 → lmdlp       <sku>            null
"lmdlp_url"                          → lmdlp       <url>            <url>
"bce_comm_url"                       → bce         <url>            <url>
"catawiki_url"                       → catawiki    <url>            <url>
"wikidata_qid": "Q12345"             → wikidata    "Q12345"         null
"ngc_id" / "pcgs_id"                 → ngc/pcgs    <id>             null

Les clés `_skus` / `_urls` au pluriel sont des arrays → N rows par entry.

`coins.sources_used` array (provenance) reste en place V2.0, désaffectation
plus tard. Ce n'est pas un cross-ref (souvent sans native_id, ex
`wikipedia_country` = "tel article de pays liste cette pièce").

Usage
-----
    .venv/bin/python referential/migrate_to_v2.py --dry-run
    .venv/bin/python referential/migrate_to_v2.py --apply
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.supabase_client import SupabaseClient, load_env  # noqa: E402


# ─── cross_refs → coin_source_refs adapters ──────────────────────────────────


def _stringify(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, str):
        return v.strip() or None
    return None


# Each entry maps a cross_refs key to (source, kind, url_for_value_fn).
#   kind: 'scalar' → value is a string/int → 1 row
#         'array'  → value is a list → N rows
#   url_for_value_fn(v): given the value (scalar) returns the native_url
#         (typically the value itself when it's an URL, else None).
CROSS_REFS_MAPPING = [
    ("numista_id",     "numista",   "scalar", lambda _: None),
    ("wikipedia_url",  "wikipedia", "scalar", _stringify),
    ("joue_code",      "joue",      "scalar", lambda _: None),
    ("mdp_product_id", "mdp",       "scalar", lambda _: None),
    ("mdp_skus",       "mdp",       "array",  lambda _: None),
    ("mdp_url",        "mdp",       "scalar", _stringify),
    ("mdp_urls",       "mdp",       "array",  _stringify),
    ("lmdlp_skus",     "lmdlp",     "array",  lambda _: None),
    ("lmdlp_url",      "lmdlp",     "scalar", _stringify),
    ("bce_comm_url",   "bce",       "scalar", _stringify),
    ("catawiki_url",   "catawiki",  "scalar", _stringify),
    ("wikidata_qid",   "wikidata",  "scalar", lambda _: None),
    ("ngc_id",         "ngc",       "scalar", lambda _: None),
    ("pcgs_id",        "pcgs",      "scalar", lambda _: None),
]


def cross_refs_to_source_refs(eurio_id: str, cross_refs: dict | None) -> list[dict]:
    """Project a coins.cross_refs JSON into coin_source_refs rows.

    Handles both scalar values (1 row) and arrays of values (N rows). Dedupes
    on (source, native_id) since the SQL PK enforces uniqueness anyway.
    """
    if not cross_refs:
        return []
    rows: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()

    for key, source, kind, url_fn in CROSS_REFS_MAPPING:
        if key not in cross_refs:
            continue
        raw = cross_refs[key]
        values: list = raw if (kind == "array" and isinstance(raw, list)) else [raw]
        for v in values:
            native_id = _stringify(v)
            if native_id is None:
                continue
            marker = (source, native_id)
            if marker in seen_keys:
                continue
            seen_keys.add(marker)
            rows.append({
                "coin_type_id": eurio_id,
                "source": source,
                "native_id": native_id,
                "native_url": url_fn(v),
            })
    return rows


# ─── Migration logic ─────────────────────────────────────────────────────────


def fetch_all_coins(sb: SupabaseClient) -> list[dict]:
    """Read every coin via PostgREST keyset pagination."""
    coins: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        batch = sb.query(
            "coins",
            select="eurio_id,cross_refs,sources_used",
            params={
                "order": "eurio_id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        if not batch:
            break
        coins.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return coins


def build_source_refs(coins: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Return all coin_source_refs rows + per-source counts."""
    all_rows: list[dict] = []
    per_source = Counter()
    skipped_no_refs = 0
    unknown_keys = Counter()

    known_keys = {k for k, *_ in CROSS_REFS_MAPPING}

    for c in coins:
        eid = c["eurio_id"]
        cr = c.get("cross_refs") or {}
        if not cr:
            skipped_no_refs += 1
            continue
        # Track keys we don't know about — surface them for review.
        for k in cr.keys():
            if k not in known_keys:
                unknown_keys[k] += 1
        rows = cross_refs_to_source_refs(eid, cr)
        for r in rows:
            per_source[r["source"]] += 1
        all_rows.extend(rows)

    return all_rows, {
        "skipped_no_refs": skipped_no_refs,
        "per_source": dict(per_source),
        "unknown_keys": dict(unknown_keys),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Preview counts, no write.")
    g.add_argument("--apply", action="store_true", help="Upsert into Supabase.")
    args = parser.parse_args()

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1

    sb = SupabaseClient(url, key)
    try:
        print("Fetching coins from Supabase...")
        coins = fetch_all_coins(sb)
        print(f"  Read {len(coins)} coins.")

        rows, stats = build_source_refs(coins)
        print()
        print("=" * 60)
        print(f"  V2 migration preview ({'DRY-RUN' if args.dry_run else 'APPLY'})")
        print("=" * 60)
        print(f"  Coins inspected            : {len(coins)}")
        print(f"  Coins with no cross_refs   : {stats['skipped_no_refs']}")
        print(f"  Total coin_source_refs rows: {len(rows)}")
        print(f"\n  Rows per source:")
        for src, n in sorted(stats["per_source"].items(), key=lambda x: -x[1]):
            print(f"    {src:15s} {n:>5}")
        if stats["unknown_keys"]:
            print(f"\n  Unmapped cross_refs keys (review needed):")
            for k, n in sorted(stats["unknown_keys"].items(), key=lambda x: -x[1]):
                print(f"    {k!r:25s} appears in {n} coins")
        print()
        print("  Sample (first 8 rows):")
        for r in rows[:8]:
            url_repr = (r["native_url"] or "")[:50]
            print(f"    {r['coin_type_id']:50s} → {r['source']:10s} {r['native_id']:15s} {url_repr}")

        if args.dry_run:
            print("\n--dry-run: nothing written. Re-run with --apply to commit.")
            return 0

        print(f"\nUpserting {len(rows)} rows into coin_source_refs (batches of 500)...")
        # PostgREST upsert on the composite UNIQUE (coin_type_id, source, native_id).
        sb.upsert(
            "coin_source_refs",
            rows,
            on_conflict="coin_type_id,source,native_id",
        )
        print("  Done.")

        # Verify with a count query.
        existing = sb.count("coin_source_refs")
        print(f"\n  coin_source_refs total rows now: {existing}")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
