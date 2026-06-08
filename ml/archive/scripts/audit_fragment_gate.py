"""audit_fragment_gate.py — audit visuel du gate anti-fragment sur une classe.

Mesure PURE. Pour une classe, génère TOUS les crops census (gate désactivé), les
note avec la probe face-vs-fragment, et produit deux contact sheets KEPT (≥τ) vs
CUT (<τ) + comptes. Sert à vérifier qualitativement que la probe garde les faces
et coupe les fragments — idéalement sur une classe HORS entraînement de la probe.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/audit_fragment_gate.py --target de-2007-2eur-50th-anniversary-of-the-treaty-of-rome --tau 0.45
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import cv2
import numpy as np

cv2.setNumThreads(1)
ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def _sheet(crops, path, tile=160, cols=8):
    if not crops:
        return
    rows_n = (len(crops) + cols - 1) // cols
    sheet = np.zeros((rows_n * tile, cols * tile, 3), np.uint8)
    for i, (im, sc) in enumerate(crops):
        t = cv2.resize(im, (tile, tile))
        cv2.putText(t, f"{sc:.2f}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        rr, cc = divmod(i, cols)
        sheet[rr * tile:(rr + 1) * tile, cc * tile:(cc + 1) * tile] = t
    cv2.imwrite(str(path), sheet)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--tau", type=float, default=0.45)
    ap.add_argument("--out", default="/tmp")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    os.environ["EURIO_CENSUS_DETECT"] = "1"
    os.environ["EURIO_CENSUS_FRAGMENT_TAU"] = "0"   # désactive le gate → tous les crops
    from vision.census import face_scores
    from vision.normalize_snap import normalize_listing
    from shared.storage.local_cache import local_path

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, storage_path FROM source_images "
        "WHERE target_eurio_id = ? AND storage_path IS NOT NULL",
        (args.target,),
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    imgs = []
    for r in rows:
        try:
            p = local_path("enrichment-raws", r["storage_path"])
        except FileNotFoundError:
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        for res in normalize_listing(bgr):
            if res.image is not None:
                imgs.append(res.image)

    scores = face_scores(imgs)
    kept = [(im, s) for im, s in zip(imgs, scores) if s >= args.tau]
    cut = [(im, s) for im, s in zip(imgs, scores) if s < args.tau]
    print(f"Classe {args.target}")
    print(f"Crops census (gate off) : {len(imgs)}")
    print(f"τ={args.tau} → GARDÉS {len(kept)} | COUPÉS {len(cut)}")

    out = Path(args.out)
    _sheet(sorted(kept, key=lambda x: -x[1]), out / "gate_kept.jpg")
    _sheet(sorted(cut, key=lambda x: -x[1]), out / "gate_cut.jpg")
    print(f"→ {out/'gate_kept.jpg'} ({len(kept)})  /  {out/'gate_cut.jpg'} ({len(cut)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
