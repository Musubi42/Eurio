"""Snap normalization — raw image → tight 224×224 coin crop on a black BG.

Two pipelines, one shared output contract.

  * `normalize_studio(bgr)` — for Numista studio sources (training pipeline).
    Otsu-based contour detection at `WORKING_RES = 1024` long-side, then
    `cv2.minEnclosingCircle` (sub-pixel `(cx, cy, r)` preserved through the
    crop). Bimetal-ring guard via `fill_ratio < 0.7`. Falls back to the
    device pipeline on contour failure (no contour, off-centre, ring
    contour, image-filling collapse) — `fallback_reason` is reported in
    `result.debug` so callers can attribute the miss.

  * `normalize_device(bgr)` — for camera frames (Android live + offline
    eval_real). Hough cascade `strict → loose` at `WORKING_RES = 1024`
    long-side, with **wide** radius range `0.15–0.55 / 0.10–0.55` — the
    legacy on-device range validated by R@1 = 94.74% on the device golden
    set. A tighter 0.35–0.55 floor was tried but caused parasitic circle
    picks on frames with variable BG (cf. `_DEVICE_HOUGH_PASSES` below).
    Mirrored bit-for-bit by `app-android/.../ml/SnapNormalizer.kt`.

The 224×224 BGR output is the unit of cohérence: both pipelines must
produce ε-equivalent outputs on the same input image. See
`docs/scan-normalization/README.md`.

Constants:
  - `OUTPUT_SIZE = 224`         (figé par le contrat ArcFace)
  - `COIN_MARGIN = 0.02`        (figé)
  - `BG_COLOR    = (0, 0, 0)`   (figé)
  - `WORKING_RES = 1024`        (long-side, partagé par les deux pipelines)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np


OUTPUT_SIZE = 224
COIN_MARGIN = 0.02
BG_COLOR = (0, 0, 0)
WORKING_RES = 1024


@dataclass(frozen=True)
class CropConfig:
    """Format de crop final (post-détection). Permet l'ablation du format
    sans toucher la détection (Hough/YOLO/contour reste identique).

    `margin_frac` : marge radiale autour du rim détecté, en fraction de r.
    Le crop carré a un côté `2*(r + margin_frac*r) = 2r·(1+margin_frac)`.

    `edge_mode` :
      - "hard"     → masque circulaire net à rayon r, hors-disque = BG_COLOR
      - "feathered"→ masque circulaire feathered (gaussian blur sur la frontière),
                     contrôlé par `feather_width_frac` × r
      - "none"     → pas de masque, on garde le fond original (cropped+resized)

    `output_size` : côté carré en pixels du crop final.

    Default = comportement legacy (margin 2%, hard mask, 224×224).
    """
    margin_frac: float = COIN_MARGIN
    edge_mode: str = "hard"          # "hard" | "feathered" | "none"
    feather_width_frac: float = 0.04  # ignoré si edge_mode != "feathered"
    output_size: int = OUTPUT_SIZE


_DEFAULT_CROP_CONFIG = CropConfig()


def _apply_edge_mask(crop: np.ndarray, cx: int, cy: int, r: int,
                     edge_mode: str, feather_width_px: int) -> np.ndarray:
    """Applique le masque selon edge_mode. Retourne le crop modifié.
    `crop` est l'image carrée déjà découpée ; (cx, cy) sont les coords du
    centre dans l'espace de `crop`."""
    if edge_mode == "none":
        return crop
    h, w = crop.shape[:2]
    if edge_mode == "hard":
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(mask, (cx, cy), r, 255, -1)
        bg = np.full_like(crop, BG_COLOR, dtype=np.uint8)
        return np.where(mask[..., None].astype(bool), crop, bg)
    if edge_mode == "feathered":
        # Masque float32 [0,1] : disque dur puis blur gaussien sur la frontière.
        # Kernel impair, taille ~2× feather_width pour couvrir la transition.
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(mask, (cx, cy), r, 255, -1)
        k = max(3, feather_width_px | 1)  # force impair
        mask_f = cv2.GaussianBlur(mask, (k, k), 0).astype(np.float32) / 255.0
        bg = np.full_like(crop, BG_COLOR, dtype=np.uint8).astype(np.float32)
        out = mask_f[..., None] * crop.astype(np.float32) + (1 - mask_f[..., None]) * bg
        return np.clip(out, 0, 255).astype(np.uint8)
    raise ValueError(f"unknown edge_mode: {edge_mode!r}")

# Studio pipeline tuning.
_STUDIO_FILL_RATIO_MIN = 0.70   # bimétal/ring guard: contour area / minEnclosingCircle area
_STUDIO_AREA_RATIO_MAX = 0.85   # reject Otsu collapse where the binarisation swallowed the frame
_STUDIO_CENTER_TOL_FRAC = 0.30  # contour centroid must be within 0.30·short of image centre

# Device pipeline cascade. The naming `strict / loose` describes the Hough
# `param2` accumulator threshold (precision floor first, recall fallback) —
# **not** the radius range, which is intentionally wide on both passes.
#
# Why wide radius (0.15–0.55 / 0.10–0.55) rather than tight (0.35–0.55)?
# Tight was tried and rejected: on device frames the BG carries gradients
# (table grain, shadow, vignette) which Hough can vote into circular
# candidates. With a tight rmin floor the "largest centred" selection rule
# would then pick a parasitic background circle over the actual coin rim,
# producing massively offset 224 crops. The wide range matches the legacy
# on-device path that produced R@1 = 94.74 % on the device golden set.
#
# Speed loss vs tight is negligible on the live ImageAnalysis path (~720p
# already ≤ working_res 1024 → no downscale), and bounded for higher-res
# inputs by the working_res cap. There is no "studio fallback cascade":
# when the studio contour pipeline rejects an image, it calls
# `normalize_device` directly — same passes, same wide radius range.
#
# Future work flagged: the device pipeline does **not** apply the
# `fill_ratio` bimétal guard that the studio pipeline uses; on bimétal
# coins Hough picks the inner cupro/or ring rather than the rim ~36 % of
# the time. The "largest centred" rule mitigates but does not fully fix
# this. Adding a fill_ratio guard equivalent to `_STUDIO_FILL_RATIO_MIN`
# is a separate sprint — would close the train↔inference latent drift on
# bimétal classes.
#
# Mirrored bit-for-bit by `SnapNormalizer.kt::PASSES`.
_DEVICE_HOUGH_PASSES = (
    # (name,          param1, param2, rmin_frac, rmax_frac)
    ("hough_strict",  100.0,  30.0,   0.15,      0.55),
    ("hough_loose",    60.0,  22.0,   0.10,      0.55),
)


@dataclass
class NormalizationResult:
    image: np.ndarray | None    # 224×224 BGR uint8, None on failure
    cx: int = 0
    cy: int = 0
    r: int = 0
    method: str = "failed"      # "contour" | "contour_fallback:hough_*" | "hough_strict" | "hough_loose" | "failed"
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class CircleDetection:
    """Output of `detect_circles_multi` — one circle, accepted or rejected.

    Coordinates are in **native pixel** space (input BGR image).
    `accepted=True` means the circle passes the strict criteria and will
    be cropped by `normalize_listing`. `accepted=False` is reported for
    the debug view (Stage 2 of the lot review) so the human can see what
    the pipeline considered and rejected.

    `votes` carries the YOLO confidence (0..1) for `yolo+*` methods, or
    `0.0` for legacy Hough-only methods.
    """
    cx: int
    cy: int
    r: int
    method: str               # "yolo+hough" | "yolo+bbox" | legacy "hough_*"
    votes: float = 0.0        # YOLO confidence (yolo+*) or 0 (hough-only)
    accepted: bool = True
    reject_reason: str | None = None  # "radius_too_small" | "radius_too_large" | "off_edge" | "low_structure" | "gated_fragment"


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
                             extra_debug: dict | None = None,
                             config: CropConfig | None = None) -> NormalizationResult:
    """Sub-pixel-aware crop / mask / resize. Bounds maths in float; rounds to
    int only at the slicing boundary. Used by `normalize_studio` to preserve
    the precision of `minEnclosingCircle`.

    `config=None` → behavior identique au legacy (margin 0.02, hard mask, 224)."""
    cfg = config if config is not None else _DEFAULT_CROP_CONFIG
    h, w = bgr.shape[:2]
    margin = r * cfg.margin_frac
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

    feather_px = int(round(cfg.feather_width_frac * r))
    crop = _apply_edge_mask(crop, crop_cx, crop_cy, int(round(r)),
                            cfg.edge_mode, feather_px)

    out = cv2.resize(crop, (cfg.output_size, cfg.output_size),
                     interpolation=cv2.INTER_AREA)
    debug: dict[str, Any] = {
        "input_size": (w, h),
        "crop_side": int(round(side_f)),
        "margin_px": float(margin),
        "edge_mode": cfg.edge_mode,
        "output_size": cfg.output_size,
    }
    if extra_debug:
        debug.update(extra_debug)
    return NormalizationResult(
        image=out, cx=int(round(cx)), cy=int(round(cy)),
        r=int(round(r)), method=method, debug=debug,
    )


def _crop_mask_resize_int(bgr: np.ndarray, cx: int, cy: int, r: int,
                           method: str,
                           config: CropConfig | None = None) -> NormalizationResult:
    """Integer-arithmetic crop / mask / resize. Used by `normalize_device` to
    keep bit-for-bit parity with the Kotlin port (Mat.toInt() truncation).

    `config=None` → behavior identique au legacy (margin 0.02, hard mask, 224).
    Quand un autre `config` est utilisé, la parité Kotlin n'est PAS garantie —
    le port Kotlin doit être mis à jour symétriquement (Step 4 cutover)."""
    cfg = config if config is not None else _DEFAULT_CROP_CONFIG
    h, w = bgr.shape[:2]
    margin = int(r * cfg.margin_frac)
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
    feather_px = int(r * cfg.feather_width_frac)
    crop = _apply_edge_mask(crop, crop_cx, crop_cy, r, cfg.edge_mode, feather_px)

    out = cv2.resize(crop, (cfg.output_size, cfg.output_size),
                     interpolation=cv2.INTER_AREA)
    return NormalizationResult(
        image=out, cx=cx, cy=cy, r=r, method=method,
        debug={"input_size": (w, h), "crop_side": side, "margin_px": margin,
               "edge_mode": cfg.edge_mode, "output_size": cfg.output_size},
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


def normalize_device(bgr: np.ndarray,
                     config: CropConfig | None = None) -> NormalizationResult:
    """Normalize a camera frame (live or offline eval_real_norm) into a tight
    coin crop. Bit-for-bit port to `SnapNormalizer.kt` quand `config=None`.

    `config` permet l'ablation format (margin, edge_mode, output_size). Quand
    un config non-default est passé, la parité Kotlin n'est PAS garantie."""
    if bgr is None or bgr.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty input"})
    detection = _detect_circle_hough(bgr)
    if detection is None:
        return NormalizationResult(image=None, debug={"error": "no circle"})
    cx, cy, r, method = detection
    return _crop_mask_resize_int(bgr, cx, cy, r, method, config=config)


def normalize_device_path(path: Path,
                          config: CropConfig | None = None) -> NormalizationResult:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return normalize_device(bgr, config=config)


# ---------------------------------------------------------------------------
# Studio pipeline (Otsu + minEnclosingCircle at WR=1024)
# ---------------------------------------------------------------------------

def _detect_circle_contour(bgr: np.ndarray
                            ) -> tuple[tuple[float, float, float, dict] | None, str | None]:
    """Otsu-based contour detection at WORKING_RES=1024.

    Returns ``(detection, reason)`` where exactly one is None:
      - ``detection = (cx, cy, r, debug)`` in native-pixel sub-pixel coords
        on success; ``reason = None``.
      - ``detection = None``; ``reason`` is one of ``"no_contour"``,
        ``"off_centre"``, ``"image_filling"``, ``"ring_contour"``.
    """
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
        return None, "no_contour"

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
        return None, "off_centre"

    area, best = max(centred, key=lambda x: x[0])
    if area / img_area > _STUDIO_AREA_RATIO_MAX:
        # Otsu collapsed everything into foreground.
        return None, "image_filling"

    (cx, cy), r = cv2.minEnclosingCircle(best)
    fill_ratio = area / max(1.0, np.pi * r * r)
    if fill_ratio < _STUDIO_FILL_RATIO_MIN:
        # Ring contour (bimétal misfire) — fallback.
        return None, "ring_contour"

    debug = {
        "fill_ratio": float(fill_ratio),
        "working_res": WORKING_RES,
        "scale": float(scale),
    }
    return (cx * scale, cy * scale, r * scale, debug), None


def normalize_studio(bgr: np.ndarray,
                      config: CropConfig | None = None) -> NormalizationResult:
    """Normalize a Numista studio source (training pipeline) into a tight coin
    crop. Falls back to `normalize_device` if the contour detection fails — the
    reason (no_contour / off_centre / image_filling / ring_contour) is reported
    in ``result.debug["fallback_reason"]``.

    `config` permet l'ablation format (margin, edge_mode, output_size)."""
    if bgr is None or bgr.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty input"})

    det, reason = _detect_circle_contour(bgr)
    if det is None:
        # Fallback to device pipeline. Tag method so we can count fallback rate.
        res = normalize_device(bgr, config=config)
        if res.image is not None:
            res.method = f"contour_fallback:{res.method}"
        res.debug["fallback_reason"] = reason
        return res

    cx, cy, r, extra_debug = det
    return _crop_mask_resize_float(bgr, cx, cy, r, method="contour",
                                    extra_debug=extra_debug, config=config)


def normalize_studio_path(path: Path,
                           config: CropConfig | None = None) -> NormalizationResult:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return normalize_studio(bgr, config=config)


# ---------------------------------------------------------------------------
# Listing pipeline (eBay & co — multi-coin tolerant, multi-Hough)
# ---------------------------------------------------------------------------

# Listing pipeline = YOLO prior + Hough refine intra-ROI.
#
# Pourquoi pas Hough nu : sur fonds hétérogènes (coincard avec texte +
# motifs décoratifs, blisters, mosaïques eBay), la passe Hough loose vote
# sur les lettres et patterns circulaires, produisant des dizaines de
# faux candidats inacceptables pour la review. YOLOv8-nano single-class
# entraîné sur des pièces (`ml/output/detection/coin_detector/weights/best.pt`)
# fournit un prior "où se trouvent les pièces", et Hough raffine le rim
# sub-pixel intra-ROI — même contrat que la pipeline unifiée du device
# (`docs/research/detection-pipeline-unified.md`).
#
# Reject criteria (post-refine) restent strictes : radius_too_small/large/off_edge.
# Pas de seuil "low_confidence" séparé — `_YOLO_CONF_THRESHOLD` filtre déjà à la source.
_YOLO_MODEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "output" / "detection" / "coin_detector" / "weights" / "best.pt"
)
_YOLO_CONF_THRESHOLD = 0.35
_YOLO_IOU_THRESHOLD = 0.45
_YOLO_IMGSZ = 640

# --- Mode CENSUS (flag, OFF par défaut) -----------------------------------
# Activé par `EURIO_CENSUS_DETECT=1`. Bascule la détection listing sur les
# réglages "haut rappel" validés au bench census (docs/cohort-pipeline/
# census-detector-design.md §6) : conf YOLO 0.35→0.10, dédup `nms_concentric`
# (gardes taille+bord), et RELÂCHE les post-filtres stricts qui jetaient des
# pièces VISIBLES (rmin 0.08→0.04, plus de `low_structure`, plus de `off_edge`).
# Mesuré : récupère ~89% des zéro-crop, faux-single détecteur 48%→0%. Contrepartie :
# plus de crops (dont fragments sur singles) → review plus grosse. Le Hough refine /
# polish / rim-refine de qualité de crop sont CONSERVÉS (ils n'affectent pas le rappel).
def _census_detect_enabled() -> bool:
    return os.environ.get("EURIO_CENSUS_DETECT") == "1"


# Gate anti-fragment (piste 3, census-detector-design.md §9) : une probe DINO
# « face entière vs fragment » filtre les crops census fragmentés (tranche/lettrage,
# anneau interne, partiels, capsule) que le haut-rappel YOLO@0.10 produit sur les
# singles. S'applique APRÈS le crop (la probe a vu les crops 224 finaux). τ par défaut
# 0.45 (LOCO-CV 9 classes : recall faces 96 %, coupe 89 % des fragments). τ≤0 désactive
# le gate (census brut = comportement §8). Sans effet hors mode census.
def _census_fragment_tau() -> float:
    try:
        return float(os.environ.get("EURIO_CENSUS_FRAGMENT_TAU", "0.55"))
    except ValueError:
        return 0.55

_CENSUS_YOLO_CONF = 0.10
_CENSUS_RMIN_FRAC = 0.04
_YOLO_BBOX_MARGIN_FRAC = 0.00  # ROI = bbox strict. +15% laissait Hough voir capsule/arches autour
                                # → votes parasites pour cercles non-rim sur coincards Meritxell-style.

_LISTING_RMIN_FRAC_STRICT = 0.08   # calibré sur distrib corpus eBay (n=3664 bboxes) :
                                    # cassure naturelle p75=0.047 → p90=0.091, vraies pièces ≥ 0.08
_LISTING_RMAX_FRAC_STRICT = 0.55
_LISTING_EDGE_MARGIN_FRAC = 0.005

# Rim refine post-détection (anti-undercrop bimétal). Cf. detect_circles_multi
# et crop_detectors.detect_bbox_refine. Listing-only (n'affecte PAS le scan
# device normalize_device, ni sa parité Kotlin).
_LISTING_RIM_REFINE = True

# Pré-filtre bbox YOLO. Sur des coincards/blisters, YOLO confond souvent
# lettres ("O"/"D"/"R") et motifs décoratifs avec des pièces lointaines —
# bboxes minuscules (r << rmin_strict) qui ne contiennent aucune info
# utile pour le debug humain et qui créent juste du bruit visuel rouge
# dans la review UI. On les drop avant Hough refine. 0.7×rmin_strict garde
# les "presque" (vraie pièce mal cadrée) ; calibré sur la distrib pour
# couper sous le pic de bruit massif (65% des bboxes ont r/short < 0.04).
_YOLO_BBOX_MIN_RADIUS_FRAC = 0.7  # ratio de rmin_strict

# Hough refine intra-ROI : params plus tolérants car ROI propre (pas de BG bruyant).
_REFINE_HOUGH_PARAM1 = 80.0
_REFINE_HOUGH_PARAM2 = 18.0
_REFINE_RMIN_FRAC = 0.30  # fraction du min(roi_w, roi_h)
_REFINE_RMAX_FRAC = 0.60

# Polish par gradient radial. Voir docs/sources-refacto/listing-crop-roadmap.md
# Piste 1. Sur les pièces capsulées / coincards, le candidat (Hough ou bbox)
# tombe souvent sur le bord de la capsule plastique au lieu du rim métallique.
# On scanne r ∈ [0.70·r₀, min(1.05·r₀, r_max_clamp)] et on sélectionne le
# rayon qui maximise la moyenne du gradient radial (= |∂I/∂n| le long du
# cercle). Le rim métal/fond a un gradient typiquement 2-4× plus fort que
# le bord plastique transparent → max-gradient discrimine.
_POLISH_SEARCH_LOW_FRAC  = 0.70
_POLISH_SEARCH_HIGH_FRAC = 1.05
_POLISH_N_RADII   = 30
_POLISH_N_ANGLES  = 64
_POLISH_MIN_GAIN  = 1.05  # accepter le polish ssi score(r_best)/score(r₀) > 1.05

# Garde structure intra-disque. YOLO classe parfois des stickers / hologrammes
# carrés (`SAMMLERPOSTEN`, sceaux, codes-barres) comme pièces, ce qui produit
# un crop quasi uniforme (pas de design, pas de texte, pas de relief).
# Mesure : moyenne(|Laplacian|) sur le disque inscrit à 0.95·r en pixels natifs.
# Calibré sur golden set (n=19 crops) : hologramme observé = 27, min vraie pièce = 49.
# Threshold 32 = 1.18× au-dessus de l'outlier, 0.65× sous le min légitime.
# À surveiller si une pièce mate sur fond uniforme se fait rejeter — le métrique
# dépend du contraste local, pas seulement du design.
_STRUCTURE_METRIC_DISC_FRAC = 0.95   # disque utilisé : 0.95·r (évite le rim lui-même)
_STRUCTURE_MIN_LAP_MEANABS  = 32.0   # mean(|Laplacian|) min pour un crop coin-like


_yolo_model_cache: Any = None


def _get_yolo_model() -> Any:
    global _yolo_model_cache
    if _yolo_model_cache is None:
        from ultralytics import YOLO
        _yolo_model_cache = YOLO(str(_YOLO_MODEL_PATH))
    return _yolo_model_cache


def _yolo_detect_bboxes(bgr: np.ndarray,
                        conf: float = _YOLO_CONF_THRESHOLD,
                        ) -> list[tuple[float, float, float, float, float]]:
    """Run YOLO on a listing image. Returns a list of
    `(x1, y1, x2, y2, conf)` in **native pixel** space, ordered by
    descending confidence."""
    model = _get_yolo_model()
    res = model.predict(
        bgr, imgsz=_YOLO_IMGSZ,
        conf=conf, iou=_YOLO_IOU_THRESHOLD,
        verbose=False,
    )
    if not res:
        return []
    boxes = res[0].boxes
    if boxes is None or len(boxes) == 0:
        return []
    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    out: list[tuple[float, float, float, float, float]] = []
    for i in range(len(boxes)):
        x1, y1, x2, y2 = xyxy[i].tolist()
        out.append((float(x1), float(y1), float(x2), float(y2), float(confs[i])))
    out.sort(key=lambda t: t[4], reverse=True)
    return out


def _hough_refine_in_roi(bgr: np.ndarray,
                          x1: float, y1: float, x2: float, y2: float,
                          r_max_clamp: float
                          ) -> tuple[float, float, float] | None:
    """Run Hough inside `bgr[y1:y2, x1:x2]` and return the most centred
    circle in **native pixel** coordinates. None if Hough finds nothing
    or all candidates exceed `r_max_clamp` (= bbox half-side, the YOLO
    anchor of trust — Hough must not "expand past" the YOLO bbox onto
    background concentric arcs).

    Scoring = pure centred (min distance² to ROI center). No size bonus —
    that bias was previously letting Hough vote on background arches
    (coincard backgrounds with arches/curves) over the actual rim."""
    h_img, w_img = bgr.shape[:2]
    x1i = max(0, int(round(x1)))
    y1i = max(0, int(round(y1)))
    x2i = min(w_img, int(round(x2)))
    y2i = min(h_img, int(round(y2)))
    if x2i - x1i < 16 or y2i - y1i < 16:
        return None
    roi = bgr[y1i:y2i, x1i:x2i]
    rh, rw = roi.shape[:2]
    short = min(rh, rw)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.0, minDist=short,
        param1=_REFINE_HOUGH_PARAM1, param2=_REFINE_HOUGH_PARAM2,
        minRadius=int(short * _REFINE_RMIN_FRAC),
        maxRadius=int(short * _REFINE_RMAX_FRAC),
    )
    if circles is None or len(circles[0]) == 0:
        return None
    valid = [c for c in circles[0] if c[2] <= r_max_clamp]
    if not valid:
        return None
    rcx, rcy = rw / 2.0, rh / 2.0
    best = min(valid, key=lambda c: (c[0] - rcx) ** 2 + (c[1] - rcy) ** 2)
    return float(x1i + best[0]), float(y1i + best[1]), float(best[2])


def _disc_lap_meanabs(lap: np.ndarray, cx: int, cy: int, r: int) -> float:
    """Moyenne de |Laplacian| sur le disque (cx, cy, 0.95·r). Renvoie +inf si
    le disque sort trop de l'image — on n'écarte alors pas (l'`off_edge` filter
    capturera ce cas si pertinent)."""
    h, w = lap.shape
    r_use = max(1, int(r * _STRUCTURE_METRIC_DISC_FRAC))
    y0 = max(0, cy - r_use)
    y1 = min(h, cy + r_use + 1)
    x0 = max(0, cx - r_use)
    x1 = min(w, cx + r_use + 1)
    if y1 - y0 < 4 or x1 - x0 < 4:
        return float("inf")
    sub = lap[y0:y1, x0:x1]
    sh, sw = sub.shape
    yy, xx = np.ogrid[:sh, :sw]
    lcx = cx - x0
    lcy = cy - y0
    mask = (xx - lcx) ** 2 + (yy - lcy) ** 2 < r_use * r_use
    if not mask.any():
        return float("inf")
    return float(np.abs(sub[mask]).mean())


def _bilinear_sample(field: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear sample of a 2D `field` at sub-pixel coords `(xs, ys)`.
    Out-of-bounds samples → 0. Vectorised."""
    h, w = field.shape
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    valid = (x0 >= 0) & (y0 >= 0) & (x0 < w - 1) & (y0 < h - 1)
    x0c = np.clip(x0, 0, w - 2)
    y0c = np.clip(y0, 0, h - 2)
    fx = xs - x0c
    fy = ys - y0c
    v00 = field[y0c, x0c]
    v10 = field[y0c, x0c + 1]
    v01 = field[y0c + 1, x0c]
    v11 = field[y0c + 1, x0c + 1]
    out = (v00 * (1 - fx) * (1 - fy) + v10 * fx * (1 - fy)
           + v01 * (1 - fx) * fy + v11 * fx * fy)
    out[~valid] = 0.0
    return out


def _radial_gradient_polish(bgr: np.ndarray,
                             cx: float, cy: float, r0: float,
                             r_max_clamp: float
                             ) -> tuple[float, float, float, float, str]:
    """Refine the radius `r0` of a candidate circle by maximising the mean
    radial gradient along the circle. Returns `(cx, cy, r_best, gain, status)`
    where `gain = score(r_best)/score(r₀)`. Center is left untouched —
    Hough/bbox center is reliable; only `r` carries the capsule-vs-rim bias.

    `status` ∈ `{"applied", "skipped:low_gain", "skipped:degenerate"}`.
    """
    h, w = bgr.shape[:2]
    pad = int(r0 * 1.10) + 4
    x0 = max(0, int(cx) - pad)
    y0 = max(0, int(cy) - pad)
    x1 = min(w, int(cx) + pad)
    y1 = min(h, int(cy) + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return cx, cy, r0, 1.0, "skipped:degenerate"

    roi = bgr[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

    lcx = float(cx - x0)
    lcy = float(cy - y0)

    angles = np.linspace(0.0, 2.0 * np.pi, _POLISH_N_ANGLES,
                          endpoint=False, dtype=np.float32)
    cos_t = np.cos(angles)
    sin_t = np.sin(angles)

    def score_at(r_test: float) -> float:
        xs = lcx + r_test * cos_t
        ys = lcy + r_test * sin_t
        gxs = _bilinear_sample(gx, xs, ys)
        gys = _bilinear_sample(gy, xs, ys)
        radial = np.abs(gxs * cos_t + gys * sin_t)
        return float(np.mean(radial))

    r_high = min(r0 * _POLISH_SEARCH_HIGH_FRAC, r_max_clamp)
    r_low = r0 * _POLISH_SEARCH_LOW_FRAC
    if r_high <= r_low:
        return cx, cy, r0, 1.0, "skipped:degenerate"

    radii = np.linspace(r_low, r_high, _POLISH_N_RADII, dtype=np.float32)
    score_r0 = score_at(r0)
    best_score = score_r0
    best_r = r0
    for r_test in radii:
        s = score_at(float(r_test))
        if s > best_score:
            best_score = s
            best_r = float(r_test)

    gain = best_score / max(1e-6, score_r0)
    if gain < _POLISH_MIN_GAIN:
        return cx, cy, r0, gain, "skipped:low_gain"
    return cx, cy, best_r, gain, "applied"


_DUP_CENTER_FRAC = 0.04    # centres à ≤ 4 % du petit côté = la même pièce
_DUP_RADIUS_RATIO = 0.85   # rayons à ≤ 15 % d'écart


def _dedup_duplicate_circles(detections: list["CircleDetection"], short: int) -> None:
    """Marque rejetés (in place) les cercles ACCEPTÉS en doublon : même centre
    ET même rayon qu'un autre = la même pièce détectée 2× (bboxes YOLO
    distinctes mais raffinées sur le même listel). Garde le plus confiant
    (votes, sinon rayon), les autres → accepted=False reason="duplicate_circle".

    Seuils très serrés (centres à <4 % du petit côté) : deux pièces DISTINCTES
    sur une planche sont espacées d'au moins ~1 diamètre → jamais fusionnées.
    Complète `nms_concentric` qui agit sur les bboxes AVANT le rim-refine."""
    dup_center = _DUP_CENTER_FRAC * short
    accepted = [i for i, d in enumerate(detections) if d.accepted]
    for a_pos, i in enumerate(accepted):
        di = detections[i]
        if not di.accepted:
            continue
        for j in accepted[a_pos + 1:]:
            dj = detections[j]
            if not dj.accepted:
                continue
            if (abs(di.cx - dj.cx) <= dup_center
                    and abs(di.cy - dj.cy) <= dup_center
                    and min(di.r, dj.r) / max(di.r, dj.r, 1) >= _DUP_RADIUS_RATIO):
                if (di.votes, di.r) >= (dj.votes, dj.r):
                    dj.accepted = False
                    dj.reject_reason = "duplicate_circle"
                else:
                    di.accepted = False
                    di.reject_reason = "duplicate_circle"
                    break


def detect_circles_multi(bgr: np.ndarray,
                         census: bool | None = None) -> list[CircleDetection]:
    """Detect ALL coins in a listing image (1..N), with accept/reject reasons.

    YOLO produces N bbox candidates above `_YOLO_CONF_THRESHOLD`. For each
    bbox we expand a small margin and run Hough inside the ROI to get a
    sub-pixel rim — that's `method="yolo+hough"`. If Hough finds nothing
    (rim invisible, capsule reflection, …) we fall back to the inscribed
    circle of the bbox — `method="yolo+bbox"`. Either way, the same
    `radius_too_small / radius_too_large / off_edge` post-filter applies.

    `census` : mode haut-rappel + gate anti-fragment (cf. §6-9). `None` (défaut)
    = résolu via le flag d'env `EURIO_CENSUS_DETECT` (chemins bench/CLI) ; un bool
    explicite a priorité (le pipeline eBay passe `census=True` côté detect_crop).

    Returns detections ordered by YOLO confidence descending. Rejected
    circles are reported only for the admin debug view (Stage 2). No
    persistence — recompute is cheap.
    """
    if bgr is None or bgr.size == 0:
        return []
    census = _census_detect_enabled() if census is None else census
    h_img, w_img = bgr.shape[:2]
    short = min(h_img, w_img)
    rmin_frac = _CENSUS_RMIN_FRAC if census else _LISTING_RMIN_FRAC_STRICT
    rmin_strict = int(short * rmin_frac)
    rmax_strict = int(short * _LISTING_RMAX_FRAC_STRICT)
    edge_margin = max(0, int(short * _LISTING_EDGE_MARGIN_FRAC))

    bbox_min_r = _YOLO_BBOX_MIN_RADIUS_FRAC * rmin_strict
    bboxes = _yolo_detect_bboxes(bgr, conf=_CENSUS_YOLO_CONF if census else _YOLO_CONF_THRESHOLD)
    if census and bboxes:
        # Dédup concentrique/contenu (gardes taille+bord) avant refine/crop — évite
        # de cropper N fois la même pièce (anneau bimétal, fragments). Cf. scan.census.
        from vision.census import nms_concentric
        _kept = set(nms_concentric([(b[0], b[1], b[2], b[3]) for b in bboxes],
                                   img_wh=(w_img, h_img)))
        bboxes = [b for b in bboxes if (b[0], b[1], b[2], b[3]) in _kept]
    # Pré-calcul du Laplacian pour le structure guard. Une seule passe par image,
    # puis on échantillonne par détection. Coût ~5-10ms sur 1600x1600.
    _gray_full = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _lap_full = cv2.Laplacian(_gray_full, cv2.CV_32F, ksize=3)
    # Centre + rayon estimé de chaque bbox, pour la garde voisin-aware du
    # rim-refine (un listel ne peut pas empiéter sur la pièce voisine).
    _bbox_centers = [((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0,
                      min(b[2] - b[0], b[3] - b[1]) / 2.0) for b in bboxes]
    detections: list[CircleDetection] = []
    for i, (x1, y1, x2, y2, conf) in enumerate(bboxes):
        bw = x2 - x1
        bh = y2 - y1
        if min(bw, bh) / 2.0 < bbox_min_r:
            continue  # bbox trop petite pour mériter d'être affichée
        mx = bw * _YOLO_BBOX_MARGIN_FRAC
        my = bh * _YOLO_BBOX_MARGIN_FRAC
        # YOLO anchor : Hough refine must stay inside the bbox half-side.
        r_max_clamp = max(bw, bh) / 2.0

        refined = _hough_refine_in_roi(bgr, x1 - mx, y1 - my, x2 + mx, y2 + my,
                                        r_max_clamp=r_max_clamp)
        if refined is not None:
            cx_f, cy_f, r_f = refined
            method = "yolo+hough"
        else:
            cx_f = (x1 + x2) / 2.0
            cy_f = (y1 + y2) / 2.0
            r_f = min(bw, bh) / 2.0
            method = "yolo+bbox"

        cx_f, cy_f, r_f, _gain, polish_status = _radial_gradient_polish(
            bgr, cx_f, cy_f, r_f, r_max_clamp=r_max_clamp,
        )
        if polish_status == "applied":
            method = method + "+polish"

        # Rim refine (chantier crop-quality-overhaul, Chunk 4) : le couple
        # Hough+polish accroche l'anneau interne or↔argent des 2€ bimétalliques
        # ~18 % du temps (undercrop). `detect_bbox_refine` part du cercle courant
        # (hint) et cherche le RIM EXTERNE dans une ROI bornée — plancher
        # r ≥ 0.9·hint (jamais pire), plafond r ≤ 2.6·hint (overcrop borné).
        # Validé sur gold humain (25 gagne / 2 régresse sur 30) + 80 %→94 % oracle.
        # Tag dédié `+rimrefine` (≠ `+lotcrop` du recrop multi-pièces) : permet de
        # tracer quel crop est passé par CE détecteur, et sert de sentinelle de
        # skip à scripts.recrop_ebay_refine. NE PAS retomber sur `+refine` nu,
        # collision avec d'autres passes (cf. chantier crop-quality-overhaul).
        # Import lazy : crop_detectors importe normalize_snap (évite le cycle).
        if _LISTING_RIM_REFINE:
            from vision.crop_detectors import detect_bbox_refine
            # Cap voisin-aware : distance jusqu'au bord proche de la pièce
            # voisine la plus proche. Borne la ROI et le plafond du rim-refine
            # → tue l'explosion à 2.6× quand la ROI engloutit les capsules
            # adjacentes sur une planche multi-pièces. Mono-pièce → None →
            # comportement bimétal validé inchangé.
            neighbor_max_r: float | None = None
            if len(_bbox_centers) > 1:
                gaps = [float(np.hypot(cx_f - ox, cy_f - oy)) - orr
                        for j, (ox, oy, orr) in enumerate(_bbox_centers) if j != i]
                if gaps:
                    neighbor_max_r = max(0.0, min(gaps))
            _ref = detect_bbox_refine(bgr, hint={"cx": cx_f, "cy": cy_f, "r": r_f},
                                      max_r=neighbor_max_r)
            if _ref.ok and _ref.r > 0:
                cx_f, cy_f, r_f = _ref.cx, _ref.cy, _ref.r
                method = method + "+rimrefine"

        cx_n = int(round(cx_f))
        cy_n = int(round(cy_f))
        r_n = int(round(r_f))

        accepted = True
        reason: str | None = None
        if r_n < rmin_strict:
            accepted = False
            reason = "radius_too_small"
        elif r_n > rmax_strict:
            accepted = False
            reason = "radius_too_large"
        elif not census and (cx_n - r_n < edge_margin or cy_n - r_n < edge_margin
                             or cx_n + r_n > w_img - edge_margin
                             or cy_n + r_n > h_img - edge_margin):
            # off_edge : désactivé en census (pièces emballées/partielles touchent
            # souvent le bord → ce filtre les jetait = zéro-crop).
            accepted = False
            reason = "off_edge"
        elif not census and _disc_lap_meanabs(_lap_full, cx_n, cy_n, r_n) < _STRUCTURE_MIN_LAP_MEANABS:
            # low_structure : désactivé en census (rejetait des pièces emballées à
            # surface uniforme = une grosse part des zéro-crop).
            accepted = False
            reason = "low_structure"

        detections.append(CircleDetection(
            cx=cx_n, cy=cy_n, r=r_n,
            method=method, votes=conf,
            accepted=accepted, reject_reason=reason,
        ))

    # Garde anti-doublon (post rim-refine) : évite que la même pièce, détectée
    # via 2 bboxes YOLO distinctes mais raffinées sur le même listel, génère N
    # crops identiques (même phash) au scrape — la dégénérescence « 3× la même
    # pièce » observée en review lot. Marque les doublons rejetés (debug-visible,
    # exclus des crops). Toujours actif (géométrique, aucun coût modèle).
    _dedup_duplicate_circles(detections, short)

    return detections


def normalize_listing(bgr: np.ndarray,
                       config: CropConfig | None = None,
                       census: bool | None = None) -> list[NormalizationResult]:
    """Normalize a listing image (eBay etc.) into 0..N tight coin crops.

    One result per **accepted** circle from `detect_circles_multi`. Order
    matches the detection order (Hough vote descending). Returns ``[]``
    when no coin is detected — the caller decides how to handle that
    (currently `detect_crop.py` flags it as an error, leaves the
    source_image at `'downloaded'` for re-processing).

    `config` permet l'ablation format (margin, edge_mode, output_size).
    `census` : voir `detect_circles_multi`. `None` = flag d'env ; un bool explicite
    a priorité (pipeline eBay = `census=True`). Active aussi le gate anti-fragment.
    """
    return normalize_listing_with_detections(bgr, config=config, census=census)[0]


def normalize_listing_with_detections(
    bgr: np.ndarray,
    config: CropConfig | None = None,
    census: bool | None = None,
) -> tuple[list[NormalizationResult], list[CircleDetection]]:
    """Comme `normalize_listing`, mais renvoie aussi la liste BRUTE des
    détections (`detect_circles_multi` — acceptés ET rejetés).

    Le caller (``detect_crop``) persiste cette liste dans
    ``source_images.detections_json`` pour que la review lot affiche
    l'Examination plate sans recompute live. Les crops renvoyés (1er
    élément) restent ceux post-gate anti-fragment ; les détections (2e)
    sont le constat complet avant gate — c'est le débug que l'humain veut
    voir (cercles écartés inclus).
    """
    if bgr is None or bgr.size == 0:
        return [], []
    use_census = _census_detect_enabled() if census is None else census
    detections = detect_circles_multi(bgr, census=use_census)
    results: list[NormalizationResult] = []
    result_src: list[int] = []  # index dans `detections` ayant produit chaque crop
    for idx, det in enumerate(detections):
        if not det.accepted:
            continue
        result = _crop_mask_resize_int(bgr, det.cx, det.cy, det.r,
                                        method=det.method, config=config)
        if result.image is None:
            continue
        results.append(result)
        result_src.append(idx)

    # Gate anti-fragment (census uniquement) : la probe DINO note chaque crop final ;
    # on jette ceux sous τ (fragments tranche/lettrage/anneau/partiel/capsule). Batch
    # unique. Hors census ou τ≤0 : aucun appel modèle, comportement inchangé.
    #
    # Les détections gatées sont re-marquées `accepted=False`
    # (reject_reason="gated_fragment") pour que `detections` (persisté dans
    # source_images.detections_json) reste un constat FIDÈLE : sinon l'overlay
    # affiche N "retenus" alors que seuls les crops post-gate existent réellement
    # → mismatch overlay ↔ bande de crops, et mapping accepté→crop_index par
    # ordre faussé (badges sur capsules vides). Cf. review_queue_routes.
    if use_census:
        tau = _census_fragment_tau()
        if tau > 0 and results:
            from vision.census import face_scores
            scores = face_scores([r.image for r in results])
            kept: list[NormalizationResult] = []
            for result, src_idx, score in zip(results, result_src, scores):
                if score >= tau:
                    kept.append(result)
                else:
                    det = detections[src_idx]
                    det.accepted = False
                    det.reject_reason = "gated_fragment"
            results = kept
    return results, detections


def normalize_listing_path(path: Path,
                            config: CropConfig | None = None,
                            census: bool | None = None) -> list[NormalizationResult]:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return normalize_listing(bgr, config=config, census=census)


def normalize_listing_path_with_detections(
    path: Path,
    config: CropConfig | None = None,
    census: bool | None = None,
) -> tuple[list[NormalizationResult], list[CircleDetection]]:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return normalize_listing_with_detections(bgr, config=config, census=census)


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
