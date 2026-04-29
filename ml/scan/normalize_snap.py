"""Snap normalization — raw image → tight 224×224 coin crop on a black BG.

Two pipelines, one shared output contract.

  * `normalize_studio(bgr)` — for Numista studio sources (training pipeline).
    Otsu-based contour detection at `WORKING_RES = 1024` long-side, then
    `cv2.minEnclosingCircle` (sub-pixel `(cx, cy, r)` preserved through the
    crop). Bimetal-ring guard via `fill_ratio < 0.7`. Falls back to the
    device pipeline on contour failure (no contour, off-centre, ring
    contour, image-filling collapse).

  * `normalize_device(bgr)` — for camera frames (Android live + offline
    eval_real). Hough cascade `tight → relaxed` at `WORKING_RES = 1024`
    long-side, with **wide** radius range `0.15–0.55 / 0.10–0.55` — the
    legacy on-device range that was validated through R@1 = 94.74% in
    Phase D. A tighter 0.35–0.55 floor was tried in Phase C but introduced
    parasitic circle picks on device frames with variable BG (cf. comment
    on `_DEVICE_HOUGH_PASSES` below). Mirrored bit-for-bit by
    `app-android/.../ml/SnapNormalizer.kt`.

The 224×224 BGR output is the unit of cohérence: both pipelines must produce
ε-equivalent outputs on the same input image (cross-algo test #1, see
`docs/scan-normalization/normalize-rework/parity-contract.md`).

Constants:
  - `OUTPUT_SIZE = 224`         (figé par le contrat ArcFace)
  - `COIN_MARGIN = 0.02`        (figé)
  - `BG_COLOR    = (0, 0, 0)`   (figé)
  - `WORKING_RES = 1024`        (long-side, partagé par les deux pipelines)

See `docs/scan-normalization/README.md` and
`docs/scan-normalization/normalize-rework/algorithms.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np


OUTPUT_SIZE = 224
COIN_MARGIN = 0.02
BG_COLOR = (0, 0, 0)
WORKING_RES = 1024

# Studio pipeline tuning (cf. algorithms.md §"Pipeline studio").
_STUDIO_FILL_RATIO_MIN = 0.70   # bimétal/ring guard: contour area / minEnclosingCircle area
_STUDIO_AREA_RATIO_MAX = 0.85   # reject Otsu collapse where the binarisation swallowed the frame
_STUDIO_CENTER_TOL_FRAC = 0.30  # contour centroid must be within 0.30·short of image centre

# Device pipeline cascade. Wide radius range 0.15–0.55 / 0.10–0.55 — same as
# the legacy on-device path that was validated through R@1=94.74% in Phase D.
#
# Why not the bench-validated tight 0.35–0.55? The Phase A bench measured
# tight on **studio sources** (Numista, uniform BG, coin centred and
# frame-filling — the radius range is then a guaranteed match). On **device
# frames** the BG carries gradients (table grain, shadow, vignette) which
# Hough can vote into circular candidates. With a tight rmin floor the rule
# "largest centred" risks picking up such a parasitic circle over the actual
# coin rim (cf. user-reported offset bug 2026-04-29 post-Phase C: the snap
# fell back to hough_relaxed and the cropped 224 was massively shifted).
#
# Speed loss vs tight is negligible on the live ImageAnalysis path (~720p
# already ≤ working_res 1024 → no downscale), and bounded for higher-res
# inputs (Phase F) by the working_res cap. The studio pipeline keeps the
# tight cascade in its fallback (`_studio_fallback`) because once it falls
# through, we already know the contour pipeline rejected the image — the
# studio source is well-behaved by definition.
#
# Mirrored bit-for-bit by `SnapNormalizer.kt::PASSES`.
_DEVICE_HOUGH_PASSES = (
    # (name,           param1, param2, rmin_frac, rmax_frac)
    ("hough_tight",    100.0,  30.0,   0.15,      0.55),
    ("hough_relaxed",   60.0,  22.0,   0.10,      0.55),
)


@dataclass
class NormalizationResult:
    image: np.ndarray | None    # 224×224 BGR uint8, None on failure
    cx: int = 0
    cy: int = 0
    r: int = 0
    method: str = "failed"      # "contour" | "contour_fallback:hough_*" | "hough_tight" | "hough_relaxed" | "failed"
    debug: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _downscale_to_working_res(bgr: np.ndarray) -> tuple[np.ndarray, float]:
    """Return (work_image, scale) where scale = native_long_side / WORKING_RES.
    `scale=1.0` if the input is already ≤ WORKING_RES. INTER_AREA so the
    detection sees a clean low-pass downsample."""
    h, w = bgr.shape[:2]
    long_side = max(h, w)
    if long_side <= WORKING_RES:
        return bgr, 1.0
    scale = long_side / WORKING_RES
    new_w = int(round(w / scale))
    new_h = int(round(h / scale))
    return cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA), scale


def _crop_mask_resize_float(bgr: np.ndarray, cx: float, cy: float, r: float,
                             method: str,
                             extra_debug: dict | None = None) -> NormalizationResult:
    """Sub-pixel-aware crop / mask / resize. Bounds maths in float; rounds to
    int only at the slicing boundary. Used by `normalize_studio` to preserve
    the precision of `minEnclosingCircle`."""
    h, w = bgr.shape[:2]
    margin = r * COIN_MARGIN
    half = r + margin
    x0_f = max(0.0, cx - half)
    y0_f = max(0.0, cy - half)
    x1_f = min(float(w), cx + half)
    y1_f = min(float(h), cy + half)
    side_f = min(x1_f - x0_f, y1_f - y0_f)
    x1_f = x0_f + side_f
    y1_f = y0_f + side_f

    x0 = int(round(x0_f))
    y0 = int(round(y0_f))
    x1 = int(round(x1_f))
    y1 = int(round(y1_f))

    crop = bgr[y0:y1, x0:x1].copy()
    if crop.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty crop"})

    crop_cx = int(round(cx - x0_f))
    crop_cy = int(round(cy - y0_f))

    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (crop_cx, crop_cy), int(round(r)), 255, -1)
    bg = np.full_like(crop, BG_COLOR, dtype=np.uint8)
    crop = np.where(mask[..., None].astype(bool), crop, bg)

    out = cv2.resize(crop, (OUTPUT_SIZE, OUTPUT_SIZE), interpolation=cv2.INTER_AREA)
    debug: dict[str, Any] = {
        "input_size": (w, h),
        "crop_side": int(round(side_f)),
        "margin_px": float(margin),
    }
    if extra_debug:
        debug.update(extra_debug)
    return NormalizationResult(
        image=out, cx=int(round(cx)), cy=int(round(cy)),
        r=int(round(r)), method=method, debug=debug,
    )


def _crop_mask_resize_int(bgr: np.ndarray, cx: int, cy: int, r: int,
                           method: str) -> NormalizationResult:
    """Integer-arithmetic crop / mask / resize. Used by `normalize_device` to
    keep bit-for-bit parity with the Kotlin port (Mat.toInt() truncation)."""
    h, w = bgr.shape[:2]
    margin = int(r * COIN_MARGIN)
    half = r + margin
    x0 = max(0, cx - half)
    y0 = max(0, cy - half)
    x1 = min(w, cx + half)
    y1 = min(h, cy + half)
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


# ---------------------------------------------------------------------------
# Device pipeline (Hough at WR=1024, tight cascade)
# ---------------------------------------------------------------------------

def _detect_circle_hough(bgr: np.ndarray) -> tuple[int, int, int, str] | None:
    """Hough cascade tight→relaxed at WORKING_RES=1024. Returns
    `(cx, cy, r, method)` in **native pixel** coordinates (int truncation,
    matching Kotlin `Mat.toInt()`), or None if nothing centred is found.

    Selection rule = "largest centred". Centred = within 30% of short side
    from frame centre. Largest = picks the outer rim on bimétal where Hough
    would otherwise vote the inner ring. Two-pass cascade: tight precision
    first, relaxed recall as fallback."""
    work, scale = _downscale_to_working_res(bgr)
    sh, sw = work.shape[:2]
    short = min(sh, sw)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)

    img_cx, img_cy = sw / 2.0, sh / 2.0
    center_tol_sq = (0.30 * short) ** 2

    for pass_name, p1, p2, rmin_frac, rmax_frac in _DEVICE_HOUGH_PASSES:
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.0, minDist=short,
            param1=p1, param2=p2,
            minRadius=int(short * rmin_frac),
            maxRadius=int(short * rmax_frac),
        )
        if circles is None or len(circles[0]) == 0:
            continue
        centred = [
            c for c in circles[0]
            if (c[0] - img_cx) ** 2 + (c[1] - img_cy) ** 2 <= center_tol_sq
        ]
        if not centred:
            continue
        best = max(centred, key=lambda c: c[2])
        cx_n = int(best[0] * scale)
        cy_n = int(best[1] * scale)
        r_n = int(best[2] * scale)
        return cx_n, cy_n, r_n, pass_name

    return None


def normalize_device(bgr: np.ndarray) -> NormalizationResult:
    """Normalize a camera frame (live or offline eval_real_norm) into a
    224×224 tight coin crop. Bit-for-bit port to `SnapNormalizer.kt`."""
    if bgr is None or bgr.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty input"})
    detection = _detect_circle_hough(bgr)
    if detection is None:
        return NormalizationResult(image=None, debug={"error": "no circle"})
    cx, cy, r, method = detection
    return _crop_mask_resize_int(bgr, cx, cy, r, method)


def normalize_device_path(path: Path) -> NormalizationResult:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return normalize_device(bgr)


# ---------------------------------------------------------------------------
# Studio pipeline (Otsu + minEnclosingCircle at WR=1024)
# ---------------------------------------------------------------------------

def _detect_circle_contour(bgr: np.ndarray
                            ) -> tuple[float, float, float, dict] | None:
    """Otsu-based contour detection at WORKING_RES=1024. Returns
    `(cx, cy, r, debug)` in **native pixel** coordinates with **sub-pixel
    precision**, or None if the contour is unusable (no centred contour,
    ring shape, image-filling). The reason is in `debug["fallback_reason"]`
    so the caller can log it."""
    work, scale = _downscale_to_working_res(bgr)
    h, w = work.shape[:2]
    short = min(h, w)
    img_area = float(h * w)
    img_cx, img_cy = w / 2.0, h / 2.0

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    # Polarity: corners brighter than the Otsu threshold = light BG (Numista
    # standard) → THRESH_BINARY_INV (foreground = darker coin). Atypical
    # darker-BG sources fall through to the direct flag.
    corners = np.array([gray[0, 0], gray[0, -1], gray[-1, 0], gray[-1, -1]])
    otsu_thr, _ = cv2.threshold(gray, 0, 255,
                                 cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    flag = cv2.THRESH_BINARY_INV if corners.mean() > otsu_thr else cv2.THRESH_BINARY
    _, mask = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)

    k = max(3, short // 200) | 1  # ~5 at 1024
    kernel = np.ones((k, k), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None  # caller sets fallback_reason

    tol_sq = (_STUDIO_CENTER_TOL_FRAC * short) ** 2
    centred: list[tuple[float, np.ndarray]] = []
    for c in contours:
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        ccx = M["m10"] / M["m00"]
        ccy = M["m01"] / M["m00"]
        if (ccx - img_cx) ** 2 + (ccy - img_cy) ** 2 <= tol_sq:
            centred.append((cv2.contourArea(c), c))
    if not centred:
        return None

    area, best = max(centred, key=lambda x: x[0])
    if area / img_area > _STUDIO_AREA_RATIO_MAX:
        # Otsu collapsed everything into foreground.
        return None

    (cx, cy), r = cv2.minEnclosingCircle(best)
    fill_ratio = area / max(1.0, np.pi * r * r)
    if fill_ratio < _STUDIO_FILL_RATIO_MIN:
        # Ring contour (bimétal misfire) — fallback.
        return None

    debug = {
        "fill_ratio": float(fill_ratio),
        "working_res": WORKING_RES,
        "scale": float(scale),
    }
    return cx * scale, cy * scale, r * scale, debug


def normalize_studio(bgr: np.ndarray) -> NormalizationResult:
    """Normalize a Numista studio source (training pipeline) into a 224×224
    tight coin crop. Falls back to `normalize_device` if the contour
    detection fails (no contour / off-centre / ring / image-filling)."""
    if bgr is None or bgr.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty input"})

    det = _detect_circle_contour(bgr)
    if det is None:
        # Fallback to device pipeline. Tag method so we can count fallback rate.
        res = normalize_device(bgr)
        if res.image is not None:
            res.method = f"contour_fallback:{res.method}"
        # We don't know the precise reason here without re-running the
        # detector; keeping it generic is enough for the fallback rate stat.
        res.debug.setdefault("fallback_reason", "contour_failed")
        return res

    cx, cy, r, extra_debug = det
    return _crop_mask_resize_float(bgr, cx, cy, r, method="contour",
                                    extra_debug=extra_debug)


def normalize_studio_path(path: Path) -> NormalizationResult:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return normalize_studio(bgr)


# ---------------------------------------------------------------------------
# Debug overlay (used by preview_normalized)
# ---------------------------------------------------------------------------

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
