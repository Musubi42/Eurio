"""Mesure le rappel du gate anti-fragment (census) sur un run eBay donné.

Diagnostic C7 : le gate `gated_fragment` (vision/normalize_snap.py) jette tout
crop dont `vision.census.face_scores` < τ (défaut 0.55). On a observé qu'il tue
des vrais 2€ uniques bien visibles. Ce script, EN LECTURE SEULE, reproduit
exactement le scoring du gate sur les images `zero_crops` d'un run, et montre :

  - la distribution des scores des crops qui PASSENT le filtre rayon ;
  - combien de « gros » cercles (r>=R_BIG, donc probables vrais coins) seraient
    récupérés à différents τ, vs combien de petits cercles seraient réadmis ;
  - un montage des gros cercles tués (à τ courant) pour vérif visuelle.

Usage : .venv/bin/python -m scripts.measure_fragment_gate --run <run_id> [--big 120]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ML_DIR = Path(__file__).resolve().parent.parent

from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")
TAUS = [0.55, 0.50, 0.45, 0.40, 0.35, 0.30]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run_id eBay")
    ap.add_argument("--big", type=int, default=120, help="rayon mini (px) d'un « vrai coin probable »")
    ap.add_argument("--max-imgs", type=int, default=None, help="limite (debug)")
    ap.add_argument("--montage", default=str(ML_DIR / "state" / "denom_bench" / "_fragment_gate_lost.png"))
    args = ap.parse_args()

    from shared.storage.local_cache import local_path
    from vision.census import face_scores
    from vision.normalize_snap import (
        CropConfig,
        _crop_mask_resize_int,
        detect_circles_multi,
    )
    import cv2

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT storage_path FROM source_images "
        "WHERE source='ebay' AND run_id=? AND crop_status='zero_crops' "
        "AND storage_path IS NOT NULL",
        (args.run,),
    ).fetchall()
    if args.max_imgs:
        rows = rows[: args.max_imgs]
    print(f"{len(rows)} images zero_crops à ré-analyser…")

    cfg = CropConfig()
    scores: list[float] = []
    radii: list[int] = []
    lost_big_imgs: list[np.ndarray] = []  # crops r>=big tués au τ courant (0.55)
    n_imgs_with_pass = 0

    for i, (sp,) in enumerate(rows):
        try:
            bgr = cv2.imread(str(local_path("enrichment-raws", sp)), cv2.IMREAD_COLOR)
        except Exception:
            continue
        if bgr is None:
            continue
        dets = detect_circles_multi(bgr, census=True)
        crops, drs = [], []
        for det in dets:
            if not det.accepted:  # déjà filtré par rayon/structure — pas par le gate fragment
                continue
            res = _crop_mask_resize_int(bgr, det.cx, det.cy, det.r, method=det.method, config=cfg)
            if res.image is not None:
                crops.append(res.image)
                drs.append(int(det.r))
        if not crops:
            continue
        n_imgs_with_pass += 1
        sc = face_scores(crops)
        for img, r, s in zip(crops, drs, sc):
            scores.append(float(s))
            radii.append(r)
            if r >= args.big and s < 0.55 and len(lost_big_imgs) < 48:
                lost_big_imgs.append(img)
        if (i + 1) % 50 == 0:
            print(f"  …{i + 1}/{len(rows)}")

    s = np.array(scores)
    r = np.array(radii)
    big = r >= args.big
    small = ~big
    print(f"\ncrops scorés (passés filtre rayon) : {len(s)}  "
          f"(gros r>={args.big}: {big.sum()} · petits: {small.sum()})")
    if len(s):
        def pct(a):
            return f"p10={np.percentile(a,10):.2f} p50={np.percentile(a,50):.2f} p90={np.percentile(a,90):.2f}"
        if big.sum():
            print(f"  scores GROS cercles  : {pct(s[big])}")
        if small.sum():
            print(f"  scores petits cercles: {pct(s[small])}")

    print(f"\n{'τ':>6} | gros récupérés | petits réadmis | (gros = vrais 2€ probables)")
    for t in TAUS:
        rec_big = int((big & (s >= t)).sum())
        rec_small = int((small & (s >= t)).sum())
        print(f"{t:>6.2f} | {rec_big:>13} | {rec_small:>13}")

    if lost_big_imgs:
        cols = 8
        rows_n = (len(lost_big_imgs) + cols - 1) // cols
        cell = 160
        canvas = Image.new("RGB", (cols * cell, rows_n * cell), (15, 15, 15))
        for k, img in enumerate(lost_big_imgs):
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pim = Image.fromarray(rgb).resize((cell, cell))
            canvas.paste(pim, ((k % cols) * cell, (k // cols) * cell))
        Path(args.montage).parent.mkdir(parents=True, exist_ok=True)
        canvas.save(args.montage)
        print(f"\nMontage des gros cercles tués (τ=0.55) : {args.montage}  ({len(lost_big_imgs)} crops)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
