"""Récupération de crop guidée par le score (stratégie A, validée au banc crop-recovery).

Quand la détection census (`detect_circles_multi` + gate anti-fragment) ne rend AUCUN crop
sur une image eBay — typiquement les bimétal à gros motif central où la détection accroche le
motif et le crop sous-croppé est jeté par le gate (`crop_status='zero_crops'`) — cette passe
de SECOURS repart de la détection dominante et cherche, par balayage de rayon scoré par la
probe gelée, le crop pièce-entière qui maximise le score. Si le meilleur passe le gate (≥ τ),
on le rend ; sinon rien (l'image reste zero_crops, pas de dégradation).

Mesuré au banc (`docs/work-in-progress/crop-recovery/`) : récupère **86 %** des zero_crops
EMU/globe (baseline 0 %), IoU D1 0,87. Coût = K appels probe / image → réservé au mode
census serveur (offline enrichment), jamais au scan device.

OFF par défaut en prod (R0) : activé par `EURIO_CENSUS_RECOVER=1`, lu par
`normalize_listing_with_detections`. Ce module ne décide pas de l'activation — il fournit la
fonction pure `recover_crop`.
"""

from __future__ import annotations

import numpy as np

# Multiplicateurs de rayon autour de r_hint (la détection dominante = souvent le motif
# central). Dense où vit la pièce entière (~2–3× r_hint), large vers le haut pour les cas où
# r_hint est un éclat minuscule (la pièce peut être à 6×+). Cf. strategy_a + findings r_hint.
_RADIUS_MULT = [1.0, 1.3, 1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.5, 4.0, 5.0, 6.0]
# Rayons en fraction ABSOLUE du petit côté — filet quand r_hint est un éclat (l'ancrage
# ×mult ne peut pas atteindre la pièce). Couvre l'échelle pièce indépendamment de r_hint.
_RADIUS_ABS_FRAC = [0.12, 0.18, 0.24, 0.30, 0.36, 0.42]
# Affinage autour du meilleur rayon (resserre).
_RADIUS_FINE = [0.85, 0.92, 0.96, 1.0, 1.04, 1.08, 1.15]
_RCAP_FRAC = 0.48  # un candidat ne dépasse pas cette fraction du petit côté (anti sur-crop fond)
# Balayage du CENTRE (offsets en fraction de r0) — optionnel, pour les crops
# DÉCALÉS que le balayage de rayon (centre fixe) ne peut pas rattraper. Mesuré au
# banc probe sur les 10 crops les plus partiels : +0,03 à +0,10 de score vs
# rayon-seul sur ~6/10 (gain nul sur les autres → garde le centre). Coût = grille
# de probes en plus → réservé à l'auto-crop interactif (sweep_center=True).
_CENTER_OFFSETS_FRAC = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]


def _clamp_center(cx, cy, r, W, H):
    return float(np.clip(cx, r, W - r)), float(np.clip(cy, r, H - r))


def _score_specs(bgr, specs, config):
    """Crope+score (probe gelée) chaque (cx,cy,r,tag). Retourne [(cx,cy,r,score,result)]."""
    from vision.census import face_scores
    from vision.normalize_snap import _crop_mask_resize_int

    imgs, kept = [], []
    for cx, cy, r in specs:
        res = _crop_mask_resize_int(bgr, int(round(cx)), int(round(cy)), int(round(r)),
                                    method="score_recover", config=config)
        if res.image is not None:
            imgs.append(res.image)
            kept.append((cx, cy, r, res))
    if not imgs:
        return []
    scores = face_scores(imgs)
    return [(cx, cy, r, float(s), res) for (cx, cy, r, res), s in zip(kept, scores)]


def search_best_crop(
    bgr: np.ndarray, hint: dict, config=None, sweep_center: bool = False,
) -> dict | None:
    """Balayage de rayon scoré autour du `hint` → meilleur crop pièce-entière (sans gate).

    `hint` = {cx, cy, r_final|r} de la détection / bbox actuelle (coords natives). Retourne
    `{"result": NormalizationResult, "score": float, "baseline_score": float, "ratio": float}`
    où `baseline_score` = le score du crop AU rayon du hint (×1.0) → permet au caller de ne
    remplacer un crop existant QUE si le meilleur l'améliore franchement. `None` si aucun crop.
    """
    if bgr is None or bgr.size == 0:
        return None
    H, W = bgr.shape[:2]
    short = min(H, W)
    cx0, cy0 = float(hint["cx"]), float(hint["cy"])
    r0 = float(hint.get("r_final") or hint.get("r") or 0.0)
    if r0 <= 0:
        return None
    rcap = _RCAP_FRAC * short

    # Étage 1 : ladder grossier (×mult sur r_hint ∪ fractions absolues du short). Le ×1.0
    # (= rayon du hint) sert de baseline de comparaison.
    specs, seen, base_rk = [], set(), int(round(min(r0, rcap)))
    radii = [r0 * m for m in _RADIUS_MULT] + [f * short for f in _RADIUS_ABS_FRAC]
    for r in radii:
        r = min(r, rcap)
        rk = int(round(r))
        if rk < 8 or rk in seen:
            continue
        seen.add(rk)
        ccx, ccy = _clamp_center(cx0, cy0, r, W, H)
        specs.append((ccx, ccy, r))
    scored = _score_specs(bgr, specs, config)
    if not scored:
        return None

    baseline_score = next((t[3] for t in scored if int(round(t[2])) == base_rk), scored[0][3])
    best = max(scored, key=lambda t: t[3])

    # Étage 2 : affinage fin autour du meilleur rayon (au même centre).
    bcx, bcy, br = best[0], best[1], best[2]
    fine, seenf = [], {int(round(br))}
    for m in _RADIUS_FINE:
        r = min(br * m, rcap)
        rk = int(round(r))
        if rk < 8 or rk in seenf:
            continue
        seenf.add(rk)
        ccx, ccy = _clamp_center(bcx, bcy, r, W, H)
        fine.append((ccx, ccy, r))
    fine_scored = _score_specs(bgr, fine, config)
    if fine_scored:
        best = max([best] + fine_scored, key=lambda t: t[3])

    # Étage 3 (optionnel) : balayage du CENTRE au meilleur rayon courant, puis
    # re-affinage du rayon au nouveau centre. Rattrape les crops décalés que les
    # étages rayon-seul (centre = hint) ne peuvent pas corriger. Ancré sur le
    # centre du hint (cx0, cy0) ± offsets·r0 — un crop décalé a son vrai centre à
    # une fraction du rayon de la bbox.
    if sweep_center:
        br = best[2]
        # Grille de centre menée à DEUX rayons (le meilleur courant et 0,85× plus
        # serré) : un crop décalé a souvent un vrai centre déplacé ET un rayon plus
        # petit en même temps (optimum joint que la descente rayon-puis-centre
        # raterait sinon — mesuré sur 909255c5).
        sweep_radii = [br]
        if int(round(0.85 * br)) >= 8:
            sweep_radii.append(0.85 * br)
        cspecs, seenc = [], set()
        for sr in sweep_radii:
            for ox in _CENTER_OFFSETS_FRAC:
                for oy in _CENTER_OFFSETS_FRAC:
                    ccx, ccy = _clamp_center(cx0 + ox * r0, cy0 + oy * r0, sr, W, H)
                    key = (int(round(ccx)), int(round(ccy)), int(round(sr)))
                    if key in seenc:
                        continue
                    seenc.add(key)
                    cspecs.append((ccx, ccy, sr))
        cscored = _score_specs(bgr, cspecs, config)
        if cscored:
            best = max([best] + cscored, key=lambda t: t[3])
            # Affinage du centre autour du gagnant (la grille grossière au pas 0,1
            # rate les optima intermédiaires, ex. décalage à −0,15·r0). ±0,05/±0,1·r0.
            bcx, bcy = best[0], best[1]
            br = best[2]
            rspecs, seenr = [], {(int(round(bcx)), int(round(bcy)))}
            for ox in (-0.1, -0.05, 0.05, 0.1):
                for oy in (-0.1, -0.05, 0.0, 0.05, 0.1):
                    ccx, ccy = _clamp_center(bcx + ox * r0, bcy + oy * r0, br, W, H)
                    key = (int(round(ccx)), int(round(ccy)))
                    if key in seenr:
                        continue
                    seenr.add(key)
                    rspecs.append((ccx, ccy, br))
            rscored = _score_specs(bgr, rspecs, config)
            if rscored:
                best = max([best] + rscored, key=lambda t: t[3])
            # Re-affine le rayon au centre gagnant (le bon rayon dépend du centre).
            bcx, bcy, br = best[0], best[1], best[2]
            fine2, seenf2 = [], {int(round(br))}
            for m in _RADIUS_FINE:
                r = min(br * m, rcap)
                rk = int(round(r))
                if rk < 8 or rk in seenf2:
                    continue
                seenf2.add(rk)
                ccx, ccy = _clamp_center(bcx, bcy, r, W, H)
                fine2.append((ccx, ccy, r))
            fine2_scored = _score_specs(bgr, fine2, config)
            if fine2_scored:
                best = max([best] + fine2_scored, key=lambda t: t[3])

    return {"result": best[4], "score": best[3], "baseline_score": baseline_score,
            "ratio": best[2] / r0}


def recover_crop(bgr: np.ndarray, hint: dict, tau: float, config=None):
    """Cherche le crop pièce-entière qui maximise la probe, autour du `hint`.

    `hint` = {cx, cy, r_final} de la détection dominante (coords natives). `tau` = seuil du
    gate (même que `_census_fragment_tau`). Retourne un `NormalizationResult` (method
    "score_recover", cx/cy/r renseignés pour reconstruire la bbox) si le meilleur candidat
    passe le gate, sinon `None` (aucune dégradation : l'image reste zero_crops).
    """
    best = search_best_crop(bgr, hint, config=config)
    if best is None or best["score"] < tau:
        return None  # rien ne passe le gate → l'image reste zero_crops (pas de dégradation)
    return best["result"]
