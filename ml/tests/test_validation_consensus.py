"""C3 — table de décision du consensus (chaque branche + invariant de sûreté)."""

from __future__ import annotations

from review.validation.consensus import consensus_verdict
from review.validation.experts import CropQuality, crop_signal, dino_signal, text_signal


def _sig(text_verdict, *, target, top1, sim, spread, crop):
    return [
        text_signal(text_verdict),
        dino_signal(target=target, top1=top1, sim=sim, spread=spread),
        crop_signal(crop),
    ]


_GOOD = CropQuality(None, None, 0.95, None)
_TILTED = CropQuality(35.0, 1, None, None)
_OK_TILT = CropQuality(12.0, 1, None, None)


def test_no_signal_to_needs_review():
    cv = consensus_verdict(_sig(None, target=None, top1=None, sim=None, spread=None,
                                crop=CropQuality(None, None, None, None)))
    assert cv.outcome == "needs_review" and cv.rule == "no_signal"
    assert cv.lane == "manual"


def test_dual_contradict_to_reject():
    cv = consensus_verdict(_sig("contradict", target="fr-x", top1="de-y", sim=0.9,
                                spread=0.1, crop=_GOOD))
    assert cv.outcome == "reject" and cv.rule == "dual_contradict"


def test_crop_cap_overrides_accept():
    # dino fort + texte convergent MAIS crop tilté → plafond needs_review.
    cv = consensus_verdict(_sig("convergent", target="fr-x", top1="fr-x", sim=0.9,
                                spread=0.1, crop=_TILTED))
    assert cv.outcome == "needs_review" and cv.rule == "crop_cap"


def test_strong_accept():
    cv = consensus_verdict(_sig("convergent", target="fr-x", top1="fr-x", sim=0.9,
                                spread=0.1, crop=_OK_TILT))
    assert cv.outcome == "accept" and cv.rule == "strong_accept"
    assert cv.lane == "auto_accept" and cv.confidence == 0.9


def test_text_contradict_alone_is_rescued_not_killed():
    # LE changement clé : contradict texte + dino match → needs_review, PAS reject.
    cv = consensus_verdict(_sig("contradict", target="fr-x", top1="fr-x", sim=0.9,
                                spread=0.1, crop=_GOOD))
    assert cv.outcome == "needs_review" and cv.rule == "text_contradict_rescue"


def test_dino_mismatch_alone_to_needs_review():
    cv = consensus_verdict(_sig("convergent", target="fr-x", top1="de-y", sim=0.9,
                                spread=0.1, crop=_GOOD))
    assert cv.outcome == "needs_review" and cv.rule == "dino_mismatch"


def test_partial_to_needs_review():
    # dino match mais sim sous le seuil → partiel.
    cv = consensus_verdict(_sig("convergent", target="fr-x", top1="fr-x", sim=0.40,
                                spread=0.1, crop=_GOOD))
    assert cv.outcome == "needs_review" and cv.rule == "partial"


def test_safety_no_accept_without_text_convergent():
    # dino fort mais texte absent → JAMAIS accept (⊆ auto_candidate actuel).
    cv = consensus_verdict(_sig(None, target="fr-x", top1="fr-x", sim=0.9,
                                spread=0.1, crop=_GOOD))
    assert cv.outcome == "needs_review"


def test_standard_out_of_scope_not_falsely_rejected():
    # Régression : un standard (hors scope ancres commemo) avec texte contradict
    # et top1≠cible ne doit PAS être rejeté (dino abstient) → rescue needs_review.
    cv = consensus_verdict([
        text_signal("contradict"),
        dino_signal(target="be-1999-standard", top1="be-2021-commemo",
                    sim=0.9, spread=0.1, in_scope=False),
        crop_signal(_GOOD),
    ])
    assert cv.outcome == "needs_review" and cv.rule == "text_contradict_rescue"
