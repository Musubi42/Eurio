"""Remove 2€ entries without a Numista ID from the referential and Supabase.

Entries with no numista_id have no image source and can't be trained —
they're dead weight. 1c–1€ entries are left untouched (out of scope, not deleted).

Dry-run by default. Pass --execute to actually delete.

Usage:
    python ml/clean_referential.py             # preview only
    python ml/clean_referential.py --execute   # delete for real
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import httpx

from eurio_referential import load_referential, save_referential

DELETE_BATCH = 80  # PostgREST IN() URL-length safety margin


# ── Supabase client (minimal) ─────────────────────────────────────────────────

class _SupabaseClient:
    def __init__(self, url: str, service_key: str) -> None:
        self._base = url.rstrip("/") + "/rest/v1"
        self._client = httpx.Client(
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )

    def __enter__(self) -> "_SupabaseClient":
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def delete_where_in(self, table: str, column: str, values: list[str]) -> int:
        """DELETE rows where column IN values. Returns rows deleted."""
        deleted = 0
        for i in range(0, len(values), DELETE_BATCH):
            batch = values[i : i + DELETE_BATCH]
            in_clause = "(" + ",".join(batch) + ")"
            resp = self._client.delete(
                f"{self._base}/{table}",
                params={column: f"in.{in_clause}"},
                headers={"Prefer": "return=minimal,count=exact"},
            )
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"DELETE {table} failed: {resp.text}",
                    request=resp.request,
                    response=resp,
                )
            cr = resp.headers.get("content-range", "")
            if "/" in cr:
                try:
                    deleted += int(cr.split("/")[-1])
                except ValueError:
                    pass
        return deleted


def _load_env() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL", "")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("VITE_SUPABASE_SERVICE_KEY", "")
    )
    if not url or not key:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k in ("SUPABASE_URL", "VITE_SUPABASE_URL") and not url:
                    url = v
                if k in ("SUPABASE_SERVICE_ROLE_KEY", "VITE_SUPABASE_SERVICE_KEY") and not key:
                    key = v
    return url, key


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean 2€ orphans (no numista_id) from referential + Supabase"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete (default is dry-run)",
    )
    args = parser.parse_args()

    # load_referential returns dict[eurio_id → entry]
    referential = load_referential()

    orphan_ids = [
        eurio_id
        for eurio_id, entry in referential.items()
        if entry["identity"]["face_value"] == 2.0
        and not entry.get("cross_refs", {}).get("numista_id")
    ]
    kept = {k: v for k, v in referential.items() if k not in set(orphan_ids)}

    print(f"{'='*60}")
    print(f"  CLEAN REFERENTIAL — 2€ ORPHANS WITHOUT NUMISTA ID")
    print(f"{'='*60}")
    print(f"  Total entries before : {len(referential)}")
    print(f"  2€ orphans to delete : {len(orphan_ids)}")
    print(f"  Entries after        : {len(kept)}")
    print()

    by_country: Counter[str] = Counter(
        referential[eid]["identity"]["country"] for eid in orphan_ids
    )
    print("  Breakdown by country:")
    for country, count in sorted(by_country.items(), key=lambda x: -x[1]):
        print(f"    {country:4s} : {count}")
    print()

    if not args.execute:
        print("  DRY-RUN — nothing deleted. Pass --execute to apply.")
        return

    print("  Deleting from Supabase...")
    url, key = _load_env()
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found in env or .env")
        sys.exit(1)

    with _SupabaseClient(url, key) as db:
        obs_deleted = db.delete_where_in("source_observations", "eurio_id", orphan_ids)
        print(f"  source_observations deleted : {obs_deleted}")

        coins_deleted = db.delete_where_in("coins", "eurio_id", orphan_ids)
        print(f"  coins deleted               : {coins_deleted}")

    print()
    print("  Updating eurio_referential.json...")
    save_referential(kept)

    print(f"\n{'='*60}")
    print(f"  Done. {len(orphan_ids)} entries removed.")
    print(f"  Referential now has {len(kept)} entries.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
