"""Gate dénomination — signal *bimétal géométrique* (zéro-training).

Problème (C7 pilier 2, cf. docs/model-efficiency/HANDOFF-C7.md) : les crops de
**photos de lots** ramènent des pièces qui ne sont pas des 2€ (1/2/5 ct cuivre,
10/20/50 ct nordic gold). La similarité DINO aux ancres avers ne les sépare pas
(les non-2€ usés chevauchent les avers 2€). Il faut un **signal physique 2€-ness**.

Fait physique exploité : **1€ et 2€ sont bimétal** (anneau d'un métal + disque
central d'un autre → contraste de couleur radial net), alors que 1/2/5 ct
(cuivre) et 10/20/50 ct (nordic gold) sont **monométal** (couleur uniforme).

- 2€ : anneau cupronickel (argenté, chroma ~neutre) + centre nickel-laiton (doré).
- 1€ : inverse (anneau doré + centre argenté).
- monométal : disque et anneau de **même** couleur → contraste radial ~0.

`bimetal_score` mesure la distance, dans le plan chroma (a*, b* de CIELAB), entre
la couleur médiane du **disque interne** et celle de l'**anneau externe**. Le
canal L* (luminosité) est ignoré → robuste aux gradients d'éclairage. Score élevé
= bimétal (1€/2€) ; score ~0 = monométal (non-2€).

⚠️ 1€ est aussi bimétal donc non séparé par ce seul signal — mais hors scope des
recherches 2€, et discriminable en aval par taille relative / couleur d'anneau
(anneau argenté pour 2€, doré pour 1€ : voir `ring_is_silver`).

Convention : entrée **BGR** (cv2), comme le reste de `ml/vision/`. Le crop est
supposé ~centré, pièce remplissant le cadre (sortie du détecteur de crop, 224²).
"""

from __future__ import annotations

import cv2
import numpy as np

# Géométrie radiale normalisée (ρ = r / R_outer). Le joint bimétal d'un vrai 2€
# est à ρ≈0.70 (disque 18 mm / pièce 25.75 mm) ; on échantillonne bien à
# l'intérieur de chaque métal et on exclut le joint (transition) et le rim.
_RHO_INNER_MAX = 0.52   # disque central : ρ < 0.52
_RHO_RING_LO = 0.74     # anneau externe : 0.74 < ρ < 0.94
_RHO_RING_HI = 0.94
_R_OUTER_FRAC = 0.47    # rayon pièce ≈ 0.47 · côté (crop serré normalisé)

_MIN_REGION_PX = 80     # min pixels par région pour une médiane fiable


def _region_masks(side: int) -> tuple[np.ndarray, np.ndarray]:
    """Masques (disque interne, anneau externe) pour un crop carré `side`²."""
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    cx = cy = (side - 1) / 2.0
    r_outer = _R_OUTER_FRAC * side
    rho = np.hypot(xx - cx, yy - cy) / r_outer
    inner = rho < _RHO_INNER_MAX
    ring = (rho > _RHO_RING_LO) & (rho < _RHO_RING_HI)
    return inner, ring


def bimetal_score(bgr: np.ndarray) -> dict:
    """Score de bimétal d'un crop pièce (BGR).

    Retour
    ------
    ok       : bool — False si crop vide / régions trop petites
    score    : float — distance chroma (a*,b*) anneau↔disque (0 = monométal)
    delta_a  : float — a* anneau − a* disque (8-bit LAB)
    delta_b  : float — b* anneau − b* disque (b* = jaune↑/bleu↓ → or vs argent)
    inner_chroma, ring_chroma : float — chroma médiane (hypot(a-128,b-128)) /région
    reason   : str | None — motif si ok=False
    """
    if bgr is None or bgr.size == 0:
        return {"ok": False, "score": 0.0, "reason": "empty_input"}

    # Carré : on recadre au plus petit côté centré si non carré.
    h, w = bgr.shape[:2]
    side = min(h, w)
    if h != w:
        y0 = (h - side) // 2
        x0 = (w - side) // 2
        bgr = bgr[y0:y0 + side, x0:x0 + side]

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    a = lab[:, :, 1].astype(np.float32)
    b = lab[:, :, 2].astype(np.float32)

    inner, ring = _region_masks(side)
    if int(inner.sum()) < _MIN_REGION_PX or int(ring.sum()) < _MIN_REGION_PX:
        return {"ok": False, "score": 0.0, "reason": "region_too_small"}

    ia, ib = float(np.median(a[inner])), float(np.median(b[inner]))
    ra, rb = float(np.median(a[ring])), float(np.median(b[ring]))
    da, db = ra - ia, rb - ib
    score = float(np.hypot(da, db))

    return {
        "ok": True,
        "score": score,
        "delta_a": da,
        "delta_b": db,
        "inner_chroma": float(np.hypot(ia - 128.0, ib - 128.0)),
        "ring_chroma": float(np.hypot(ra - 128.0, rb - 128.0)),
        "inner_ab": (ia, ib),
        "ring_ab": (ra, rb),
        "reason": None,
    }


def ring_is_silver(res: dict) -> bool:
    """Vrai si l'anneau externe est ~argenté (chroma faible) et le disque doré.

    Distingue 2€ (anneau argent + centre or) de 1€ (anneau or + centre argent),
    une fois `bimetal_score` confirmé bimétal. Heuristique, à calibrer au bench.
    """
    if not res.get("ok"):
        return False
    return res["ring_chroma"] < res["inner_chroma"] and res["delta_b"] < 0.0
