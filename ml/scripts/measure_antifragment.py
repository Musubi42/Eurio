"""measure_antifragment.py — signal géométrique « pièce entière vs fragment ».

Bench-first (R0) : ne mute PAS la base. Pour chaque raw d'une classe, lance le
crop en mode census (`EURIO_CENSUS_DETECT=1`) et, pour CHAQUE crop produit
(correspondance 1:1 avec une `CircleDetection` acceptée → cx,cy,r natifs),
calcule un signal de **complétude du rim** : un fragment (bout de lettre, anneau
interne, bord partiel) n'a pas d'anneau circulaire complet autour de (cx,cy,r),
donc une couverture angulaire `arc_coverage` faible.

Logique reprise de `scan.crop_detectors.measure_tilt` (Canny sur l'anneau
[0.70·r, 1.15·r] + secteurs de 30°) mais on renvoie TOUJOURS `arc_coverage`
(measure_tilt court-circuite sous 0.60) pour pouvoir calibrer un seuil.

Sorties :
  - contact sheet (chaque tuile annotée arc_cov + axis_ratio), pour labelliser
  - JSONL des signaux par crop (raw_id, idx, cx, cy, r, arc_coverage, …)
  - histogramme arc_coverage en stdout

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/measure_antifragment.py --target at-2002-2eur-standard-1st-map \
      --contact-sheet /tmp/af.jpg --jsonl /tmp/af.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import cv2
import numpy as np

cv2.setNumThreads(1)
ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"

# Constantes alignées sur measure_tilt (crop_detectors.py).
_RING_LO = 0.70
_RING_HI = 1.15
_MIN_RING_PTS = 50
_N_SECTORS = 12


def rim_signals(bgr: np.ndarray, cx: float, cy: float, r: float) -> dict:
    """Complétude du rim autour de (cx,cy,r). Renvoie TOUJOURS arc_coverage.

    arc_coverage : fraction des 12 secteurs de 30° contenant ≥1 point Canny dans
                   l'anneau [0.70·r, 1.15·r]. 1.0 = anneau complet (pièce entière).
    axis_ratio   : minor/major de l'ellipse ajustée (1.0 = cercle), ou None.
    n_ring       : nb de points Canny dans l'anneau.
    """
    from vision.normalize_snap import _downscale_to_working_res

    if bgr is None or bgr.size == 0 or r <= 0:
        return {"arc_coverage": 0.0, "axis_ratio": None, "n_ring": 0}

    H, W = bgr.shape[:2]
    half = 2.6 * r
    x0 = max(0, int(cx - half)); y0 = max(0, int(cy - half))
    x1 = min(W, int(cx + half)); y1 = min(H, int(cy + half))
    sub = bgr[y0:y1, x0:x1]
    if sub.size == 0:
        return {"arc_coverage": 0.0, "axis_ratio": None, "n_ring": 0}

    work, scale = _downscale_to_working_res(sub)
    cx_w = (cx - x0) / scale
    cy_w = (cy - y0) / scale
    r_w = r / scale

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    median = float(np.median(gray))
    edges = cv2.Canny(gray, max(0.0, median * 0.5), min(255.0, median * 1.5))
    ys, xs = np.nonzero(edges)
    if len(xs) == 0:
        return {"arc_coverage": 0.0, "axis_ratio": None, "n_ring": 0}

    dists = np.hypot(xs.astype(float) - cx_w, ys.astype(float) - cy_w)
    ring = (dists >= _RING_LO * r_w) & (dists <= _RING_HI * r_w)
    rxs = xs[ring].astype(np.float32); rys = ys[ring].astype(np.float32)
    n_ring = int(ring.sum())
    if n_ring < _MIN_RING_PTS:
        return {"arc_coverage": 0.0, "axis_ratio": None, "n_ring": n_ring}

    angles = np.degrees(np.arctan2(rys - cy_w, rxs - cx_w)) % 360.0
    occupied = len(set(int(a / (360.0 / _N_SECTORS)) for a in angles))
    arc_cov = occupied / _N_SECTORS

    axis_ratio = None
    if n_ring >= 5:
        pts = np.column_stack([rxs, rys]).reshape(-1, 1, 2)
        try:
            (_, _), (d1, d2), _ = cv2.fitEllipseAMS(pts)
            mj, mn = max(d1, d2), min(d1, d2)
            if mj > 0:
                axis_ratio = round(mn / mj, 3)
        except cv2.error:
            pass

    return {"arc_coverage": round(arc_cov, 3), "axis_ratio": axis_ratio, "n_ring": n_ring}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="at-2002-2eur-standard-1st-map")
    ap.add_argument("--contact-sheet", default="")
    ap.add_argument("--jsonl", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    os.environ["EURIO_CENSUS_DETECT"] = "1"
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
    print(f"Classe {args.target} : {len(rows)} raws\n")

    records = []   # (raw_id, idx, crop_img, signals)
    for r in rows:
        try:
            p = local_path("enrichment-raws", r["storage_path"])
        except FileNotFoundError:
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        results = normalize_listing(bgr)
        for idx, res in enumerate(results):
            if res.image is None:
                continue
            sig = rim_signals(bgr, res.cx, res.cy, res.r)
            records.append((r["id"][:8], idx, res.image, sig))

    print(f"Crops census produits : {len(records)}\n")

    covs = [rec[3]["arc_coverage"] for rec in records]
    print("Histogramme arc_coverage :")
    bins = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    for lo, hi in zip(bins, bins[1:]):
        n = sum(1 for c in covs if lo <= c < hi)
        bar = "#" * n
        print(f"  [{lo:.2f},{hi:.2f}) {n:3d} {bar}")

    if args.jsonl:
        with open(args.jsonl, "w") as f:
            for raw_id, idx, _, sig in records:
                f.write(json.dumps({"raw_id": raw_id, "idx": idx, **sig}) + "\n")
        print(f"\n→ JSONL : {args.jsonl}")

    if args.contact_sheet and records:
        cols = 8
        rows_n = (len(records) + cols - 1) // cols
        sheet = np.zeros((rows_n * 160, cols * 160, 3), np.uint8)
        for i, (raw_id, idx, img, sig) in enumerate(records):
            t = cv2.resize(img, (160, 160))
            ac = sig["arc_coverage"]
            col = (0, 255, 0) if ac >= 0.8 else ((0, 200, 255) if ac >= 0.6 else (0, 0, 255))
            cv2.putText(t, f"{ac:.2f}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
            cv2.putText(t, f"#{i}", (4, 154), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
            rr, cc = divmod(i, cols)
            sheet[rr * 160:(rr + 1) * 160, cc * 160:(cc + 1) * 160] = t
        cv2.imwrite(args.contact_sheet, sheet)
        print(f"→ contact sheet : {args.contact_sheet} ({len(records)} tuiles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
