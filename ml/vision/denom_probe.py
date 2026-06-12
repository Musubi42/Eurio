"""Gate dénomination — probe DINO « 2€ vs junk » (C7 pilier 2, H11bis).

Inférence de la probe logistique entraînée par `scripts/train_denom_probe.py` :
score 2€-ness ∈ [0,1] = sigmoïde sur [embedding vitl14 gelé (1024-d) ⊕ `bimetal_score`
normalisé]. Au-dessus du seuil → `2eur` ; en dessous → `not_2eur` (cent / médaille /
mire / 1€ / set). Rejette, per-crop, la pollution des photos de lots.

Le seuil est calibré R0-safe : sur 419 vrais 2€ held-out, **99,5 % passent**
(false-drop 0,48 %, et le rejet reste ré-ouvrable). Cf. C7 §H11bis.

Artefact : `ml/state/denom_probe.npz` (coef, intercept, bm_mean, bm_std, threshold,
encoder). Réutilise le `vec` vitl14 déjà encodé par `auto_validate` (gratuit) +
`bimetal_score` (cheap, sur l'image du crop).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from vision.denom_geometry import bimetal_score

ML_DIR = Path(__file__).resolve().parents[1]
PROBE_PATH = ML_DIR / "state" / "denom_probe.npz"

# Encodeur attendu par la probe — doit matcher SUGGESTIONS_ENCODER_VERSION.
PROBE_ENCODER_VERSION = "dinov2-vitl14"

_probe: dict | None = None


def _load() -> dict | None:
    """Charge la probe une fois (singleton). None si l'artefact est absent."""
    global _probe
    if _probe is None:
        if not PROBE_PATH.exists():
            return None
        z = np.load(PROBE_PATH)
        _probe = {
            "coef": z["coef"][0].astype(np.float32),       # (1025,)
            "intercept": float(z["intercept"][0]),
            "bm_mean": float(z["bm_mean"]),
            "bm_std": float(z["bm_std"]),
            "threshold": float(z["threshold"]),
        }
    return _probe


def denom_threshold() -> float | None:
    p = _load()
    return p["threshold"] if p else None


def denom_score(vec: np.ndarray, bgr: np.ndarray) -> float | None:
    """Score 2€-ness ∈ [0,1] pour un crop. None si la probe est absente.

    `vec` : embedding vitl14 normalisé (1024-d), réutilisé tel quel.
    `bgr` : image BGR du crop (pour `bimetal_score`).
    """
    p = _load()
    if p is None:
        return None
    bm = bimetal_score(bgr).get("score", 0.0)
    bm_n = (bm - p["bm_mean"]) / (p["bm_std"] + 1e-6)
    x = np.concatenate([np.asarray(vec, dtype=np.float32), [bm_n]])
    z = float(x @ p["coef"] + p["intercept"])
    return 1.0 / (1.0 + np.exp(-z))


def decide_denom(score: float | None) -> str | None:
    """Verdict de dénomination depuis le score. None si score/probe absent."""
    p = _load()
    if p is None or score is None:
        return None
    return "2eur" if score >= p["threshold"] else "not_2eur"
