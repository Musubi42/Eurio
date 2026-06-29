"""Enrich the `coins` referential with the metadata required by the sets DSL.

Canonical target is the SQLite store `eurio.db` (data-layer-unification: SQLite
is the single source of truth, Supabase is only a read-only projection). The
script is idempotent and dry-run by default.

Against the **canonical SQLite store** (``--target sqlite``, the default) it does
two things:

1. **Seed `coin_series`** from `ml/data/coin_series_seed.json` (~32 entries for
   the whole euro area history). Upserts on `id` (two-pass to satisfy the
   ``supersedes_*`` self-FKs). The seed's ``designation_i18n`` object is stored
   in the ``designation_i18n_json`` TEXT column.

2. **Populate `coins.series_id`** (FK → coin_series.id) for circulation coins
   only (``is_commemorative = 0``), by matching (country, year) against the date
   range of each series. Commemoratives are left with series_id = NULL (they are
   standalone issues not part of a circulation series).

   `coins.issue_type` is intentionally **not** populated here: that column is a
   Supabase-era artifact with no canonical home (the canonical `coins` table has
   no `issue_type`; the V2 referential keeps issue_type on `mint_releases`
   instead), and the legacy commemo-common/national split relied on the dropped
   `national_variants` field (now modelled via `variant_kind`/`variant_label`).
   Reviving it faithfully is a separate chunk — tracked in
   `docs/work-in-progress/auth-redesign/ROADMAP.md` (D2 notes).

The legacy **Supabase** path (``--target supabase``) keeps the original 3-part
behaviour (incl. `issue_type`) via PostgREST, for back-compat only. Supabase is
being retired as a write target — prefer ``--target sqlite``.

Usage:
    python -m referential.enrich_coins_metadata                  # dry-run, SQLite (default)
    python -m referential.enrich_coins_metadata --apply          # write to eurio.db
    python -m referential.enrich_coins_metadata --apply --skip-seed   # only enrich coins.series_id
    python -m referential.enrich_coins_metadata --target supabase --apply   # legacy PostgREST path
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SEED_PATH = Path(__file__).parent.parent / "data" / "coin_series_seed.json"


def _resolve_db_path() -> Path:
    """Canonical eurio.db path: ``EURIO_DB_PATH`` env, else ml/state/eurio.db."""
    env = os.environ.get("EURIO_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "state" / "eurio.db"


# ---------- issue_type derivation ----------


def derive_issue_type(coin: dict[str, Any]) -> str:
    """Derive the canonical issue_type from the legacy fields on a coin row."""
    if not coin.get("is_commemorative"):
        return "circulation"
    if coin.get("national_variants"):
        return "commemo-common"
    return "commemo-national"


# ---------- series matching ----------


class SeriesIndex:
    """(country, year) → series_id lookup built from the coin_series seed.

    Country keys are normalized to lowercase for case-insensitive matching
    against the `coins.country` column (which is stored uppercase by the
    legacy bootstrap, while the seed json uses lowercase ISO2).
    """

    def __init__(self, series: list[dict[str, Any]]):
        self._by_country: dict[str, list[tuple[int, int, str]]] = {}
        for s in series:
            country = s["country"].lower()
            start = int(s["minting_started_at"].split("-")[0])
            end_raw = s.get("minting_ended_at")
            end = int(end_raw.split("-")[0]) if end_raw else 9999
            self._by_country.setdefault(country, []).append((start, end, s["id"]))
        for lst in self._by_country.values():
            lst.sort()

    def lookup(self, country: str, year: int) -> str | None:
        for start, end, sid in self._by_country.get(country.lower(), []):
            if start <= year <= end:
                return sid
        return None

    def countries(self) -> set[str]:
        return set(self._by_country.keys())


# ---------- canonical SQLite I/O (default target) ----------


def seed_coin_series_sqlite(store: Any, series: list[dict[str, Any]], apply: bool) -> int:
    """Upsert coin_series into eurio.db. Two-pass for the self-referential FKs.

    Returns the coin_series row count after the operation (or the seed length in
    dry-run). The seed's ``designation_i18n`` object → ``designation_i18n_json``.
    """
    if not apply:
        return len(series)

    base_rows = [
        (
            s["id"],
            s["country"],
            s["designation"],
            json.dumps(s["designation_i18n"], ensure_ascii=False)
            if s.get("designation_i18n")
            else None,
            s.get("description"),
            s["minting_started_at"],
            s.get("minting_ended_at"),
            s.get("minting_end_reason"),
        )
        for s in series
    ]
    ref_rows = [
        (s.get("supersedes_series_id"), s.get("superseded_by_series_id"), s["id"])
        for s in series
        if s.get("supersedes_series_id") or s.get("superseded_by_series_id")
    ]

    with store._writing() as conn:
        # Pass 1: upsert everything except the self-FKs.
        conn.executemany(
            "INSERT INTO coin_series "
            "(id, country, designation, designation_i18n_json, description, "
            " minting_started_at, minting_ended_at, minting_end_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  country = excluded.country, "
            "  designation = excluded.designation, "
            "  designation_i18n_json = excluded.designation_i18n_json, "
            "  description = excluded.description, "
            "  minting_started_at = excluded.minting_started_at, "
            "  minting_ended_at = excluded.minting_ended_at, "
            "  minting_end_reason = excluded.minting_end_reason, "
            "  updated_at = datetime('now')",
            base_rows,
        )
        # Pass 2: now that all rows exist, set the supersedes/superseded refs.
        if ref_rows:
            conn.executemany(
                "UPDATE coin_series SET supersedes_series_id = ?, "
                "superseded_by_series_id = ?, updated_at = datetime('now') WHERE id = ?",
                ref_rows,
            )
        return conn.execute("SELECT COUNT(*) FROM coin_series").fetchone()[0]


def enrich_series_id_sqlite(
    store: Any, index: SeriesIndex, apply: bool
) -> tuple[Counter[str | None], list[str], int]:
    """Set ``coins.series_id`` for circulation coins via (country, year) match.

    Returns (series distribution, unmatched circulation ids, n_updates_written).
    Only circulation coins (``is_commemorative = 0``) get a series; others are
    forced to NULL. Updates are emitted only when the value actually changes.
    """
    conn = store._connection()
    coins = conn.execute(
        "SELECT eurio_id, country, year, is_commemorative, series_id FROM coins"
    ).fetchall()

    series_counter: Counter[str | None] = Counter()
    updates: list[tuple[str | None, str]] = []
    unmatched_circulation: list[str] = []

    for c in coins:
        if c["is_commemorative"]:
            new_series: str | None = None
        else:
            new_series = index.lookup(c["country"], c["year"])
            if new_series is None:
                unmatched_circulation.append(
                    f"{c['eurio_id']} ({c['country']}/{c['year']})"
                )
        series_counter[new_series] += 1
        if c["series_id"] != new_series:
            updates.append((new_series, c["eurio_id"]))

    written = 0
    if apply and updates:
        with store._writing() as wconn:
            wconn.executemany(
                "UPDATE coins SET series_id = ?, updated_at = datetime('now') "
                "WHERE eurio_id = ?",
                updates,
            )
        written = len(updates)

    return series_counter, unmatched_circulation, (written if apply else len(updates))


def main_sqlite(args: argparse.Namespace, series_seed: list[dict[str, Any]], index: SeriesIndex) -> None:
    from store import Store  # local import: avoid pulling the store on --help

    db_path = Path(args.db_path) if args.db_path else _resolve_db_path()
    print(f"Target: SQLite canonical store → {db_path}")
    if not db_path.exists():
        print(f"ERROR: eurio.db not found at {db_path}")
        sys.exit(1)
    store = Store(db_path)

    # Pass 1: seed coin_series
    if not args.skip_seed:
        print(f"\n[1/2] Seeding coin_series ({len(series_seed)} rows)...")
        if args.apply:
            count = seed_coin_series_sqlite(store, series_seed, apply=True)
            print(f"  coin_series count after upsert: {count}")
        else:
            seed_coin_series_sqlite(store, series_seed, apply=False)
            print(f"  [dry-run] would upsert {len(series_seed)} rows")

    # Pass 2: populate coins.series_id
    print("\n[2/2] Matching circulation coins → series_id...")
    series_counter, unmatched, n = enrich_series_id_sqlite(store, index, apply=args.apply)

    print("\n  series_id distribution (top 10):")
    for k, v in series_counter.most_common(10):
        print(f"    {str(k):30} {v:5}")

    circulation_total = sum(v for k, v in series_counter.items() if k is not None) + len(unmatched)
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} circulation coins did not match any series:")
        for line in unmatched[:20]:
            print(f"    {line}")
        if len(unmatched) > 20:
            print(f"    ... and {len(unmatched) - 20} more")
        print(
            "  These likely indicate a gap in coin_series_seed.json "
            "(missing country or date range). Fix the seed, not this script."
        )
    else:
        print(f"  ✓ All {circulation_total} circulation coins matched a series")

    if args.apply:
        print(f"\n  ✓ wrote {n} coins.series_id update(s)")
    else:
        print(f"\n  [dry-run] would update {n} coins.series_id")

    print("\n=== done ===")


# ---------- Supabase I/O (legacy --target supabase) ----------


def fetch_all_coins(client: PostgrestClient) -> list[dict[str, Any]]:
    """Fetch all coin rows with only the fields we need for enrichment."""
    select = "eurio_id,country,year,is_commemorative,national_variants,issue_type,series_id"
    rows: list[dict[str, Any]] = []
    batch = 1000
    offset = 0
    while True:
        resp = client._client.get(
            f"{client.base}/coins",
            params={"select": select, "limit": batch, "offset": offset},
            headers={"Prefer": "count=exact"},
        )
        resp.raise_for_status()
        chunk = resp.json()
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < batch:
            break
        offset += batch
    return rows


def upsert_coin_series(client: PostgrestClient, series: list[dict[str, Any]]) -> None:
    """Upsert coin_series rows. Idempotent on `id`."""
    rows = [
        {
            "id": s["id"],
            "country": s["country"],
            "designation": s["designation"],
            "designation_i18n": s.get("designation_i18n"),
            "description": s.get("description"),
            "minting_started_at": s["minting_started_at"],
            "minting_ended_at": s.get("minting_ended_at"),
            "minting_end_reason": s.get("minting_end_reason"),
            "supersedes_series_id": s.get("supersedes_series_id"),
            "superseded_by_series_id": s.get("superseded_by_series_id"),
        }
        for s in series
    ]
    # Two-pass to avoid FK violations on supersedes/superseded_by:
    # pass 1 upserts without self-references, pass 2 updates the refs.
    pass1 = [
        {**r, "supersedes_series_id": None, "superseded_by_series_id": None}
        for r in rows
    ]
    client.upsert("coin_series", pass1, on_conflict="id")
    # Pass 2: set the refs
    pass2 = [
        {
            "id": r["id"],
            "country": r["country"],
            "designation": r["designation"],
            "minting_started_at": r["minting_started_at"],
            "supersedes_series_id": r["supersedes_series_id"],
            "superseded_by_series_id": r["superseded_by_series_id"],
        }
        for r in rows
        if r["supersedes_series_id"] or r["superseded_by_series_id"]
    ]
    if pass2:
        client.upsert("coin_series", pass2, on_conflict="id")


def update_coin_metadata(client: PostgrestClient, updates: list[dict[str, Any]]) -> None:
    """Update issue_type + series_id on a batch of coins.

    Uses PostgREST upsert on eurio_id — requires us to supply the full row
    identity. We fetch the existing row shapes we need and send only the
    mutated fields plus the PK.
    """
    if not updates:
        return
    client.upsert("coins", updates, on_conflict="eurio_id")


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Enrich coins with series_id (+ issue_type on legacy Supabase target)")
    ap.add_argument("--apply", action="store_true", help="Actually write (default is dry-run)")
    ap.add_argument("--skip-seed", action="store_true", help="Don't upsert coin_series, only enrich coins")
    ap.add_argument(
        "--target",
        choices=("sqlite", "supabase"),
        default="sqlite",
        help="Write target: 'sqlite' = canonical eurio.db (default), 'supabase' = legacy PostgREST",
    )
    ap.add_argument("--db-path", help="Override eurio.db path (sqlite target only; default: EURIO_DB_PATH or ml/state/eurio.db)")
    return ap.parse_args()


def main_supabase(args: argparse.Namespace, series_seed: list[dict[str, Any]], index: SeriesIndex) -> None:
    from export.sync_to_supabase import PostgrestClient, load_env

    # Load env + client
    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from .env")
        sys.exit(1)

    with PostgrestClient(url, key) as client:
        # Pass 1: seed coin_series
        if not args.skip_seed:
            print(f"\n[1/3] Seeding coin_series ({len(series_seed)} rows)...")
            if args.apply:
                upsert_coin_series(client, series_seed)
                count = client.count("coin_series")
                print(f"  coin_series count after upsert: {count}")
            else:
                print(f"  [dry-run] would upsert {len(series_seed)} rows")

        # Pass 2: fetch all coins
        print("\n[2/3] Fetching coins...")
        coins = fetch_all_coins(client)
        print(f"  fetched {len(coins)} coins")

        # Compute updates
        type_counter: Counter[str] = Counter()
        series_counter: Counter[str | None] = Counter()
        updates: list[dict[str, Any]] = []
        unmatched_circulation: list[str] = []

        for coin in coins:
            new_type = derive_issue_type(coin)
            type_counter[new_type] += 1

            if new_type == "circulation":
                new_series = index.lookup(coin["country"], coin["year"])
                if new_series is None:
                    unmatched_circulation.append(
                        f"{coin['eurio_id']} ({coin['country']}/{coin['year']})"
                    )
            else:
                new_series = None

            series_counter[new_series] += 1

            # Only emit update if something changed
            if coin.get("issue_type") != new_type or coin.get("series_id") != new_series:
                updates.append(
                    {
                        "eurio_id": coin["eurio_id"],
                        "country": coin["country"],
                        "year": coin["year"],
                        "face_value": 0,  # placeholder required by NOT NULL; overwritten by merge
                        "issue_type": new_type,
                        "series_id": new_series,
                    }
                )

        # Report
        print(f"\n  issue_type distribution:")
        for k, v in sorted(type_counter.items()):
            print(f"    {k:20} {v:5}")
        print(f"\n  series_id distribution (top 10):")
        top = series_counter.most_common(10)
        for k, v in top:
            print(f"    {str(k):30} {v:5}")
        print(f"\n  Updates to write: {len(updates)}")
        print(f"  Unmatched circulation coins: {len(unmatched_circulation)}")

        # Assertions
        circulation_total = type_counter.get("circulation", 0)
        matched_circulation = circulation_total - len(unmatched_circulation)
        if unmatched_circulation:
            print(f"\nWARNING: {len(unmatched_circulation)} circulation coins did not match any series:")
            for line in unmatched_circulation[:20]:
                print(f"    {line}")
            if len(unmatched_circulation) > 20:
                print(f"    ... and {len(unmatched_circulation) - 20} more")
            print(
                "  These likely indicate a gap in coin_series_seed.json "
                "(missing country or date range issue). Fix the seed, not this script."
            )
        else:
            print(f"  ✓ All {circulation_total} circulation coins matched a series")

        # Pass 3: apply updates — BUT we can't use the upsert pattern with face_value
        # placeholder safely. Switch to PATCH per-coin for correctness.
        print(f"\n[3/3] Writing updates...")
        if args.apply:
            if updates:
                patch_count = 0
                for u in updates:
                    resp = client._client.patch(
                        f"{client.base}/coins",
                        params={"eurio_id": f"eq.{u['eurio_id']}"},
                        json={"issue_type": u["issue_type"], "series_id": u["series_id"]},
                    )
                    if resp.status_code >= 400:
                        print(f"  FAIL {u['eurio_id']}: HTTP {resp.status_code} {resp.text[:200]}")
                        resp.raise_for_status()
                    patch_count += 1
                    if patch_count % 500 == 0:
                        print(f"    patched {patch_count}/{len(updates)}")
                print(f"  ✓ patched {patch_count} coins")
            else:
                print("  No updates to write — schema already enriched.")
        else:
            print(f"  [dry-run] would patch {len(updates)} coins")

    print("\n=== done ===")


def main() -> None:
    args = parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== enrich_coins_metadata.py [{mode}] [target={args.target}] ===\n")

    # Load the seed once (shared by both targets)
    seed = json.loads(SEED_PATH.read_text())
    series_seed = seed["series"]
    print(f"Loaded {len(series_seed)} series from {SEED_PATH.name}")
    index = SeriesIndex(series_seed)
    print(f"  Countries covered: {sorted(index.countries())}")

    if args.target == "sqlite":
        main_sqlite(args, series_seed, index)
    else:
        main_supabase(args, series_seed, index)


if __name__ == "__main__":
    main()
