"""Stratégie A — crop guidé par le score (probe-as-oracle).

Idée : sur les bimétal à gros motif central, la détection prod se rabat sur le DISQUE
INTERNE ; la pièce entière ≈ 2,2–2,6× le rayon détecté. Le score de la probe GELÉE monte
quand on agrandit le crop jusqu'à capter la pièce entière, puis redescend si on déborde sur
le fond. Donc le score EST le signal « sous-croppé » → on cherche le crop qui le maximise,
autour de la détection.

`recrop()` fait une recherche **coarse-to-fine** guidée par la probe gelée (lecture via
`common.score_crops`, autorisée pour la recherche interne — cf. SESSION-PROMPT) puis retourne
**tous** les candidats évalués. Le harness re-crope+re-score chaque candidat et garde
l'argmax (cf. BENCHMARK §2) — on ne décide donc pas du résultat final, on propose un nuage
dont le meilleur est l'optimum trouvé. Tous les candidats sont loggés (réutilisable pour
l'évaluation hybride offline).

Deux étages actifs :
  ① ladder de rayon au centre du hint (×mult sur r_final ∪ fractions absolues du short) ;
  ③ rayon fin autour du meilleur rayon → resserre l'IoU.
L'étage ② (recentrage par jitter) a été abandonné : il cassait la garde D3b (cf. corps).
"""

from __future__ import annotations

import numpy as np

from .common import crop_candidate, score_crops
from .iface import Candidate, register

# Multiplicateurs de rayon autour de r_final (le disque interne détecté). Dense dans la zone
# où vit la pièce entière (≈ ×1,8–2,8, diagnostic VISION §1), large vers le haut.
_RADIUS_MULT = [1.0, 1.3, 1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.5, 4.0]

# Rayons en valeur ABSOLUE (fraction du petit côté). Filet de sécurité quand r_final est une
# détection parasite minuscule (~5% du short) : l'ancrage ×mult ne peut alors pas atteindre la
# pièce entière. Ces candidats couvrent l'échelle pièce indépendamment de r_final.
_RADIUS_ABS_FRAC = [0.12, 0.18, 0.24, 0.30, 0.36, 0.42]

# Rayon fin (multiplicateurs autour du meilleur rayon) étage ③.
_RADIUS_FINE = [0.85, 0.92, 0.96, 1.0, 1.04, 1.08, 1.15]

# Borne dure : un candidat ne peut pas dépasser cette fraction du petit côté de l'image
# (anti sur-crop sur le fond ; affiné en A3).
_RCAP_FRAC = 0.48


def _clamp_center(cx: float, cy: float, r: float, W: int, H: int) -> tuple[float, float]:
    """Recentre pour que le disque tienne dans l'image."""
    return float(np.clip(cx, r, W - r)), float(np.clip(cy, r, H - r))


def _score_batch(raw_bgr, specs: list[tuple[float, float, float, str]]) -> list[Candidate]:
    """Crope+score chaque (cx, cy, r, tag) avec la probe gelée. Retourne les Candidate
    scorés (debug['iscore']) ; saute ceux dont le crop échoue."""
    imgs, kept = [], []
    for cx, cy, r, tag in specs:
        im = crop_candidate(raw_bgr, cx, cy, r)
        if im is not None:
            imgs.append(im)
            kept.append((cx, cy, r, tag))
    scores = score_crops(imgs) if imgs else []
    out: list[Candidate] = []
    for (cx, cy, r, tag), s in zip(kept, scores):
        out.append(Candidate(cx, cy, r, tag, debug={"iscore": float(s)}))
    return out


@register("A:score_search")
def recrop(raw_bgr: np.ndarray, hint: dict) -> list[Candidate]:
    """hint = {cx, cy, r_final, r_bbox, short}. Retourne les candidats évalués (coords
    natives) ; le harness garde l'argmax du score."""
    H, W = raw_bgr.shape[:2]
    short = min(H, W)
    cx, cy, r0 = hint["cx"], hint["cy"], hint["r_final"]
    rcap = _RCAP_FRAC * short

    all_cands: list[Candidate] = []

    # ① ladder de rayon au centre du hint ----------------------------------------
    radii: list[tuple[float, str]] = []
    for m in _RADIUS_MULT:
        radii.append((r0 * m, f"A:r{m:g}"))
    for f in _RADIUS_ABS_FRAC:
        radii.append((f * short, f"A:abs{f:g}"))
    specs, seen = [], set()
    for r, tag in radii:
        r = min(r, rcap)
        rk = int(round(r))
        if rk < 4 or rk in seen:
            continue
        seen.add(rk)
        ccx, ccy = _clamp_center(cx, cy, r, W, H)
        specs.append((ccx, ccy, r, tag))
    stage1 = _score_batch(raw_bgr, specs)
    all_cands += stage1
    if not stage1:
        return [Candidate(*_clamp_center(cx, cy, r0, W, H), r0, "A:r1")]

    best = max(stage1, key=lambda c: c.debug["iscore"])
    br = best.r
    bcx, bcy = best.cx, best.cy

    # ② recentrage par jitter de centre : ABANDONNÉ. Mesuré (2026-06-15) : +0,06 IoU D1
    # mais +3 pts de faux-accept D3b (5% > garde 2%) — le jitter aveugle fabrique des
    # faux-positifs probe sur les fragments. Le recentrage fiable est le rôle de la
    # stratégie B (géométrie). On garde donc le centre du hint.

    # ③ rayon fin autour du meilleur (centre, rayon) -----------------------------
    fine_specs, seenf = [], set()
    for m in _RADIUS_FINE:
        r = min(br * m, rcap)
        rk = int(round(r))
        if rk < 4 or rk in seenf:
            continue
        seenf.add(rk)
        ccx, ccy = _clamp_center(bcx, bcy, r, W, H)
        fine_specs.append((ccx, ccy, r, "A:fine"))
    all_cands += _score_batch(raw_bgr, fine_specs)

    return all_cands
