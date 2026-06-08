"""Mesure la distribution du rayon détecté (en fraction du short side de
la raw) sur tous les raws eBay locaux, après YOLO+Hough refine.

But : choisir `_LISTING_RMIN_FRAC_STRICT` avec des vraies données plutôt
que par guess. Affiche la distrib des `r/short` pour les détections YOLO,
toutes confondues — pré-filtre `_YOLO_BBOX_MIN_RADIUS_FRAC` désactivé
pour voir aussi les "presque trop petites".

Usage::

    cd ml
    .venv/bin/python -m scripts.measure_listing_radius_distribution
    .venv/bin/python -m scripts.measure_listing_radius_distribution --limit 50
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

import cv2  # noqa: E402

from vision.normalize_snap import (  # noqa: E402
    _hough_refine_in_roi,
    _yolo_detect_bboxes,
    _YOLO_BBOX_MARGIN_FRAC,
)


_RAW_ROOT = _ML_DIR / "state" / "sources" / "ebay" / "raw"


def _iter_raws(limit: int | None) -> list[Path]:
    files = sorted(_RAW_ROOT.rglob("*.jpg"))
    if limit:
        files = files[:limit]
    return files


def _measure_one(raw: Path) -> list[tuple[float, float, str, float]]:
    """Returns rows of (r_frac, conf, method, bbox_min_side_frac) per YOLO bbox."""
    bgr = cv2.imread(str(raw), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return []
    h, w = bgr.shape[:2]
    short = float(min(h, w))
    bboxes = _yolo_detect_bboxes(bgr)
    rows: list[tuple[float, float, str, float]] = []
    for x1, y1, x2, y2, conf in bboxes:
        bw = x2 - x1
        bh = y2 - y1
        bbox_min_side = min(bw, bh) / short
        mx = bw * _YOLO_BBOX_MARGIN_FRAC
        my = bh * _YOLO_BBOX_MARGIN_FRAC
        refined = _hough_refine_in_roi(bgr, x1 - mx, y1 - my, x2 + mx, y2 + my,
                                        r_max_clamp=max(bw, bh) / 2.0)
        if refined is not None:
            _, _, r = refined
            method = "yolo+hough"
        else:
            r = min(bw, bh) / 2.0
            method = "yolo+bbox"
        rows.append((r / short, conf, method, bbox_min_side))
    return rows


def _bucket_label(frac: float) -> str:
    """Histogram bucket label for r/short."""
    edges = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.40, 0.55]
    for e in edges:
        if frac < e:
            return f"<{e:.2f}"
    return ">=0.55"


def _percentiles(values: list[float], pcts: list[int]) -> dict[int, float]:
    if not values:
        return {p: float("nan") for p in pcts}
    s = sorted(values)
    n = len(s)
    return {p: s[min(n - 1, int(round(p / 100 * n)))] for p in pcts}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    raws = _iter_raws(args.limit)
    print(f"scanning {len(raws)} raws under {_RAW_ROOT}\n")

    all_r_frac: list[float] = []
    method_counter: Counter[str] = Counter()
    hist: Counter[str] = Counter()
    n_zero_bbox = 0
    n_processed = 0

    for i, raw in enumerate(raws, 1):
        rows = _measure_one(raw)
        n_processed += 1
        if not rows:
            n_zero_bbox += 1
            continue
        for r_frac, _conf, method, _bb in rows:
            all_r_frac.append(r_frac)
            method_counter[method] += 1
            hist[_bucket_label(r_frac)] += 1
        if i % 20 == 0:
            print(f"  {i}/{len(raws)} raws…", flush=True)

    print(f"\n=== summary ===")
    print(f"raws processed       : {n_processed}")
    print(f"raws with 0 bbox     : {n_zero_bbox}")
    print(f"total YOLO bboxes    : {len(all_r_frac)}")
    print(f"methods              : {dict(method_counter)}")

    print(f"\n=== histogram of r/short_side ===")
    bucket_order = ["<0.04", "<0.06", "<0.08", "<0.10", "<0.12",
                    "<0.15", "<0.20", "<0.30", "<0.40", "<0.55", ">=0.55"]
    for k in bucket_order:
        n = hist.get(k, 0)
        bar = "#" * min(60, n)
        print(f"  {k:>7}  {n:5d}  {bar}")

    print(f"\n=== percentiles of r/short_side ===")
    pcts = _percentiles(all_r_frac, [5, 10, 25, 50, 75, 90, 95])
    for p, v in pcts.items():
        print(f"  p{p:02d} = {v:.4f}")


if __name__ == "__main__":
    main()
