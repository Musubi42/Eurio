"""Stratégies de RÉFÉRENCE (smoke) pour valider le harness et amorcer le front.

⚠️ NE PAS confondre avec les vraies stratégies A/B : celles-ci vivent dans
`docs/work-in-progress/crop-recovery/strategy-*/` et sont écrites par les sessions
dédiées. Ici = un baseline (iface.py) + un balayage de rayon naïf, juste pour prouver
que le banc discrimine (lift attendu sur D2) et alimenter le front d'exemple.
"""

from __future__ import annotations

import numpy as np

from .iface import Candidate, register

_SWEEP_MULT = [1.0, 1.4, 1.8, 2.2, 2.6, 3.0]


@register("ref:radius_sweep")
def ref_radius_sweep(raw_bgr: np.ndarray, hint: dict) -> list[Candidate]:
    """Référence A naïve : candidats à rayons croissants autour du hint, centre clampé
    pour tenir dans l'image. Le harness les score et garde l'argmax. Pas de calage —
    c'est le rôle de la session A d'optimiser range/granularité/recentrage/gardes."""
    H, W = raw_bgr.shape[:2]
    cx, cy, r0 = hint["cx"], hint["cy"], hint["r_final"]
    rcap = 0.48 * min(H, W)
    out: list[Candidate] = []
    seen: set[int] = set()
    for m in _SWEEP_MULT:
        r = min(r0 * m, rcap)
        rk = int(r)
        if rk in seen or rk < 4:
            continue
        seen.add(rk)
        ccx = float(np.clip(cx, r, W - r))
        ccy = float(np.clip(cy, r, H - r))
        out.append(Candidate(ccx, ccy, r, f"ref:sweep:x{m}"))
    return out or [Candidate(cx, cy, r0, "ref:sweep:x1")]
