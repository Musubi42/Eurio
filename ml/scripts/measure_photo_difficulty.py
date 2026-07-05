"""Teste l'hypothèse « les zero_crops échouent parce que ce sont des PHOTOS plus
dures (flou/glare), pas à cause du crop » — issue de measure_crop_undercrop.

Pour un run eBay, compare la difficulté d'image entre `zero_crops` (rejetés par le
gate) et `success` (passés). Cheap : pas de YOLO ni DINO. Par image (long-side
réduit à 768, centre 70 %) :
  - netteté   = variance du Laplacien (haut = net) ;
  - glare     = fraction de pixels quasi-saturés (>=245) ;
  - contraste = écart-type des niveaux de gris.

Si zero_crops sont nettement plus flous / plus glare → confirme que la cause des
faux négatifs est la qualité photo (→ probe à durcir/retrain), pas la géométrie du crop.

Usage : .venv/bin/python -m scripts.measure_photo_difficulty --run <run_id>
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent

from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")


def _metrics(bgr) -> tuple[float, float, float]:
    import cv2
    h, w = bgr.shape[:2]
    s = 768.0 / max(h, w)
    if s < 1.0:
        bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    h, w = bgr.shape[:2]
    y0, y1 = int(0.15 * h), int(0.85 * h)
    x0, x1 = int(0.15 * w), int(0.85 * w)
    gray = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    glare = float((gray >= 245).mean())
    contrast = float(gray.std())
    return sharp, glare, contrast


def _summary(name, arr):
    a = np.array(arr)
    return (f"{name:<11} n={len(a):<4} "
            f"net p25={np.percentile(a[:,0],25):7.0f} p50={np.percentile(a[:,0],50):7.0f} | "
            f"glare p50={np.percentile(a[:,1],50)*100:4.1f}% p90={np.percentile(a[:,1],90)*100:4.1f}% | "
            f"contraste p50={np.percentile(a[:,2],50):4.0f}")


def main() -> int:
    import cv2
    from shared.storage.local_cache import local_path

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--max-per-status", type=int, default=250)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    out: dict[str, list] = {}
    for status in ("zero_crops", "success"):
        rows = conn.execute(
            "SELECT storage_path FROM source_images WHERE source='ebay' AND run_id=? "
            "AND crop_status=? AND storage_path IS NOT NULL",
            (args.run, status),
        ).fetchall()[: args.max_per_status]
        vals = []
        for (sp,) in rows:
            try:
                bgr = cv2.imread(str(local_path("enrichment-raws", sp)), cv2.IMREAD_COLOR)
            except Exception:
                continue
            if bgr is None:
                continue
            vals.append(_metrics(bgr))
        out[status] = vals
        print(_summary(status, vals))

    z = np.array(out["zero_crops"]); s = np.array(out["success"])
    if len(z) and len(s):
        print(f"\nMédiane netteté : zero={np.median(z[:,0]):.0f}  success={np.median(s[:,0]):.0f}  "
              f"→ success {np.median(s[:,0])/max(1,np.median(z[:,0])):.2f}× plus net")
        print(f"Flou sévère (netteté<100) : zero {100*(z[:,0]<100).mean():.0f}%  success {100*(s[:,0]<100).mean():.0f}%")
        print(f"Glare fort (>2% sat) : zero {100*(z[:,1]>0.02).mean():.0f}%  success {100*(s[:,1]>0.02).mean():.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
