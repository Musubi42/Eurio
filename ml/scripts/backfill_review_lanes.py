"""backfill_review_lanes.py — assigne la lane persistée aux review_queue existants.

Calcule le verdict Dino de chaque item sans lane et le mappe vers sa lane via la
règle centralisée (foundation/review_lanes.py). ADDITIF & SÛR (R0) :
- ne touche JAMAIS ``lane_source='human'`` (déplacements manuels stickys) ;
- idempotent : par défaut ne traite que ``lane IS NULL`` ;
- ``--force`` re-route aussi les items déjà assignés par 'auto' (utile après un
  nouveau run Dino) — toujours en épargnant les 'human'.

Dry-run par défaut (montre la répartition). ``--commit`` pour écrire.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/backfill_review_lanes.py            # dry-run
  .venv/bin/python scripts/backfill_review_lanes.py --commit   # écrit
  .venv/bin/python scripts/backfill_review_lanes.py --force --commit
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="écrit (défaut = dry-run)")
    ap.add_argument(
        "--force", action="store_true",
        help="re-route aussi les lanes déjà posées par 'auto' (jamais les 'human')",
    )
    ap.add_argument("--limit", type=int, default=0, help="cap items (0=tous)")
    args = ap.parse_args()

    from foundation.review_lanes import compute_lane

    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row

    where = "lane IS NULL" if not args.force else "lane_source != 'human'"
    rows = conn.execute(
        f"SELECT id, image_asset_id, status, lane FROM review_queue WHERE {where} "
        "ORDER BY enqueued_at"
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[{mode}] backfill lanes : {len(rows)} items à router "
          f"({'force' if args.force else 'lane NULL seulement'})\n")

    # Répartition par (lane, status) pour validation humaine.
    by_lane: Counter[str] = Counter()
    by_lane_status: Counter[tuple[str, str]] = Counter()
    changed = 0
    for r in rows:
        _verdict, lane = compute_lane(conn, r["image_asset_id"])
        by_lane[lane] += 1
        by_lane_status[(lane, r["status"])] += 1
        if args.commit and lane != r["lane"]:
            conn.execute(
                "UPDATE review_queue SET lane=?, lane_source='auto' "
                "WHERE id=? AND lane_source!='human'",
                (lane, r["id"]),
            )
            changed += 1
    if args.commit:
        conn.commit()

    print(f"{'lane':14}{'total':>8}   par status")
    print("-" * 56)
    for lane in ("manual", "auto_accept", "ccproxy"):
        statuses = {s: n for (la, s), n in by_lane_status.items() if la == lane}
        detail = ", ".join(f"{s}={n}" for s, n in sorted(statuses.items()))
        print(f"{lane:14}{by_lane[lane]:>8}   {detail}")
    print("-" * 56)
    print(f"{'TOTAL':14}{sum(by_lane.values()):>8}")
    print(f"\n{'[COMMITTÉ] ' + str(changed) + ' lanes écrites' if args.commit else '[DRY-RUN — rien écrit]'}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
