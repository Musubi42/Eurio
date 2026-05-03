"""go-task ml:src:ebay:status — quick health snapshot for eBay.

Affiche : quota du jour, freshness buckets, derniers runs, lots en review queue.
Read-only, no API call. Utile pour reprendre un projet 3 mois plus tard.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[2]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.sources_routes import (
    EBAY_DAILY_QUOTA,
    ebay_calls_today,
    estimate_calls_per_eurio_id,
)
from state import Store


def main() -> int:
    db_path = ML_DIR / "state" / "training.db"
    store = Store(db_path)
    conn = store._connection()  # noqa: SLF001

    calls = ebay_calls_today(store)
    avg = estimate_calls_per_eurio_id(store)

    print("=" * 60)
    print(f"eBay quota — today")
    print(f"  calls_today    {calls} / {EBAY_DAILY_QUOTA}")
    print(f"  remaining      {max(EBAY_DAILY_QUOTA - calls, 0)}")
    print(f"  avg/eurio_id   {avg:.1f}")
    print()

    buckets = conn.execute(
        """
        SELECT
          SUM(CASE WHEN last_enriched_at IS NULL THEN 1 ELSE 0 END) AS never,
          SUM(CASE WHEN last_enriched_at IS NOT NULL
                    AND julianday('now') - julianday(last_enriched_at) > 90
                   THEN 1 ELSE 0 END) AS stale,
          SUM(CASE WHEN last_enriched_at IS NOT NULL
                    AND julianday('now') - julianday(last_enriched_at) <= 90
                   THEN 1 ELSE 0 END) AS fresh,
          COUNT(*) AS total
          FROM v_ebay_freshness
        """
    ).fetchone()

    print("Freshness queue (commémo 2€ non-EU)")
    print(f"  never enriched {buckets['never'] or 0}")
    print(f"  stale (>90j)   {buckets['stale'] or 0}")
    print(f"  fresh          {buckets['fresh'] or 0}")
    print(f"  total          {buckets['total'] or 0}")
    print()

    runs = conn.execute(
        """
        SELECT id, kind, status, current_step, n_calls, n_raws_added, n_crops_added,
               n_review_enqueued, n_errors, started_at, error_summary
          FROM source_runs
         WHERE source = 'ebay'
         ORDER BY started_at DESC LIMIT 3
        """
    ).fetchall()

    print("Last 3 runs")
    if not runs:
        print("  (none yet)")
    for r in runs:
        print(
            f"  {r['started_at']}  {r['status']:8s}  step={r['current_step']:9s}  "
            f"calls={r['n_calls']:4d}  raws={r['n_raws_added']:4d}  "
            f"crops={r['n_crops_added']:4d}  review={r['n_review_enqueued']:4d}  errs={r['n_errors']:3d}"
        )
        if r["error_summary"]:
            print(f"    └─ {r['error_summary']}")
    print()

    n_lots = conn.execute(
        """
        SELECT count(*) AS n FROM review_queue rq
        JOIN image_assets ia ON ia.id = rq.image_asset_id
        JOIN source_images si ON si.id = ia.source_image_id
        WHERE si.source = 'ebay' AND rq.kind = 'lot' AND rq.status = 'open'
        """
    ).fetchone()
    print(f"Open lot reviews (kind='lot'): {n_lots['n'] or 0}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
