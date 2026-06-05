"""review_sheets_census.py — planches de review des crops récupérés par un run census.

Génère des contact sheets LISIBLES (par classe, paginées) pour les `image_assets`
d'un `run_id` donné (ex: census-recover-<cohort>). Une planche = N tuiles d'une
seule classe. Annotations : index intra-classe + statut (auto_phash = vert,
pending_match = blanc). Lecture seule — ne mute rien.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/review_sheets_census.py --run census-recover-b0299ca0252b
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="census-recover-b0299ca0252b")
    ap.add_argument("--out", default="/tmp/census_review")
    ap.add_argument("--per-sheet", type=int, default=30)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--tile", type=int, default=200)
    args = ap.parse_args()

    from storage.local_cache import local_path

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ia.storage_path, ia.resolution_status, ia.detection_method,
               si.target_eurio_id AS cls
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ?
         ORDER BY si.target_eurio_id, ia.source_image_id, ia.crop_index
        """,
        (args.run,),
    ).fetchall()
    print(f"Run {args.run} : {len(rows)} crops\n")

    by_cls: dict[str, list] = {}
    for r in rows:
        by_cls.setdefault(r["cls"], []).append(r)

    tile, cols, per = args.tile, args.cols, args.per_sheet
    total_sheets = 0
    index = []  # (sheet_file, class, n)
    for cls in sorted(by_cls):
        items = by_cls[cls]
        short = cls.replace("-2eur-", "-").replace("-anniversary", "")[:32]
        for s in range(0, len(items), per):
            chunk = items[s:s + per]
            rows_n = (len(chunk) + cols - 1) // cols
            sheet = np.zeros((rows_n * tile + 26, cols * tile, 3), np.uint8)
            cv2.putText(sheet, f"{cls}  [{s}-{s+len(chunk)-1}] / {len(items)}",
                        (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 220, 255), 1)
            for i, r in enumerate(chunk):
                try:
                    p = local_path("enrichment-crops", r["storage_path"])
                    im = cv2.imread(str(p))
                except FileNotFoundError:
                    im = None
                t = cv2.resize(im, (tile, tile)) if im is not None else np.full(
                    (tile, tile, 3), 40, np.uint8)
                auto = r["resolution_status"] == "auto_phash"
                col = (0, 255, 0) if auto else (255, 255, 255)
                cv2.putText(t, f"#{s+i}", (4, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
                if auto:
                    cv2.putText(t, "phash", (4, tile - 8), cv2.FONT_HERSHEY_SIMPLEX,
                                0.45, (0, 255, 0), 1)
                rr, cc = divmod(i, cols)
                y0 = 26 + rr * tile
                sheet[y0:y0 + tile, cc * tile:(cc + 1) * tile] = t
            fn = out / f"{short}_{s // per:02d}.jpg"
            cv2.imwrite(str(fn), sheet)
            total_sheets += 1
        index.append((short, len(items), (len(items) + per - 1) // per))

    print(f"{'classe':40s}{'crops':>7}{'planches':>10}")
    for short, n, ns in index:
        print(f"{short:40s}{n:>7}{ns:>10}")
    print(f"\n→ {total_sheets} planches dans {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
