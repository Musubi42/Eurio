"""Backfill DINOv2 predictions for crops that already exist in DB.

Walks `image_assets` (filtered to the V1 scope: parent source_image's
target_eurio_id is a 2€ commemorative coin, crop file present on disk)
and writes one row per crop into `image_asset_dino_predictions` for
the requested ``--kind`` (default ``2eur_commemo``).

Idempotent: skips assets that already have a prediction for the same
``(encoder_version, anchors_kind)``. Pass ``--force`` to recompute
in place.

Usage:
    .venv/bin/python -m scripts.backfill_dino_predictions
    .venv/bin/python -m scripts.backfill_dino_predictions --limit 50
    .venv/bin/python -m scripts.backfill_dino_predictions --force
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sources._base.steps.auto_validate import run_auto_validate_dino_backfill  # noqa: E402
from state import Store  # noqa: E402

DB_PATH = ML_DIR / "state" / "training.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        default="2eur_commemo",
        choices=["2eur_commemo"],
        help="Anchor scope (default: 2eur_commemo).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if a prediction row already exists.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N assets (for smoke / dry runs).",
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help="Path to the training SQLite DB (default: ml/state/training.db).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    for name in ("foundation", "sources._base.steps.auto_validate"):
        logging.getLogger(name).setLevel(logging.INFO)

    store = Store(Path(args.db))
    t0 = time.perf_counter()
    result = run_auto_validate_dino_backfill(
        store=store,
        anchors_kind=args.kind,
        force=args.force,
        limit=args.limit,
    )
    dt = time.perf_counter() - t0

    print()
    print(f"Kind:               {args.kind}")
    print(f"Predicted:          {result.n_predicted}")
    print(f"Skipped (existing): {result.n_skipped_existing}")
    print(f"Skipped (oos):      {result.n_skipped_out_of_scope}")
    print(f"Errors:             {result.n_errors}")
    print(f"Total time:         {dt:.1f}s")
    if result.n_predicted:
        print(f"Per-asset average:  {dt / result.n_predicted * 1000:.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
