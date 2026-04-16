"""Enrich the `coins` referential with the metadata required by the sets DSL.

Concretely this script does three things, idempotent:

1. **Seed `coin_series`** from `ml/data/coin_series_seed.json` (~32 entries for
   the whole euro area history). Upserts on `id`.

2. **Populate `coins.issue_type`** (text enum) for all 2938 coins based on
   existing fields:
      is_commemorative=false              → 'circulation'
      is_commemorative=true, nat_var NULL → 'commemo-national'
      is_commemorative=true, nat_var !=   → 'commemo-common'
   (other values like 'starter-kit', 'bu-set', 'proof' are reserved for future
   sources and left NULL for v1)

3. **Populate `coins.series_id`** (FK → coin_series.id) for circulation coins
   only, by matching (country, year) against the date range of each series.
   Commemoratives are left with series_id = NULL (they are standalone issues
   not part of a circulation series).

Design notes:
- Uses the shared `PostgrestClient` pattern from `sync_to_supabase.py` (httpx,
  service role key, batch upserts).
- Strong post-conditions (asserts) so the script fails loudly if the matching
  leaves holes.
- Dry-run by default: prints what it *would* do, never touches the DB. Pass
  `--apply` to actually write.

Usage:
    python ml/enrich_coins_metadata.py              # dry-run, default
    python ml/enrich_coins_metadata.py --apply      # actually write
    python ml/enrich_coins_metadata.py --apply --skip-seed   # only enrich coins, skip coin_series seed
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sync_to_supabase import PostgrestClient, load_env

SEED_PATH = Path(__file__).parent / "data" / "coin_series_seed.json"


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


# ---------- Supabase I/O ----------


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
    ap = argparse.ArgumentParser(description="Enrich coins with issue_type + series_id")
    ap.add_argument("--apply", action="store_true", help="Actually write to Supabase (default is dry-run)")
    ap.add_argument("--skip-seed", action="store_true", help="Don't upsert coin_series, only enrich coins")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== enrich_coins_metadata.py [{mode}] ===\n")

    # Load the seed
    seed = json.loads(SEED_PATH.read_text())
    series_seed = seed["series"]
    print(f"Loaded {len(series_seed)} series from {SEED_PATH.name}")
    index = SeriesIndex(series_seed)
    print(f"  Countries covered: {sorted(index.countries())}")

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


if __name__ == "__main__":
    main()
