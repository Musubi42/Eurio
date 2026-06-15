"""Stratégie B — détection GÉOMÉTRIQUE du rebord externe (bimétal-aware, zéro modèle).

Diagnostic B0 (mesuré 2026-06-15 sur D2 EMU/globe, cf. RESULTS.md) : la détection prod
se rabat sur le **motif central** (globe / carte), pas sur le disque interne — la pièce
entière fait **≈ 3,0× r_hint** (médiane oracle = rayon qui maximise la probe). Le
`detect_bbox_refine` de prod échoue ici pour deux raisons cumulées : (1) son plafond
`_REFINE_R_CEIL = 2,6× r_hint` est **sous** le vrai rebord (3×) → il ne PEUT pas le rendre ;
(2) sa sélection se cale sur le **joint bimétal** (anneau argent↔or, ~1,77× r_hint, très
contrasté), pas sur le rebord externe argent↔fond (peu contrasté).

B n'appelle **jamais la probe** (c'est l'intérêt : la même géométrie tourne on-device dans
`SnapNormalizer.kt`). Le harness score et choisit ; B ne fait que **proposer** des cercles.

Deux pistes géométriques complémentaires, retournées comme candidats (le harness garde
l'argmax-score ; pour l'évaluation hybride tous sont loggés) :

  ① **Silhouette métal/fond** (primaire) — Otsu dans une ROI large, plus grand contour
     circulaire concentrique au hint → rebord externe. **Recentre ET redimensionne** (le
     hint est décentré sur le motif). Gagnant au B0 (56% pass vs 50% pour un sweep centré).
  ② **Joint bimétal → rebord** (secours, bimétal only) — le cercle le plus contrasté centré
     dans la ROI = le joint argent/or (ρ≈0,70·R) ; on prédit R = r_joint / ρ. Robuste quand
     le fond ne contraste pas (silhouette noyée), inopérant sur monométal.

Fallback : si aucune piste ne donne de cercle franc, on ne retourne RIEN → le harness garde
le baseline (crop prod), donc **aucune dégradation** (le cas reste pour A / l'hybride).

Gardes (anti sur-crop fond, anti-fusion lots, cf. feedback_recrop_multicoin_guard) :
concentricité au hint, plancher `r ≥ 0,95·r_hint` (jamais pire), plafond
`r ≤ min(4,2·r_hint, 0,48·short)`, circularité (fill ≈ 1, axes ronds).
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.crop_detectors import _otsu_external_contours
from vision.normalize_snap import _downscale_to_working_res

from .iface import Candidate, register

# Joint bimétal : rayon disque / rayon pièce. 2€ = 18,0/25,75 = 0,699 ; 1€ = 16,5/23,25 =
# 0,710. On prend 0,70 (les deux denominations bimétal sont à ~0,70).
_RHO_JOINT = 0.70

# ROI autour du hint : demi-côté = K × r_hint. Le rebord vit à ~3× r_hint (B0) → il faut une
# fenêtre nettement plus large que `detect_bbox_refine` (2,6×) pour le contenir.
_ROI_K = 3.6

# Bornes de rayon (en multiples de r_hint) — le rebord externe est plus GRAND que le hint.
_R_FLOOR_MULT = 0.95   # plancher : jamais plus serré que le crop actuel
_R_CEIL_MULT = 4.5     # plafond : borne l'overcrop / la fusion de voisines (oracle ≈ 3,0×, p75 silhouette 4,2×)
_RCAP_FRAC = 0.49      # plafond absolu : fraction du petit côté de l'image

# Concentricité : le centre de l'ellipse candidate doit rester proche du centre du hint.
# Large car la silhouette RECENTRE (le hint est décalé sur le motif) — borné par la
# fraction du rayon candidat lui-même.
_CONCENTRIC_FRAC = 0.55

# Circularité = axis_ratio de l'ellipse ajustée (min/max des axes, 1,0 = cercle parfait).
# B0 (mesuré) : sur le rebord externe peu contrasté, Otsu rend souvent un ARC partiel — le
# fill (aire/ellipse) chute alors que le fit reste rond. On ne garde donc QUE l'axis_ratio
# (un arc de cercle reste rond) + la concentricité ; la probe (harness) filtre les fits
# instables. Le fill-vs-cercle-englobant testé d'abord tuait le rappel (76%→22%).
_AXIS_RATIO_MIN = 0.62  # min/max des axes de l'ellipse ajustée


def _clamp_center(cx: float, cy: float, r: float, W: int, H: int) -> tuple[float, float]:
    return float(np.clip(cx, r, W - r)), float(np.clip(cy, r, H - r))


def _mk(cx, cy, r, source: str, debug: dict) -> Candidate:
    """Construit un Candidate en coerçant tout en float Python natif (cv2/numpy renvoient
    des float32 que le json.dumps du harness refuse)."""
    return Candidate(float(cx), float(cy), float(r), source,
                     debug={k: (round(float(v), 4) if isinstance(v, (int, float, np.floating))
                                else v) for k, v in debug.items()})


def _roi(raw_bgr: np.ndarray, hint: dict):
    """ROI carrée ~_ROI_K×r_hint autour du hint, ramenée en working-res.
    Retourne (work, scale, x0, y0, roi_cx_w, roi_cy_w, r_hint_w) ou None."""
    H, W = raw_bgr.shape[:2]
    cx, cy, r0 = float(hint["cx"]), float(hint["cy"]), float(hint["r_final"])
    if r0 <= 0:
        return None
    half = _ROI_K * r0
    x0 = max(0, int(cx - half)); y0 = max(0, int(cy - half))
    x1 = min(W, int(cx + half)); y1 = min(H, int(cy + half))
    sub = raw_bgr[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    work, scale = _downscale_to_working_res(sub)
    return work, scale, x0, y0, (cx - x0) / scale, (cy - y0) / scale, r0 / scale


def _bounds(hint: dict, short: int) -> tuple[float, float]:
    r0 = float(hint["r_final"])
    return _R_FLOOR_MULT * r0, min(_R_CEIL_MULT * r0, _RCAP_FRAC * short)


def _silhouette_rim(raw_bgr: np.ndarray, hint: dict) -> Candidate | None:
    """① Silhouette métal/fond : plus grand contour circulaire concentrique au hint dans la
    ROI = rebord externe. Recentre (centroïde du contour) + redimensionne."""
    roi = _roi(raw_bgr, hint)
    if roi is None:
        return None
    work, scale, x0, y0, rcx_w, rcy_w, r0_w = roi
    H, W = raw_bgr.shape[:2]
    short = min(H, W)
    r_floor, r_ceil = _bounds(hint, short)

    best = None  # (r_native, cx_native, cy_native, fill_ellipse, axis_ratio)
    for c in _otsu_external_contours(work):
        if len(c) < 5:
            continue
        (ex, ey), (d1, d2), _ = cv2.fitEllipse(c)   # centre + axes du rebord (robuste aux arcs)
        major = max(d1, d2)
        if major <= 0:
            continue
        r_w = major / 2.0
        axis_ratio = min(d1, d2) / major
        if axis_ratio < _AXIS_RATIO_MIN:
            continue
        # concentricité au hint : le centre de l'ellipse (pas le centroïde — un arc partiel
        # ajuste quand même le bon cercle, mais son centroïde dérive vers l'arc).
        if (ex - rcx_w) ** 2 + (ey - rcy_w) ** 2 > (_CONCENTRIC_FRAC * r_w) ** 2:
            continue
        r_native = r_w * scale
        if r_native < r_floor or r_native > r_ceil:
            continue
        fill_e = cv2.contourArea(c) / (np.pi * (d1 / 2.0) * (d2 / 2.0) + 1e-6)
        if best is None or r_native > best[0]:
            best = (r_native, x0 + ex * scale, y0 + ey * scale, fill_e, axis_ratio)

    if best is None:
        return None
    r_native, cxn, cyn, fill_e, axis_ratio = best
    cxn, cyn = _clamp_center(cxn, cyn, r_native, W, H)
    return _mk(cxn, cyn, r_native, "B:silhouette",
               {"fill_ellipse": fill_e, "axis_ratio": axis_ratio,
                "ratio_hint": r_native / hint["r_final"]})


def _joint_rim(raw_bgr: np.ndarray, hint: dict) -> Candidate | None:
    """② Joint bimétal → rebord : cercle le plus contrasté centré dans la ROI = joint
    argent/or ; rebord externe prédit R = r_joint / ρ. Secours quand le fond ne contraste
    pas. Inopérant (et c'est voulu) sur monométal : aucun joint franc → pas de candidat."""
    roi = _roi(raw_bgr, hint)
    if roi is None:
        return None
    work, scale, x0, y0, rcx_w, rcy_w, r0_w = roi
    H, W = raw_bgr.shape[:2]
    short = min(H, W)
    r_floor, r_ceil = _bounds(hint, short)
    work_short = min(work.shape[:2])

    gray = cv2.medianBlur(cv2.cvtColor(work, cv2.COLOR_BGR2GRAY), 5)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.0, minDist=work_short,
        param1=100, param2=22,
        minRadius=int(r0_w * 0.8), maxRadius=int(work_short * 0.5),
    )
    if circles is None or len(circles[0]) == 0:
        return None
    tol_sq = (0.30 * work_short) ** 2
    centred = [c for c in circles[0]
               if (c[0] - rcx_w) ** 2 + (c[1] - rcy_w) ** 2 <= tol_sq]
    if not centred:
        return None
    # 1er rang Hough parmi les centrés = cercle au plus fort accumulateur = joint bimétal.
    jc = centred[0]
    r_native = (jc[2] * scale) / _RHO_JOINT
    if r_native < r_floor or r_native > r_ceil:
        return None
    cxn, cyn = _clamp_center(x0 + jc[0] * scale, y0 + jc[1] * scale, r_native, W, H)
    return _mk(cxn, cyn, r_native, "B:bimetal_joint",
               {"r_joint": float(jc[2] * scale), "ratio_hint": r_native / hint["r_final"]})


@register("B:bimetal_rim")
def recrop(raw_bgr: np.ndarray, hint: dict) -> list[Candidate]:
    """hint = {cx, cy, r_final, r_bbox, short}. Retourne 0..2 candidats géométriques de
    rebord externe (coords natives). Aucun appel à la probe. Fallback (rien trouvé) =
    liste vide → le harness garde le baseline (pas de dégradation)."""
    out: list[Candidate] = []
    sil = _silhouette_rim(raw_bgr, hint)
    if sil is not None:
        out.append(sil)
    jnt = _joint_rim(raw_bgr, hint)
    if jnt is not None:
        # évite un doublon quasi-identique à la silhouette (même cercle).
        if sil is None or abs(jnt.r - sil.r) > 0.08 * sil.r \
                or (jnt.cx - sil.cx) ** 2 + (jnt.cy - sil.cy) ** 2 > (0.08 * sil.r) ** 2:
            out.append(jnt)
    return out
