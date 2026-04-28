"""
Snap normalization — raw camera frame → tight 224×224 coin crop on a fixed
black background. Used by Phase 1 (PC eval) and ported bit-for-bit to Android
in Phase 4 (`SnapNormalizer.kt`). The same algorithm runs over the studio
sources at training time so train and inference distributions align.

Pipeline:
  1. Hough circle detection (centered single coin assumption).
  2. Square crop tangent to the detected circle (+ small margin).
  3. Alpha mask: pixels outside the coin disk → black (BG_COLOR).
  4. Resize to 224×224 with INTER_AREA.

See docs/scan-normalization/README.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np


OUTPUT_SIZE = 224
COIN_MARGIN = 0.02          # margin around detected radius before crop
BG_COLOR = (0, 0, 0)        # alpha-mask fill outside coin disk


@dataclass
class NormalizationResult:
    image: np.ndarray | None    # 224×224 BGR, None on failure
    cx: int = 0
    cy: int = 0
    r: int = 0
    method: str = "failed"      # "hough" | "failed"
    debug: dict[str, Any] = field(default_factory=dict)


def _detect_coin_circle(bgr: np.ndarray) -> tuple[int, int, int, str] | None:
    """Find the dominant circle near the image center. Returns (cx, cy, r, method).

    Selection strategy: among Hough candidates, drop those whose center is far
    from the image center (>30% of the short side away), then pick the LARGEST
    radius. The "largest" rule is critical for bimetallic 2 EUR studio sources:
    Hough scores the inner gold/silver ring higher than the outer edge because
    its luminance gradient is sharper, so first-by-vote returns the wrong (inner)
    circle. Picking largest among centered candidates returns the actual outer
    coin edge instead. The center filter keeps phantom circles (wood grain,
    table edges) from winning when they happen to be larger than the coin.

    Two-pass cascade: tight precision first (rejects most phantoms), relaxed
    fallback for small/tilted coins where tight params miss.
    """
    h, w = bgr.shape[:2]
    short = min(h, w)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)

    img_cx, img_cy = w / 2.0, h / 2.0
    center_tol_sq = (0.30 * short) ** 2

    for pass_name, p1, p2, rmin_frac, rmax_frac in (
        ("hough_tight",   100, 30, 0.15, 0.55),
        ("hough_relaxed",  60, 22, 0.10, 0.55),
    ):
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.0,
            minDist=short,
            param1=p1,
            param2=p2,
            minRadius=int(short * rmin_frac),
            maxRadius=int(short * rmax_frac),
        )
        if circles is None or len(circles[0]) == 0:
            continue

        centered = [
            c for c in circles[0]
            if (c[0] - img_cx) ** 2 + (c[1] - img_cy) ** 2 <= center_tol_sq
        ]
        if not centered:
            continue
        best = max(centered, key=lambda c: c[2])
        return int(best[0]), int(best[1]), int(best[2]), pass_name

    return None


def normalize(bgr: np.ndarray) -> NormalizationResult:
    """Normalize a raw BGR frame into a 224×224 tight coin crop."""
    if bgr is None or bgr.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty input"})

    detection = _detect_coin_circle(bgr)
    if detection is None:
        return NormalizationResult(image=None, debug={"error": "no circle"})

    cx, cy, r, method = detection
    h, w = bgr.shape[:2]

    margin = int(r * COIN_MARGIN)
    half = r + margin
    x0 = max(0, cx - half)
    y0 = max(0, cy - half)
    x1 = min(w, cx + half)
    y1 = min(h, cy + half)

    # Force a square crop — image edge clipping can asymmetrically bias the
    # bbox. Take the smaller dimension and recenter on the coin.
    side = min(x1 - x0, y1 - y0)
    x1, y1 = x0 + side, y0 + side

    crop = bgr[y0:y1, x0:x1].copy()
    if crop.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty crop"})

    crop_cx = cx - x0
    crop_cy = cy - y0

    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (crop_cx, crop_cy), r, 255, -1)
    bg = np.full_like(crop, BG_COLOR, dtype=np.uint8)
    crop = np.where(mask[..., None].astype(bool), crop, bg)

    out = cv2.resize(crop, (OUTPUT_SIZE, OUTPUT_SIZE), interpolation=cv2.INTER_AREA)

    return NormalizationResult(
        image=out, cx=cx, cy=cy, r=r, method=method,
        debug={"input_size": (w, h), "crop_side": side, "margin_px": margin},
    )


def normalize_path(path: Path) -> NormalizationResult:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return normalize(bgr)


def draw_debug(bgr: np.ndarray, result: NormalizationResult) -> np.ndarray:
    """Annotated copy of the input with the detected circle drawn."""
    out = bgr.copy()
    if result.image is None:
        cv2.putText(out, f"FAILED: {result.debug.get('error', '?')}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return out
    cv2.circle(out, (result.cx, result.cy), result.r, (0, 255, 0), 2)
    cv2.circle(out, (result.cx, result.cy), 3, (0, 255, 0), -1)
    cv2.putText(out, f"r={result.r}px {result.method}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    return out
