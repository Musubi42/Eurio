"""Backfill `source_images.detections_json` en relançant `detect_circles_multi`
une fois par raw de listing.

Why: la review lot (Examination plate) lisait jusqu'ici les détections en
recomputant la pipeline complète (YOLO + Hough + polish) à CHAQUE chargement
— ~67s pour un lot de 4 images. Le producer (`detect_crop.py`) persiste
désormais le constat de détection au scrape ; ce script backfille les
listings déjà scrapés pour que leur plate s'affiche sans recompute.

Non-destructif : `UPDATE source_images.detections_json` uniquement. Aucun
crop, asset, phash, ni statut touché. Idempotent — saute les images qui ont
déjà un `detections_json` (sauf `--force`).

Scope : sources `listing` (eBay & co), pas `studio` (1 coin, BG uniforme —
la plate lot ne les concerne pas). Filtrable par `--run-id`.

Usage::

    cd ml
    python -m scripts.backfill_detections_json
    python -m scripts.backfill_detections_json --run-id <run_id>
    python -m scripts.backfill_detections_json --dry --limit 5
    python -m scripts.backfill_detections_json --force   # recompute tout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Path setup (lance via `python -m scripts.backfill_detections_json`).
_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

import cv2  # noqa: E402

from vision.normalize_snap import normalize_listing_with_detections  # noqa: E402
from sources._base.steps.detect_crop import _crop_strategy, _detection_to_dict  # noqa: E402
from store import Store  # noqa: E402
from shared.storage.local_cache import local_path  # noqa: E402


def _process_one(sid: str, source_id: str, raw_storage_path: str
                 ) -> tuple[list[dict] | None, str]:
    """Renvoie (detections_dicts, note). detections=None si erreur (skip write)."""
    try:
        p = local_path("enrichment-raws", raw_storage_path)
    except FileNotFoundError as exc:
        return None, f"raw missing: {exc}"
    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None, "imread failed"
    # Pipeline complet (crop + gate anti-fragment) pour écrire le MÊME constat
    # que le scrape : les capsules/fragments gatés sont marqués accepted=False.
    _, dets = normalize_listing_with_detections(bgr, census=(source_id == "ebay"))
    return [_detection_to_dict(d) for d in dets], ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None, help="restreindre à un source_runs.id")
    ap.add_argument("--force", action="store_true",
                    help="recompute même si detections_json déjà présent")
    ap.add_argument("--dry", action="store_true",
                    help="liste sans écrire")
    ap.add_argument("--limit", type=int, default=None,
                    help="traiter au plus N source_images (debug)")
    args = ap.parse_args()

    store = Store(_ML_DIR / "state" / "eurio.db")
    conn = store._connection()  # noqa: SLF001

    where = ["s.storage_path IS NOT NULL"]
    params: list = []
    if not args.force:
        where.append("s.detections_json IS NULL")
    if args.run_id:
        where.append("s.run_id = ?")
        params.append(args.run_id)
    rows = conn.execute(
        f"""
        SELECT s.id AS sid, s.source AS source, s.storage_path AS path
          FROM source_images s
         WHERE {' AND '.join(where)}
         ORDER BY s.id
        """,
        params,
    ).fetchall()
    # Listing-only (la plate lot ne concerne pas les sources studio).
    rows = [r for r in rows if _crop_strategy(r["source"]) == "listing"]
    if args.limit is not None:
        rows = rows[: args.limit]

    print(f"[backfill-detections] candidates={len(rows)} "
          f"force={args.force} run={args.run_id or 'ALL'}")
    if args.dry:
        for r in rows[:5]:
            print(f"  would process sid={r['sid'][:8]} source={r['source']}")
        if len(rows) > 5:
            print(f"  … and {len(rows) - 5} more")
        return 0

    n_written = 0
    skip_notes: list[str] = []
    for i, r in enumerate(rows, 1):
        dets, note = _process_one(r["sid"], r["source"], r["path"])
        if dets is None:
            skip_notes.append(f"sid={r['sid'][:8]} → {note}")
        else:
            conn.execute(
                "UPDATE source_images SET detections_json = ? WHERE id = ?",
                (json.dumps(dets), r["sid"]),
            )
            n_written += 1
        if i % 25 == 0 or i == len(rows):
            conn.commit()
            print(f"  [{i}/{len(rows)}] written={n_written} skipped={len(skip_notes)}")

    conn.commit()
    print(f"[backfill-detections] done · written={n_written} / {len(rows)} "
          f"source_images · skipped={len(skip_notes)}")
    if skip_notes:
        print(f"[backfill-detections] skips (showing 10):")
        for n in skip_notes[:10]:
            print(f"  {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
