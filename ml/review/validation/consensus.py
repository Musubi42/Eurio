"""Règle de consensus de l'auto-validation (C3 du redesign).

Agrège les avis d'experts (``Signal`` : text + dino + crop_quality) en un verdict
``{accept, needs_review, reject}`` + lane + confiance + raison. **Remplace le
gauntlet** : plus aucun expert ne tue seul un listing — le rejet n'arrive QUE sur
désaccord fort de deux experts, et reste ré-ouvrable (C5). Un contradict isolé
devient ``needs_review`` (arbitrage humain), pas un kill.

Forme = **table de décision lisible** (pas de scores pondérés opaques), un humain
doit pouvoir auditer pourquoi (cf. §7 du doc). Chaque branche porte un ``rule``
nommé. Invariant de sûreté : ``accept`` est un SOUS-ENSEMBLE strict des
auto_candidate actuels (mêmes conditions dino+texte, plus la garde crop) → le
shadow ne peut JAMAIS auto-accepter quelque chose que la règle actuelle review.

Statut : SHADOW. ``consensus_verdict`` est calculée et diffée contre le verdict
courant sur le gold (``consensus_shadow``) ; non câblée au pipeline live tant que
le diff n'est pas validé.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

from review.validation.experts import Signal, collect_signals
from training.foundation.auto_validate import compute_auto_validate_view

RULE_VERSION = 1

_CROP_BAD = {"too_tilted", "low_quality"}


@dataclass(frozen=True)
class ConsensusVerdict:
    outcome: str  # accept | needs_review | reject
    lane: str  # auto_accept | ccproxy | manual
    confidence: float  # [0, 1]
    reason: str
    rule: str  # branche déclenchée (audit)


def consensus_verdict(signals: list[Signal]) -> ConsensusVerdict:
    """Table de décision sur les avis d'experts. Ordre = priorité."""
    by = {s.expert: s for s in signals}
    text = by.get("text")
    dino = by.get("dino")
    crop = by.get("crop_quality")

    text_label = text.label if text else "absent"
    dino_label = dino.label if dino else "absent"
    sim = dino.score if dino else None
    sim_pass = bool(dino and dino.raw.get("sim_pass"))
    spread_pass = bool(dino and dino.raw.get("spread_pass"))
    dino_strong = dino_label == "match" and sim_pass and spread_pass
    crop_bad = crop is not None and crop.label in _CROP_BAD

    # 1. Aucun signal exploitable → filet humain (règle actuelle conservée).
    if dino_label == "absent" and text_label == "absent":
        return ConsensusVerdict(
            "needs_review", "manual", 0.20,
            "aucun signal exploitable (dino + texte absents)", "no_signal",
        )

    # 2. Désaccord FORT des deux experts → reject ré-ouvrable (C5).
    if text_label == "contradict" and dino_label == "mismatch":
        return ConsensusVerdict(
            "reject", "manual", 0.85,
            "texte ET dino contredisent la cible", "dual_contradict",
        )

    # 3. Crop défaillant → plafond needs_review quel que soit dino (cap C2).
    if crop_bad:
        return ConsensusVerdict(
            "needs_review", "ccproxy", 0.50,
            f"crop {crop.label} → plafonné needs_review", "crop_cap",
        )

    # 4. Accord fort + crop OK → accept (⊆ auto_candidate actuel).
    if dino_strong and text_label == "convergent":
        return ConsensusVerdict(
            "accept", "auto_accept",
            round(min(1.0, sim if sim is not None else 0.0), 4),
            "dino fort + texte convergent + crop OK", "strong_accept",
        )

    # 5. Contradiction d'un SEUL expert → needs_review (rescue, PAS kill).
    if text_label == "contradict":  # dino n'est pas mismatch (sinon règle 2)
        return ConsensusVerdict(
            "needs_review", "ccproxy", 0.40,
            "texte contredit mais dino ne confirme pas le rejet → arbitrage",
            "text_contradict_rescue",
        )
    if dino_label == "mismatch":  # texte ne contredit pas
        return ConsensusVerdict(
            "needs_review", "ccproxy", 0.40,
            "dino diverge de la cible, texte ne tranche pas → arbitrage",
            "dino_mismatch",
        )

    # 6. Signaux partiels (dino match tiède, ou texte partial/absent) → review.
    return ConsensusVerdict(
        "needs_review", "ccproxy", 0.35,
        "signaux partiels → arbitrage humain", "partial",
    )


def _old_outcome(level: str) -> str:
    """Mappe le verdict actuel (4-vocab) vers le 3-vocab pour comparer.
    Le gold est post-gate pipeline → l'ancien ne produit que accept/needs_review."""
    return "accept" if level == "auto_candidate" else "needs_review"


def consensus_shadow(conn: sqlite3.Connection, gold: list) -> dict:
    """Diffe l'ancien verdict vs le consensus sur le gold, SANS écrire.

    Retourne la matrice de confusion (old × new), le détail des flips (avec
    règle déclenchée + vérité terrain), et un contrôle de sûreté (aucun nouvel
    auto-accept).
    """
    conn.row_factory = sqlite3.Row
    confusion: Counter = Counter()
    flips: list[dict] = []
    rule_dist: Counter = Counter()

    for g in gold:
        view = compute_auto_validate_view(conn, g.asset_id)
        old = _old_outcome(view.level)
        signals = collect_signals(conn, g.asset_id)
        cv = consensus_verdict(signals)
        confusion[(old, cv.outcome)] += 1
        rule_dist[cv.rule] += 1
        if old != cv.outcome:
            dino = next((s for s in signals if s.expert == "dino"), None)
            flips.append(
                {
                    "asset_id": g.asset_id,
                    "source": g.source,
                    "old": old,
                    "new": cv.outcome,
                    "rule": cv.rule,
                    "ground_truth": g.ground_truth_eurio_id,
                    "dino_top1": dino.raw.get("top1") if dino else None,
                }
            )

    new_autoaccepts = confusion[("needs_review", "accept")]
    return {
        "n": len(gold),
        "confusion": {f"{o}->{n}": c for (o, n), c in sorted(confusion.items())},
        "new_rule_dist": dict(rule_dist),
        "n_flips": len(flips),
        "flips": flips,
        "safety_no_new_autoaccept": new_autoaccepts == 0,
    }
