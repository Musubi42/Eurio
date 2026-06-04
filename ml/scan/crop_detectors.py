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



# ---------------------------------------------------------------------------
# Mesure de tilt (inclinaison de la pièce dans l'image)
# ---------------------------------------------------------------------------
# Stratégie retenue : Canny sur anneau [0.70·r, 1.15·r] + fitEllipseAMS.
# 92.5 % trustworthy sur 120 assets eBay, 0 aberration > 45° trustworthy,
# couverture angulaire en secteurs (remplace le ratio n_ring/périmètre qui
# était quasi-inopérant à seuil 0.85 dans le probe).
#
# Buckets d'affichage recommandés (sur tilt_deg trustworthy) :
#   round  : axis_ratio ≥ 0.97  → tilt physiquement indéterminable (<14°)
#   slight : tilt_deg < 10°     → quasi-face (peut passer en crop)
#   tilted : 10° ≤ tilt_deg < 30° → inclinaison notable (crop dégradé)
#   strong : tilt_deg ≥ 30°    → très incliné (crop fiable difficile)
#   Seuil trustworthy = True pour les 3 critères (center_drift, r_ratio, arc_cov).

_TILT_ROI_K         = 2.6     # même fenêtre que detect_bbox_refine
_TILT_RING_LO       = 0.70    # anneau interne : facteur × r_hint (working res)
_TILT_RING_HI       = 1.15    # anneau externe
_TILT_MIN_RING_PTS  = 50      # nombre minimum de points Canny dans l'anneau
_TILT_ARC_COV_MIN   = 0.60    # fraction de secteurs de 30° devant contenir ≥1 pt
_TILT_CENTER_FRAC   = 0.30    # distance max centre ellipse / r_hint
_TILT_R_RATIO_LO    = 0.70    # grand-axe / r_hint ∈ [LO, HI]
_TILT_R_RATIO_HI    = 1.40
_TILT_TRIVIAL       = 0.97    # axis_ratio ≥ seuil → quasi-cercle, angle indéterminé


def measure_tilt(bgr: np.ndarray, hint: dict) -> dict:
    """Mesure l'inclinaison d'une pièce par Canny + fitEllipseAMS sur l'anneau
    de bords autour du hint (même ROI que ``detect_bbox_refine``).

    Paramètres
    ----------
    bgr  : image raw BGR en résolution native.
    hint : {cx, cy, r} en pixels natifs (centre et rayon du crop bbox connu).

    Retour
    ------
    ok            : bool  — False si aucun fit utilisable
    axis_ratio    : float | None — minor/major (1.0 = cercle parfait)
    tilt_deg      : float | None — acos(axis_ratio) en degrés [0–90]
    angle         : float | None — angle OpenCV axe principal (0–180°)
    trustworthy   : bool  — True si center_drift, r_ratio et arc_coverage OK
    reason        : str | None — motif de rejet (ou None si trustworthy=True)
    cx, cy        : float | None — centre ellipse en coords natives
    major, minor  : float | None — demi-axes en pixels natifs
    debug         : dict  — métriques internes (arc_coverage, n_ring, r_ratio…)
    """
    import math as _math

    def _fail(reason: str) -> dict:
        return {
            "ok": False, "axis_ratio": None, "tilt_deg": None, "angle": None,
            "trustworthy": False, "reason": reason,
            "cx": None, "cy": None, "major": None, "minor": None,
            "debug": {},
        }

    if bgr is None or bgr.size == 0:
        return _fail("empty_input")

    hcx = float(hint.get("cx", 0))
    hcy = float(hint.get("cy", 0))
    hr  = float(hint.get("r", 0))
    if hr <= 0:
        return _fail("no_hint_r")

    H, W = bgr.shape[:2]

    # 1. ROI identique à detect_bbox_refine.
    half = _TILT_ROI_K * hr
    x0 = max(0, int(hcx - half));  y0 = max(0, int(hcy - half))
    x1 = min(W, int(hcx + half));  y1 = min(H, int(hcy + half))
    sub = bgr[y0:y1, x0:x1]
    if sub.size == 0:
        return _fail("empty_roi")

    # 2. Mise à l'échelle working-res (long-side ≤ 1024).
    work, scale = _downscale_to_working_res(sub)
    roi_cx_w = (hcx - x0) / scale
    roi_cy_w = (hcy - y0) / scale
    r_hint_w = hr / scale

    # 3. Canny adaptatif (seuils médiane ± 0.5×médiane).
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    median = float(np.median(gray))
    lo = max(0.0, median * 0.5)
    hi = min(255.0, median * 1.5)
    edges = cv2.Canny(gray, lo, hi)

    # 4. Filtrage anneau [ring_lo·r, ring_hi·r] autour du centre hint.
    ys, xs = np.nonzero(edges)
    if len(xs) == 0:
        return _fail("no_edges")

    dists = np.hypot(xs.astype(float) - roi_cx_w, ys.astype(float) - roi_cy_w)
    ring_mask = (dists >= _TILT_RING_LO * r_hint_w) & (dists <= _TILT_RING_HI * r_hint_w)
    ring_xs = xs[ring_mask].astype(np.float32)
    ring_ys = ys[ring_mask].astype(np.float32)
    n_ring = int(ring_mask.sum())

    if n_ring < _TILT_MIN_RING_PTS:
        return _fail("too_few_ring_pts")

    # 5. Couverture angulaire : fraction des secteurs de 30° (12 secteurs)
    #    contenant au moins un point Canny. Remplace n_ring/périmètre qui
    #    était quasi-inopérant dans le probe (82 % des cas > 2.0).
    angles_deg = np.degrees(
        np.arctan2(ring_ys - roi_cy_w, ring_xs - roi_cx_w)
    ) % 360.0
    n_sectors   = 12
    sector_size = 360.0 / n_sectors
    occupied    = len(set(int(a / sector_size) for a in angles_deg))
    arc_coverage = occupied / n_sectors  # fraction [0, 1]

    if arc_coverage < _TILT_ARC_COV_MIN:
        return _fail("incomplete_ring")

    # 6. fitEllipseAMS → fitEllipseDirect → fitEllipse (cascade défensive).
    pts = np.column_stack([ring_xs, ring_ys]).reshape(-1, 1, 2)
    ell = None
    for fn_name, fn in [
        ("ams",    lambda p: cv2.fitEllipseAMS(p)),
        ("direct", lambda p: cv2.fitEllipseDirect(p)),
        ("std",    lambda p: cv2.fitEllipse(p)),
    ]:
        try:
            ell = fn(pts)
            break
        except cv2.error:
            continue

    if ell is None:
        return _fail("fitellipse_failed")

    (ell_cx_w, ell_cy_w), (d1, d2), angle_ell = ell
    major_w = max(d1, d2) / 2.0
    minor_w = min(d1, d2) / 2.0
    if major_w <= 0:
        return _fail("degenerate_ellipse")

    # 7. Projection en pixels natifs.
    cx_n    = x0 + ell_cx_w * scale
    cy_n    = y0 + ell_cy_w * scale
    major_n = major_w * scale
    minor_n = minor_w * scale

    axis_ratio  = minor_w / major_w
    r_ratio     = major_n / hr
    center_dist = _math.hypot(cx_n - hcx, cy_n - hcy)
    center_frac = center_dist / hr

    # 8. Critères de confiance.
    reasons: list[str] = []
    if center_frac > _TILT_CENTER_FRAC:
        reasons.append(f"center_drift:{center_frac:.2f}")
    if not (_TILT_R_RATIO_LO <= r_ratio <= _TILT_R_RATIO_HI):
        reasons.append(f"r_ratio_out:{r_ratio:.2f}")
    if axis_ratio >= _TILT_TRIVIAL:
        # Quasi-cercle : l'angle est numériquement instable, tilt indéterminable.
        reasons.append(f"too_circular:{axis_ratio:.3f}")

    trustworthy = (len(reasons) == 0)
    tilt_deg    = _math.degrees(_math.acos(min(1.0, axis_ratio)))

    return {
        "ok":          True,
        "axis_ratio":  round(axis_ratio,   4),
        "tilt_deg":    round(tilt_deg,     2),
        "angle":       round(float(angle_ell), 2),
        "trustworthy": trustworthy,
        "reason":      "; ".join(reasons) if reasons else None,
        "cx":          round(cx_n,         1),
        "cy":          round(cy_n,         1),
        "major":       round(major_n,      1),
        "minor":       round(minor_n,      1),
        "debug": {
            "arc_coverage":  round(arc_coverage,  3),
            "n_ring":        n_ring,
            "r_ratio":       round(r_ratio,       3),
            "center_frac":   round(center_frac,   3),
        },
    }


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
