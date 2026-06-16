"""Push `eurio.db` → Supabase — Chunk 4 harmonisation.

Voir docs/data-harmonization/{architecture,plan}.md.

Avant ce chunk : ce script lisait `eurio_referential.json` (devenu périmé
depuis le Chunk 1b où `coins` est devenu canonique en SQLite). Maintenant :
projection strictement descendante **`eurio.db` → Supabase**, sur les 3
tables consommées par l'app — `coins`, `source_observations`,
`coin_market_prices`. Idempotent (upsert sur clé naturelle), jamais de
delete (les orphelins éventuels côté Supabase sont remontés par la commande
de détection de dérive, `scripts/detect_supabase_drift.py`).

Le matcher flou ayant été retiré, on ne synchronise plus `matching_decisions`
ni `review_queue` — ce sont des artefacts historiques figés côté Supabase.

Usage::

    python -m export.sync_to_supabase                  # tout
    python -m export.sync_to_supabase --dry-run        # juste les compteurs
    python -m export.sync_to_supabase --coins-only     # coins seulement
    python -m export.sync_to_supabase --verify         # post-sync : contrôle
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"
UPSERT_BATCH_SIZE = 500


# ---------- env ----------
# Canonical secret accessor (single source: secrets/dev.env via .envrc).
# Re-exported here so the many `from export.sync_to_supabase import load_env`
# callers keep working unchanged.
from shared.env import load_env  # noqa: E402


# ---------- PostgREST client ----------

class PostgrestClient:
    """Minimal PostgREST client avec upsert / count."""

    def __init__(self, url: str, service_key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self._client = httpx.Client(
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=60,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PostgrestClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def upsert(self, table: str, rows: list[dict], *, on_conflict: str | None = None) -> None:
        if not rows:
            return
        for i in range(0, len(rows), UPSERT_BATCH_SIZE):
            batch = rows[i : i + UPSERT_BATCH_SIZE]
            headers = {"Prefer": "resolution=merge-duplicates,return=minimal"}
            params: dict[str, str] = {}
            if on_conflict:
                params["on_conflict"] = on_conflict
            resp = self._client.post(
                f"{self.base}/{table}", json=batch, headers=headers, params=params,
            )
            if resp.status_code >= 400:
                print(f"  FAIL batch {i}-{i+len(batch)}: HTTP {resp.status_code}")
                print(f"  {resp.text[:400]}")
                resp.raise_for_status()

    def count(self, table: str) -> int:
        resp = self._client.get(
            f"{self.base}/{table}",
            params={"select": "count"},
            headers={"Prefer": "count=exact"},
        )
        resp.raise_for_status()
        hdr = resp.headers.get("content-range") or ""
        return int(hdr.rsplit("/", 1)[1]) if "/" in hdr else 0

    def get(self, table: str, params: dict[str, str]) -> list[dict]:
        resp = self._client.get(f"{self.base}/{table}", params=params)
        resp.raise_for_status()
        return resp.json()


# ---------- eurio.db → Supabase row shapes ----------

def db_coins_rows(conn: sqlite3.Connection) -> list[dict]:
    """`coins` + tables filles → forme attendue par `coins` Supabase."""
    cross_by_eid: dict[str, dict[str, Any]] = {}
    for r in conn.execute("SELECT eurio_id, ref_type, ref_value FROM coin_cross_refs"):
        cross_by_eid.setdefault(r["eurio_id"], {})[r["ref_type"]] = r["ref_value"]

    img_by_eid: dict[str, dict[str, Any]] = {}
    for r in conn.execute(
        "SELECT eurio_id, source, role, url FROM coin_canonical_images WHERE url IS NOT NULL"
    ):
        d = img_by_eid.setdefault(r["eurio_id"], {})
        # Format historique attendu par bench_routes et catalog_snapshot :
        # {obverse: url, obverse_source: 'numista', reverse: url, …}
        d[r["role"]] = r["url"]
        d[f"{r['role']}_source"] = r["source"]

    nat_by_eid: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT eurio_id, country_iso2 FROM coin_national_variants ORDER BY country_iso2"
    ):
        nat_by_eid.setdefault(r["eurio_id"], []).append(r["country_iso2"])

    sources_by_eid: dict[str, list[str]] = {}
    for r in conn.execute("SELECT DISTINCT eurio_id, source FROM coin_observations"):
        sources_by_eid.setdefault(r["eurio_id"], []).append(r["source"])

    rows: list[dict] = []
    for c in conn.execute("SELECT * FROM coins"):
        eid = c["eurio_id"]
        cross = dict(cross_by_eid.get(eid, {}))
        if c["numista_id"] is not None:
            cross["numista_id"] = c["numista_id"]
        imported = (c["imported_at"] or "")[:10] or date.today().isoformat()
        updated = (c["updated_at"] or c["imported_at"] or "")[:10] or date.today().isoformat()
        rows.append({
            "eurio_id": eid,
            "country": c["country"],
            "year": c["year"],
            "face_value": float(c["face_value"]),
            "currency": c["currency"] or "EUR",
            "is_commemorative": bool(c["is_commemorative"]),
            "collector_only": bool(c["collector_only"]),
            "theme": c["theme"],
            "design_description": c["design_description"],
            "design_group_id": c["design_group_id"],
            "national_variants": nat_by_eid.get(eid) or None,
            "mintage": c["mintage"],
            "images": img_by_eid.get(eid) or {},
            "cross_refs": cross,
            "sources_used": sorted(sources_by_eid.get(eid, [])),
            "needs_review": bool(c["needs_review"]),
            "review_reason": c["review_reason"],
            "first_seen": imported,
            "last_updated": updated,
        })
    return rows


# Mapping source-de-blob → (source canonique, observation_type) côté Supabase.
# Hérité de l'ancien flatten JSON → conserve l'unicité (eurio_id, source,
# source_native_id, observation_type) côté DB cible.
_OBS_MAPPING = {
    "wikipedia":     ("wikipedia", "mintage"),
    "lmdlp_mintage": ("lmdlp",     "mintage"),
    "ebay_market":   ("ebay",      "market_stats"),
    "bce_comm":      ("bce_comm",  "coin_info"),
}


def db_observations_rows(conn: sqlite3.Connection) -> list[dict]:
    """`coin_observations` → forme `source_observations` Supabase.

    Re-éclate les listes (lmdlp_variants, mdp_issue) en N lignes par variante
    pour coller à la contrainte unique côté Supabase.
    """
    rows: list[dict] = []
    for r in conn.execute(
        "SELECT eurio_id, source, payload_json FROM coin_observations"
    ):
        eid, src = r["eurio_id"], r["source"]
        try:
            payload = json.loads(r["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        # Listes : 1 ligne par item.
        if src == "lmdlp_variants" and isinstance(payload, list):
            for v in payload:
                if isinstance(v, dict):
                    rows.append({
                        "eurio_id": eid, "source": "lmdlp",
                        "source_native_id": v.get("sku"),
                        "observation_type": "variant", "payload": v,
                    })
        elif src == "mdp_issue" and isinstance(payload, list):
            for v in payload:
                if isinstance(v, dict):
                    rows.append({
                        "eurio_id": eid, "source": "mdp",
                        "source_native_id": v.get("sku"),
                        "observation_type": "issue_price", "payload": v,
                    })
        elif src in _OBS_MAPPING and isinstance(payload, dict):
            sup_src, obs_type = _OBS_MAPPING[src]
            rows.append({
                "eurio_id": eid, "source": sup_src, "source_native_id": None,
                "observation_type": obs_type, "payload": payload,
            })
        # autres clés inconnues → passe générique
        elif isinstance(payload, dict):
            rows.append({
                "eurio_id": eid, "source": src, "source_native_id": None,
                "observation_type": "legacy_import", "payload": payload,
            })
    return rows


def db_i18n_rows(conn: sqlite3.Connection) -> list[dict]:
    """`coin_names_i18n` SQLite → Supabase rows."""
    rows: list[dict] = []
    for r in conn.execute(
        "SELECT eurio_id, lang, title, source, confidence, model, fetched_at "
        "FROM coin_names_i18n"
    ):
        rows.append({
            "eurio_id": r["eurio_id"],
            "lang": r["lang"],
            "title": r["title"],
            "source": r["source"],
            "confidence": r["confidence"],
            "model": r["model"],
            "fetched_at": r["fetched_at"],
        })
    return rows


def db_aliases_rows(conn: sqlite3.Connection) -> list[dict]:
    """`coin_aliases` SQLite → Supabase rows."""
    rows: list[dict] = []
    for r in conn.execute(
        "SELECT eurio_id, lang, alias, source, confidence, fetched_at "
        "FROM coin_aliases"
    ):
        rows.append({
            "eurio_id": r["eurio_id"],
            "lang": r["lang"],
            "alias": r["alias"],
            "source": r["source"],
            "confidence": r["confidence"],
            "fetched_at": r["fetched_at"],
        })
    return rows


def db_market_prices_rows(conn: sqlite3.Connection) -> list[dict]:
    """Variantes LMDLP → `coin_market_prices` (1 ligne par variante avec prix)."""
    rows: list[dict] = []
    for r in conn.execute(
        "SELECT eurio_id, payload_json FROM coin_observations WHERE source='lmdlp_variants'"
    ):
        try:
            variants = json.loads(r["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(variants, list):
            continue
        for v in variants:
            if not isinstance(v, dict):
                continue
            price = v.get("price_eur")
            if price is None:
                continue
            quality = v.get("quality") or "unknown"
            sampled_at = v.get("sampled_at") or datetime.now(timezone.utc).isoformat()
            rows.append({
                "eurio_id": r["eurio_id"],
                "source": "lmdlp",
                "quality": quality,
                "p25": None, "p50": float(price), "p75": None,
                "samples_count": 1,
                "with_sales_count": 1 if v.get("in_stock") else 0,
                "query_used": v.get("sku"),
                "fetched_at": sampled_at,
            })
    return rows


# ---------- verify ----------

def verify(client: PostgrestClient, db_coins: list[dict]) -> dict:
    """Compare les compteurs Supabase à eurio.db + spot-check 5 coins."""
    sb_counts = {t: client.count(t) for t in ("coins", "source_observations", "coin_market_prices")}
    report = {"supabase_counts": sb_counts, "db_coins": len(db_coins), "samples": []}

    if not db_coins:
        return report
    sample_ids = [db_coins[i]["eurio_id"] for i in range(0, len(db_coins), max(1, len(db_coins) // 5))][:5]
    in_filter = ",".join(f'"{e}"' for e in sample_ids)
    sb_rows = client.get(
        "coins",
        {"select": "eurio_id,country,year,theme,design_group_id", "eurio_id": f"in.({in_filter})"},
    )
    sb_by_eid = {r["eurio_id"]: r for r in sb_rows}
    db_by_eid = {r["eurio_id"]: r for r in db_coins if r["eurio_id"] in sample_ids}
    for eid in sample_ids:
        d, s = db_by_eid.get(eid), sb_by_eid.get(eid)
        match = bool(s) and all(s.get(k) == d.get(k) for k in ("country", "year", "theme", "design_group_id"))
        report["samples"].append({"eurio_id": eid, "in_supabase": bool(s), "match": match})
    return report


# ---------- main ----------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--coins-only", action="store_true")
    ap.add_argument("--verify", action="store_true", help="post-sync : count + spot-check")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    store = Store(args.db)
    conn = store._connection()  # noqa: SLF001

    coins_rows = db_coins_rows(conn)
    obs_rows = db_observations_rows(conn)
    market_rows = db_market_prices_rows(conn)
    i18n_rows = db_i18n_rows(conn)
    aliases_rows = db_aliases_rows(conn)

    print("Source counts (eurio.db) :")
    print(f"  coins         : {len(coins_rows)}")
    print(f"  observations  : {len(obs_rows)}")
    print(f"  market_prices : {len(market_rows)}")
    print(f"  coin_names_i18n : {len(i18n_rows)}")
    print(f"  coin_aliases    : {len(aliases_rows)}")

    if args.dry_run:
        print("\n[dry-run] aucun appel HTTP.")
        return

    env = load_env()
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERROR : SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants", file=sys.stderr)
        sys.exit(1)

    with PostgrestClient(url, key) as client:
        print("\nUpsert coins...")
        client.upsert("coins", coins_rows, on_conflict="eurio_id")
        print(f"  Supabase coins now : {client.count('coins')}")

        if not args.coins_only:
            print("\nUpsert source_observations...")
            client.upsert(
                "source_observations", obs_rows,
                on_conflict="eurio_id,source,source_native_id,observation_type",
            )
            print(f"  Supabase source_observations now : {client.count('source_observations')}")

            print("\nUpsert coin_market_prices...")
            client.upsert(
                "coin_market_prices", market_rows,
                on_conflict="eurio_id,source,quality,fetched_at",
            )
            print(f"  Supabase coin_market_prices now : {client.count('coin_market_prices')}")

            print("\nUpsert coin_names_i18n...")
            client.upsert(
                "coin_names_i18n", i18n_rows,
                on_conflict="eurio_id,lang",
            )
            print(f"  Supabase coin_names_i18n now : {client.count('coin_names_i18n')}")

            print("\nUpsert coin_aliases...")
            client.upsert(
                "coin_aliases", aliases_rows,
                on_conflict="eurio_id,lang,alias",
            )
            print(f"  Supabase coin_aliases now : {client.count('coin_aliases')}")

        if args.verify:
            print("\nVerify...")
            print(json.dumps(verify(client, coins_rows), indent=2, ensure_ascii=False))

    print("\n" + "=" * 60 + "\nSync OK.\n" + "=" * 60)


if __name__ == "__main__":
    main()
