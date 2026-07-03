"""Top-K cosine matcher against an anchor bank.

Inputs are L2-normalized by construction (encoder.encode_image and
encoder.encode_paths normalize before returning), so cosine reduces
to a plain dot-product. No batching here — the caller is expected to
loop over crops if needed; the module stays small and trivially
testable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from training.foundation.anchors import AnchorBank


@dataclass
class Match:
    eurio_id: str
    sim: float

    def to_dict(self) -> dict:
        return {"eurio_id": self.eurio_id, "sim": float(self.sim)}


def _best_sim_by_eurio(
    sims: np.ndarray, eurio_ids: list[str], mask: np.ndarray | None = None,
) -> dict[str, float]:
    """Max-pool par eurio_id : depuis B, une banque multi-exemplaires a
    plusieurs lignes par classe (canonique + crops FPS). La similarité d'une
    CLASSE = la meilleure de ses lignes. Dédup indispensable côté suggestions
    (sinon le top-K renverrait 3 exemplaires de la même pièce)."""
    best: dict[str, float] = {}
    for i, eid in enumerate(eurio_ids):
        if mask is not None and not mask[i]:
            continue
        s = float(sims[i])
        if eid not in best or s > best[eid]:
            best[eid] = s
    return best


def _validate_query(query_vec: np.ndarray, bank: AnchorBank) -> None:
    if query_vec.ndim != 1:
        raise ValueError(
            f"query_vec must be 1-D (D,), got shape={query_vec.shape}"
        )
    if query_vec.shape[0] != bank.dim:
        raise ValueError(
            f"query_vec dim={query_vec.shape[0]} ≠ bank dim={bank.dim}"
        )


def top_k_match(
    query_vec: np.ndarray,
    bank: AnchorBank,
    *,
    top_k: int = 5,
) -> list[Match]:
    """Return the top-K nearest DISTINCT classes for ``query_vec``, desc by sim.

    Max-pool par eurio_id (une classe multi-exemplaires ne compte qu'une fois,
    à sa meilleure ligne)."""
    if bank.count == 0:
        return []
    _validate_query(query_vec, bank)
    sims = bank.matrix @ query_vec  # (N,)
    best = _best_sim_by_eurio(sims, bank.eurio_ids)
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [Match(eurio_id=eid, sim=s) for eid, s in ranked]


def top_k_match_country(
    query_vec: np.ndarray,
    bank: AnchorBank,
    *,
    target_country: str,
    top_k: int = 5,
) -> list[Match]:
    """Country-restricted re-rank: top-K nearest anchors *within* a target ISO2.

    Mesure (chunk 3.5, 524 crops 2€ commémo) : sur la même bank et les
    mêmes embeddings, restreindre aux ancres dont l'eurio_id préfixe ==
    target_country fait passer R@1 de 10 % à 34 % et R@5 de 21 % à 66 %.
    Le coût est négligeable (mask numpy, pas de re-encoding).

    Returns ``[]`` if no anchor in the bank matches ``target_country``
    (caller should fall back to ``top_k_match``).
    """
    if bank.count == 0:
        return []
    _validate_query(query_vec, bank)
    if not target_country:
        return []

    target = target_country.lower()
    mask = np.array(
        [eid[:2].lower() == target for eid in bank.eurio_ids],
        dtype=bool,
    )
    if not mask.any():
        return []

    sims = bank.matrix @ query_vec
    best = _best_sim_by_eurio(sims, bank.eurio_ids, mask=mask)  # classes distinctes
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [Match(eurio_id=eid, sim=s) for eid, s in ranked]


def spread(matches: list[Match]) -> float:
    """top1.sim − top2.sim (0.0 if fewer than 2 matches)."""
    if len(matches) < 2:
        return 0.0
    return float(matches[0].sim - matches[1].sim)
