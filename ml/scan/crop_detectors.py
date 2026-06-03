"""Détecteurs de cercle pluggables pour le banc crop (chantier crop-quality-overhaul).

Chaque détecteur prend un raw BGR et renvoie un ``DetectorResult`` (cercle en
coords pixel NATIVES). Le banc les compare côte-à-côte ; le détecteur retenu
(décision Chunk 4, sur gold) graduera dans ``normalize_listing``.

Contrat « même résultat, technique libre » : tous les détecteurs produisent
leur crop final via le MÊME ``_crop_mask_resize_float`` de prod (marge 0.02,
masque dur, 224) — seule la DÉTECTION du (cx, cy, r) change. C'est ce qui rend
la comparaison honnête (apples-to-apples) et le portage Android tractable.

Détecteurs :
- ``fitellipse`` (Chunk 1) : contour Otsu externe + ``cv2.fitEllipse`` +
  sélecteur ``max(r)`` parmi les candidats centrés à ``fill ≥ 0.70``. Corrige
  l'undercrop bimétal sur fond UNI. Échoue sur fond texturé (no_ellipse) et
  overcroppe sur multi-objets (fusionne / prend la carte).
- ``adaptive`` (Chunk 2) : même base contour mais SÉLECTEUR PAR CIRCULARITÉ
  (``fill`` proche de 1.0 + axes ronds) → rejette les cartes/certificats
  rectangulaires (anti-overcrop) ; fallback Hough plein-cadre « largest
  centred » quand aucun contour circulaire (fond texturé). Sans dépendance,
  sans YOLO (bbox YOLO jugée peu fiable sur ce corpus).

L'insight circularité : ``fill = aire_contour / aire_ellipse_fit`` discrimine la
FORME — cercle ≈ 1.0, anneau/partiel < 0.8, rectangle (carte) > 1.1.

Chunks 3+ : ``edcircles`` (opencv-contrib, fonds texturés), ``fastsam``
(server-only). Ajouter = une fonction + une entrée dans ``DETECTORS``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

# Primitifs de PROD réutilisés (même format de crop → comparaison honnête).
from scan.normalize_snap import (
    CropConfig,
    NormalizationResult,
    _STUDIO_AREA_RATIO_MAX,
    _STUDIO_CENTER_TOL_FRAC,
    _STUDIO_FILL_RATIO_MIN,
    _crop_mask_resize_float,
    _downscale_to_working_res,
)

# Rayon minimal d'une vraie pièce, en fraction du petit côté (working res).
_RMIN_FRAC = 0.06

# Fenêtre de circularité (fill = aire_contour / aire_ellipse) pour « ressemble
# à une pièce » : cercle ≈ 1.0. En-dessous = anneau/partiel ; au-dessus = forme
# anguleuse (carte/certificat rectangulaire).
_CIRC_FILL_MIN = 0.80
_CIRC_FILL_MAX = 1.12
_CIRC_AXIS_RATIO_MIN = 0.55   # min/max des axes de l'ellipse (1.0 = cercle parfait)

# Hough plein-cadre (fallback fond texturé) — large, comme le device path.
_HOUGH_RMIN_FRAC = 0.15
_HOUGH_RMAX_FRAC = 0.55
_HOUGH_CENTER_TOL_FRAC = 0.30


@dataclass
class DetectorResult:
    """Cercle détecté en coords pixel NATIVES (sur le raw d'origine)."""
    ok: bool
    cx: float = 0.0
    cy: float = 0.0
    r: float = 0.0
    method: str = ""
    reason: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)


def _otsu_external_contours(work: np.ndarray) -> list[np.ndarray]:
    """Binarisation Otsu (polarité par les coins) + morpho + contours externes.

    Même préparation que ``normalize_snap._detect_circle_contour``.
    """
    h, w = work.shape[:2]
    short = min(h, w)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    corners = np.array([gray[0, 0], gray[0, -1], gray[-1, 0], gray[-1, -1]])
    otsu_thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    flag = cv2.THRESH_BINARY_INV if corners.mean() > otsu_thr else cv2.THRESH_BINARY
    _, mask = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)

    k = max(3, short // 200) | 1
    kernel = np.ones((k, k), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return list(contours)


def _ellipse_candidates(work: np.ndarray, center_tol_frac: float,
                        rmin_frac: float) -> list[dict]:
    """Liste des candidats-ellipses centrés/non-débordants, en coords `work`.

    Chaque candidat : {cx, cy, r (semi-grand axe), fill, axis_ratio, area}.
    """
    h, w = work.shape[:2]
    short = min(h, w)
    img_area = float(h * w)
    img_cx, img_cy = w / 2.0, h / 2.0
    tol_sq = (center_tol_frac * short) ** 2
    rmin = rmin_frac * short

    out: list[dict] = []
    for c in _otsu_external_contours(work):
        if len(c) < 5:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        ccx, ccy = M["m10"] / M["m00"], M["m01"] / M["m00"]
        if (ccx - img_cx) ** 2 + (ccy - img_cy) ** 2 > tol_sq:
            continue
        area = cv2.contourArea(c)
        if area / img_area > _STUDIO_AREA_RATIO_MAX:
            continue
        (ex, ey), (d1, d2), _ = cv2.fitEllipse(c)
        r = max(d1, d2) / 2.0
        if r < rmin:
            continue
        ell_area = np.pi * (d1 / 2.0) * (d2 / 2.0)
        fill = area / max(1.0, ell_area)
        out.append({
            "cx": ex, "cy": ey, "r": r, "fill": fill, "area": area,
            "axis_ratio": (min(d1, d2) / max(d1, d2)) if max(d1, d2) else 0.0,
        })
    return out


def _hough_largest_centred(work: np.ndarray, rmin_frac: float = _HOUGH_RMIN_FRAC,
                           rmax_frac: float = _HOUGH_RMAX_FRAC,
                           center_tol_frac: float = _HOUGH_CENTER_TOL_FRAC) -> dict | None:
    """Hough, plus grand cercle centré (rim externe sur bimétal). Coords `work`.
    Pas de polish (le polish tire vers l'anneau interne)."""
    h, w = work.shape[:2]
    short = min(h, w)
    gray = cv2.medianBlur(cv2.cvtColor(work, cv2.COLOR_BGR2GRAY), 5)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.0, minDist=short,
        param1=100, param2=24,
        minRadius=int(short * rmin_frac),
        maxRadius=int(short * rmax_frac),
    )
    if circles is None or len(circles[0]) == 0:
        return None
    img_cx, img_cy = w / 2.0, h / 2.0
    tol_sq = (center_tol_frac * short) ** 2
    centred = [c for c in circles[0]
               if (c[0] - img_cx) ** 2 + (c[1] - img_cy) ** 2 <= tol_sq]
    pool = centred if centred else list(circles[0])
    best = max(pool, key=lambda c: c[2])
    return {"cx": float(best[0]), "cy": float(best[1]), "r": float(best[2])}


# detect_bbox_refine : facteurs de la ROI autour du centre de la bbox connue.
_REFINE_ROI_K = 2.6        # demi-côté ROI = K × r_hint (couvre le rim externe même si hint = anneau interne)
_REFINE_R_FLOOR = 0.90     # plancher : r_final ≥ floor × r_hint (jamais PIRE que l'actuel)
_REFINE_R_CEIL = 2.6       # plafond : r_final ≤ ceil × r_hint (borne l'overcrop)


def detect_bbox_refine(bgr: np.ndarray, hint: dict | None = None) -> DetectorResult:
    """Raffine le rim externe DANS une ROI autour du centre de la bbox connue.

    `hint` = {cx, cy, r} en pixels natifs (centre + rayon du crop actuel /
    bbox stockée). Garde la localisation (pas d'overcrop sur sets/lots) tout
    en cherchant le rim externe (corrige l'anneau interne bimétal).
    Plancher r ≥ 0.9×r_hint (jamais pire), plafond r ≤ 2.6×r_hint (borné).
    """
    if not hint or not hint.get("r"):
        return DetectorResult(False, reason="no_hint")
    H, W = bgr.shape[:2]
    hcx, hcy, hr = float(hint["cx"]), float(hint["cy"]), float(hint["r"])
    half = _REFINE_ROI_K * hr
    x0 = max(0, int(hcx - half)); y0 = max(0, int(hcy - half))
    x1 = min(W, int(hcx + half)); y1 = min(H, int(hcy + half))
    sub = bgr[y0:y1, x0:x1]
    if sub.size == 0:
        return DetectorResult(False, reason="empty_roi")

    work, scale = _downscale_to_working_res(sub)
    roi_cx_w, roi_cy_w = (hcx - x0) / scale, (hcy - y0) / scale  # centre hint en coords work
    short = min(work.shape[:2])
    tol_sq = (0.35 * short) ** 2

    def _accept(cx_w, cy_w, r_w, method, extra):
        cx_n = x0 + cx_w * scale
        cy_n = y0 + cy_w * scale
        r_n = max(r_w * scale, _REFINE_R_FLOOR * hr)   # plancher : jamais pire que l'actuel
        if r_n > _REFINE_R_CEIL * hr:
            return None                                 # overcrop (capsule/objet) → rejeter
        return DetectorResult(ok=True, cx=cx_n, cy=cy_n, r=r_n, method=method,
                              reason=None, debug={**extra, "scale": float(scale)})

    # 1. Contour-fitEllipse dans la ROI : candidat circulaire concentrique au hint,
    #    le plus grand (= rim externe). Otsu accroche le MÉTAL → ignore nativement
    #    une capsule plastique transparente (latch sur la pièce, pas l'écrin).
    circ = []
    for c in _ellipse_candidates(work, center_tol_frac=10.0, rmin_frac=0.05):
        if (c["cx"] - roi_cx_w) ** 2 + (c["cy"] - roi_cy_w) ** 2 > tol_sq:
            continue
        if _CIRC_FILL_MIN <= c["fill"] <= _CIRC_FILL_MAX and c["axis_ratio"] >= _CIRC_AXIS_RATIO_MIN:
            circ.append(c)
    if circ:
        best = max(circ, key=lambda c: c["r"])
        res = _accept(best["cx"], best["cy"], best["r"], "bbox_refine:contour",
                      {"fill_ratio": round(best["fill"], 4), "axis_ratio": round(best["axis_ratio"], 3)})
        if res is not None:
            return res

    # 2. Hough dans la ROI (rim externe = plus grand cercle concentrique au hint).
    hgh = _hough_largest_centred(work, rmin_frac=0.18, rmax_frac=0.50, center_tol_frac=0.30)
    if hgh is not None and (hgh["cx"] - roi_cx_w) ** 2 + (hgh["cy"] - roi_cy_w) ** 2 <= tol_sq:
        res = _accept(hgh["cx"], hgh["cy"], hgh["r"], "bbox_refine:hough", {})
        if res is not None:
            return res

    # 3. Dernier recours : on garde le hint (= crop actuel, aucune dégradation).
    return DetectorResult(ok=True, cx=hcx, cy=hcy, r=hr, method="bbox_refine:hint_kept",
                          reason="no_better_rim", debug={"scale": float(scale)})


def detect_fitellipse(bgr: np.ndarray) -> DetectorResult:
    """Chunk 1 : contour Otsu + fitEllipse, sélecteur ``max(r) | fill≥0.70``."""
    work, scale = _downscale_to_working_res(bgr)
    cands = _ellipse_candidates(work, _STUDIO_CENTER_TOL_FRAC, _RMIN_FRAC)
    if not cands:
        return DetectorResult(False, reason="no_ellipse")
    valid = [c for c in cands if c["fill"] >= _STUDIO_FILL_RATIO_MIN]
    degraded = not valid
    best = max(cands if degraded else valid, key=lambda c: c["r"])
    return DetectorResult(
        ok=True, cx=best["cx"] * scale, cy=best["cy"] * scale, r=best["r"] * scale,
        method="fitellipse", reason="low_fill_degraded" if degraded else None,
        debug={"fill_ratio": round(best["fill"], 4),
               "axis_ratio": round(best["axis_ratio"], 3),
               "n_candidates": len(cands), "scale": float(scale)},
    )


def detect_adaptive(bgr: np.ndarray) -> DetectorResult:
    """Chunk 2 : sélecteur par circularité (anti-carte) + fallback Hough texturé."""
    work, scale = _downscale_to_working_res(bgr)
    cands = _ellipse_candidates(work, _STUDIO_CENTER_TOL_FRAC, _RMIN_FRAC)

    # Candidats « pièce » = circulaires (fill proche de 1.0, axes ronds).
    circular = [
        c for c in cands
        if _CIRC_FILL_MIN <= c["fill"] <= _CIRC_FILL_MAX
        and c["axis_ratio"] >= _CIRC_AXIS_RATIO_MIN
    ]
    if circular:
        best = max(circular, key=lambda c: c["r"])  # rim externe = le plus grand cercle propre
        return DetectorResult(
            ok=True, cx=best["cx"] * scale, cy=best["cy"] * scale, r=best["r"] * scale,
            method="adaptive:contour", reason=None,
            debug={"fill_ratio": round(best["fill"], 4),
                   "axis_ratio": round(best["axis_ratio"], 3),
                   "n_candidates": len(cands), "n_circular": len(circular),
                   "scale": float(scale)},
        )

    # Pas de contour circulaire (fond texturé / Otsu noyé) → Hough plein-cadre.
    h = _hough_largest_centred(work)
    if h is not None:
        return DetectorResult(
            ok=True, cx=h["cx"] * scale, cy=h["cy"] * scale, r=h["r"] * scale,
            method="adaptive:hough", reason="contour_failed_hough_fallback",
            debug={"n_candidates": len(cands), "scale": float(scale)},
        )

    # Dernier recours : le plus grand contour non-circulaire (mieux que rien).
    if cands:
        best = max(cands, key=lambda c: c["r"])
        return DetectorResult(
            ok=True, cx=best["cx"] * scale, cy=best["cy"] * scale, r=best["r"] * scale,
            method="adaptive:contour_degraded", reason="no_circular_no_hough",
            debug={"fill_ratio": round(best["fill"], 4),
                   "axis_ratio": round(best["axis_ratio"], 3), "scale": float(scale)},
        )
    return DetectorResult(False, reason="no_detection")


# Registre des détecteurs. Clé = nom d'algo exposé par l'API du banc.
# `fitellipse`/`adaptive` = plein cadre (pas de hint). `bbox_refine` = raffine
# autour du centre de la bbox connue (nécessite `hint`).
DETECTORS: dict[str, Callable[..., DetectorResult]] = {
    "fitellipse": detect_fitellipse,
    "adaptive": detect_adaptive,
    "bbox_refine": detect_bbox_refine,
}

# Détecteurs qui requièrent un hint {cx, cy, r} (centre/rayon du crop actuel).
_HINTED = {"bbox_refine"}


def run_detector(algo: str, bgr: np.ndarray, hint: dict | None = None) -> DetectorResult:
    fn = DETECTORS.get(algo)
    if fn is None:
        return DetectorResult(False, reason=f"unknown_algo:{algo}")
    if bgr is None or bgr.size == 0:
        return DetectorResult(False, reason="empty_input")
    if algo in _HINTED:
        return fn(bgr, hint)
    return fn(bgr)


def crop_with_detector(
    algo: str, bgr: np.ndarray, config: CropConfig | None = None,
    hint: dict | None = None,
) -> tuple[NormalizationResult | None, DetectorResult]:
    """Détecte puis crop avec le MÊME format que la prod (``_crop_mask_resize_float``)."""
    det = run_detector(algo, bgr, hint=hint)
    if not det.ok:
        return None, det
    res = _crop_mask_resize_float(bgr, det.cx, det.cy, det.r, method=det.method, config=config)
    return res, det
