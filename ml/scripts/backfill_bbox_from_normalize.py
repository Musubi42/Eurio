"""Backfill `image_assets.bbox_json` by re-running the deterministic
normalizer over each source_image of a given run.

Why: bbox was never persisted by the producer (`detect_crop.py` omitted
the `bbox=` argument when building `ImageAssetRow`). The fix in the
producer covers FUTURE runs; this script backfills PAST runs so the
crop-forensics admin view (`/bench/runs/{run_id}/crops`) has overlay data
for already-cropped raws.

Non-destructive : on ne touche ni au fichier crop, ni au storage_path,
ni au phash, ni au resolution_status. On `UPDATE` uniquement
`bbox_json` (et `detection_method` au passage, pour aligner sur la
nouvelle valeur composée du pipeline).

Match strategy : on ré-exécute `normalize_listing_path` (qui est
déterministe : mêmes circles dans le même ordre) et on aligne par
`crop_index`. Si le nombre de results diffère du nombre d'image_assets
existants pour ce source_image, on warne et on backfille au prorata
(min(len)).

Usage::

    cd ml
    python -m scripts.backfill_bbox_from_normalize --run-id <run_id>
    python -m scripts.backfill_bbox_from_normalize --run-id <run_id> --dry
    python -m scripts.backfill_bbox_from_normalize --run-id <run_id> --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Path setup (lance via `python -m scripts.backfill_bbox_from_normalize`).
_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from vision.normalize_snap import normalize_listing_path, normalize_studio_path  # noqa: E402
from sources._base.steps.detect_crop import _crop_strategy  # noqa: E402
from store import Store  # noqa: E402
from shared.storage.local_cache import local_path  # noqa: E402


def _bbox_from_result(result) -> dict[str, float] | None:
    if result is None or not result.r or result.r <= 0:
        return None
    return {
        "x": float(result.cx - result.r),
        "y": float(result.cy - result.r),
        "w": float(2 * result.r),
        "h": float(2 * result.r),
    }


def _process_one(conn, sid: str, source_id: str, raw_storage_path: str
                  ) -> tuple[int, int, str]:
    """Backfill un source_image. Renvoie (n_updated, n_assets_existing, note)."""
    try:
        raw = local_path("enrichment-raws", raw_storage_path)
    except FileNotFoundError as exc:
        return 0, 0, f"raw missing: {exc}"

    if _crop_strategy(source_id) == "studio":
        single = normalize_studio_path(raw)
        results = [single] if single.image is not None else []
    else:
        results = normalize_listing_path(raw)

    asset_rows = conn.execute(
        """
        SELECT id, crop_index, detection_method, bbox_json
          FROM image_assets
         WHERE source_image_id = ?
         ORDER BY crop_index ASC
        """,
        (sid,),
    ).fetchall()
    n_existing = len(asset_rows)
    if n_existing == 0:
        return 0, 0, "no existing image_assets"

    if not results:
        return 0, n_existing, "normalize returned 0 circles"

    n_updated = 0
    n_match = min(len(results), n_existing)
    for i in range(n_match):
        bbox = _bbox_from_result(results[i])
        if bbox is None:
            continue
        bbox_json = json.dumps(bbox, ensure_ascii=False)
        # Aligne aussi detection_method (au cas où il aurait dérivé).
        new_method = results[i].method or asset_rows[i]["detection_method"]
        conn.execute(
            """
            UPDATE image_assets
               SET bbox_json = ?,
                   detection_method = ?
             WHERE id = ?
            """,
            (bbox_json, new_method, asset_rows[i]["id"]),
        )
        n_updated += 1

    note = ""
    if len(results) != n_existing:
        note = (
            f"crop count drift: normalize={len(results)} db={n_existing} "
            f"backfilled {n_match}"
        )
    return n_updated, n_existing, note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True, help="source_runs.id")
    ap.add_argument("--dry", action="store_true",
                    help="show what would be backfilled, no DB writes")
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N source_images (debug)")
    args = ap.parse_args()

    db_path = _ML_DIR / "state" / "eurio.db"
    store = Store(db_path)
    conn = store._connection()

    run_row = conn.execute(
        "SELECT id, source FROM source_runs WHERE id = ?", (args.run_id,),
    ).fetchone()
    if run_row is None:
        print(f"[backfill-bbox] run {args.run_id} not found.", file=sys.stderr)
        return 1
    source_id = run_row["source"]

    raws = conn.execute(
        """
        SELECT DISTINCT s.id AS sid, s.storage_path AS path
          FROM source_images s
          JOIN image_assets a ON a.source_image_id = s.id
         WHERE a.run_id = ?
           AND s.storage_path IS NOT NULL
        """,
        (args.run_id,),
    ).fetchall()
    if args.limit is not None:
        raws = raws[: args.limit]

    print(f"[backfill-bbox] run={args.run_id} source={source_id} "
          f"raws_to_process={len(raws)}")

    if args.dry:
        for r in raws[:5]:
            print(f"  would process sid={r['sid']}")
        if len(raws) > 5:
            print(f"  … and {len(raws) - 5} more")
        return 0

    total_assets = 0
    total_updated = 0
    drift_notes: list[str] = []
    for i, r in enumerate(raws, 1):
        n_up, n_ex, note = _process_one(conn, r["sid"], source_id, r["path"])
        total_assets += n_ex
        total_updated += n_up
        if note:
            drift_notes.append(f"sid={r['sid'][:8]} → {note}")
        if i % 50 == 0 or i == len(raws):
            conn.commit()
            print(f"  [{i}/{len(raws)}] cumulative updated={total_updated} "
                  f"assets={total_assets}")

    conn.commit()
    print(
        f"[backfill-bbox] done · updated_bbox={total_updated} / {total_assets} "
        f"image_assets across {len(raws)} source_images"
    )
    if drift_notes:
        print(f"[backfill-bbox] {len(drift_notes)} drift notes (showing 10):")
        for n in drift_notes[:10]:
            print(f"  {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
