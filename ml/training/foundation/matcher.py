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


def top_k_match(
    query_vec: np.ndarray,
    bank: AnchorBank,
    *,
    top_k: int = 5,
) -> list[Match]:
    """Return the top-K nearest anchors for ``query_vec``, sorted desc by sim."""
    if bank.count == 0:
        return []
    if query_vec.ndim != 1:
        raise ValueError(
            f"query_vec must be 1-D (D,), got shape={query_vec.shape}"
        )
    if query_vec.shape[0] != bank.dim:
        raise ValueError(
            f"query_vec dim={query_vec.shape[0]} ≠ bank dim={bank.dim}"
        )

    sims = bank.matrix @ query_vec  # (N,)
    k = min(top_k, bank.count)
    # argpartition for the k largest, then sort just those k
    idx_part = np.argpartition(-sims, k - 1)[:k] if k > 1 else np.array([int(np.argmax(sims))])
    idx_sorted = idx_part[np.argsort(-sims[idx_part])]
    return [
        Match(eurio_id=bank.eurio_ids[int(i)], sim=float(sims[int(i)]))
        for i in idx_sorted
    ]


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
    if query_vec.ndim != 1:
        raise ValueError(
            f"query_vec must be 1-D (D,), got shape={query_vec.shape}"
        )
    if query_vec.shape[0] != bank.dim:
        raise ValueError(
            f"query_vec dim={query_vec.shape[0]} ≠ bank dim={bank.dim}"
        )
    if not target_country:
        return []

    target = target_country.lower()
    mask = np.array(
        [eid[:2].lower() == target for eid in bank.eurio_ids],
        dtype=bool,
    )
    n_match = int(mask.sum())
    if n_match == 0:
        return []

    sims = bank.matrix @ query_vec
    masked = np.where(mask, sims, -np.inf)
    k = min(top_k, n_match)
    idx_part = np.argpartition(-masked, k - 1)[:k] if k > 1 else np.array([int(np.argmax(masked))])
    idx_sorted = idx_part[np.argsort(-masked[idx_part])]
    return [
        Match(eurio_id=bank.eurio_ids[int(i)], sim=float(sims[int(i)]))
        for i in idx_sorted
    ]


def spread(matches: list[Match]) -> float:
    """top1.sim − top2.sim (0.0 if fewer than 2 matches)."""
    if len(matches) < 2:
        return 0.0
    return float(matches[0].sim - matches[1].sim)
