"""Tests du verdict intrus closed-set + consensus intra-classe (P1 v2).

Reproduit synthétiquement le scénario mesuré sur mix-zone-17 (faux positifs
Kniefall de-2020) : une classe dont l'ancre canonique matche mal ses propres
photos réelles. Sans consensus, tous ses crops seraient « intrus » ; avec le
consensus (centroïde leave-one-out des camarades éligibles), seuls les vrais
intrus minoritaires restent flagués.

Run: `.venv/bin/python -m pytest ml/tests/test_training_set_scan.py -q`
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from training.training_set_scan import (  # noqa: E402
    CropForVerdict,
    compute_closed_set_verdicts,
)


def _n(v: list[float]) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64)
    return a / np.linalg.norm(a)


# Directions : u1 = allure RÉELLE de la classe A (photos eBay), u2 = classe B,
# u3 = ancre canonique de A (photo studio qui matche mal le réel — sim 0 avec u1).
U1 = [1.0, 0.0, 0.0, 0.0]
U2 = [0.0, 1.0, 0.0, 0.0]
U3 = [0.0, 0.0, 1.0, 0.0]

# Banque d'ancres : index 0 = ancre A (faible), index 1 = ancre B.
BANK = np.stack([_n(U3), _n(U2)])
CLASS_ANCHORS = {"A": [(0, "a-coin")], "B": [(1, "b-coin")]}

# 4 crops réels de A : proches entre eux (u1) avec une teinte de u2 — sans
# consensus, l'ancre B (sim ≈ 0.29) bat l'ancre A (sim 0) → faux positifs.
REAL_A = [_n([1.0, 0.3, 0.0, 0.05 * i]) for i in range(4)]


def _crops_and_vecs(extra=()):
    crops = [
        CropForVerdict(asset_id=f"real-{i}", assigned_class="A",
                       eligible=True, effective_face="obverse")
        for i in range(len(REAL_A))
    ]
    vecs = list(REAL_A)
    for c, v in extra:
        crops.append(c)
        vecs.append(v)
    return crops, np.stack(vecs)


def test_consensus_saves_cohesive_classmates_from_weak_anchor():
    crops, vecs = _crops_and_vecs()
    out = compute_closed_set_verdicts(
        crops, vecs, class_anchor_rows=CLASS_ANCHORS, bank_matrix=BANK,
        intruder_margin=0.05,
    )
    for r in out:
        # L'ancre canonique est bien faible (≈ 0) mais le consensus LOO des
        # 3 camarades sauve le crop : assigned_sim ≈ 1 → pas intrus.
        assert r.anchor_sim is not None and r.anchor_sim < 0.1
        assert r.consensus_sim is not None and r.consensus_sim > 0.9
        assert r.is_intruder is False


def test_true_minority_intruder_still_flagged():
    intruder = (
        CropForVerdict(asset_id="intrus", assigned_class="A",
                       eligible=True, effective_face="obverse"),
        _n(U2),  # c'est une pièce B, étiquetée A
    )
    crops, vecs = _crops_and_vecs([intruder])
    out = compute_closed_set_verdicts(
        crops, vecs, class_anchor_rows=CLASS_ANCHORS, bank_matrix=BANK,
        intruder_margin=0.05,
    )
    by_id = {r.asset_id: r for r in out}
    # L'intrus : loin du centroïde LOO de A (qui ne le contient pas), collé à B.
    r = by_id["intrus"]
    assert r.is_intruder is True
    assert r.top1_class == "B"
    assert r.top1_eurio_id == "b-coin"
    assert r.margin is not None and r.margin > 0.5
    # Les 4 vrais crops de A restent sauvés malgré l'intrus dans le pool
    # (centroïde dominé par la majorité).
    assert all(not by_id[f"real-{i}"].is_intruder for i in range(4))


def test_non_eligible_crop_is_judged_but_does_not_shape_consensus():
    rejected = (
        CropForVerdict(asset_id="rej", assigned_class="A",
                       eligible=False, effective_face="obverse"),
        _n(U2),  # rejeté mal étiqueté : en réalité une B → candidat rescue
    )
    crops, vecs = _crops_and_vecs([rejected])
    out = compute_closed_set_verdicts(
        crops, vecs, class_anchor_rows=CLASS_ANCHORS, bank_matrix=BANK,
        intruder_margin=0.05,
    )
    r = next(x for x in out if x.asset_id == "rej")
    # Jugé (badge rescue possible)…
    assert r.is_intruder is True and r.top1_class == "B"
    # …mais absent du centroïde : les crops éligibles gardent un consensus pur.
    real = next(x for x in out if x.asset_id == "real-0")
    assert real.consensus_sim is not None and real.consensus_sim > 0.9


def test_reverse_face_never_flagged():
    rev = (
        CropForVerdict(asset_id="rev", assigned_class="A",
                       eligible=True, effective_face="reverse"),
        _n(U2),
    )
    crops, vecs = _crops_and_vecs([rev])
    out = compute_closed_set_verdicts(
        crops, vecs, class_anchor_rows=CLASS_ANCHORS, bank_matrix=BANK,
        intruder_margin=0.05,
    )
    r = next(x for x in out if x.asset_id == "rev")
    assert r.is_intruder is False


def test_outlier_catches_intruder_whose_true_class_is_outside_cohort():
    # Cas Brandenburg mesuré : l'intrus n'est réclamé par AUCUNE classe de la
    # cohorte (sa vraie classe n'y est pas) → marge ~0. Mais il ne ressemble
    # pas à ses camarades → outlier (médiane − K·MAD), même à DEUX intrus
    # jumeaux (la purge du centroïde casse la validation mutuelle).
    u4 = [0.0, 0.0, 0.0, 1.0]  # design hors cohorte
    reals = [
        (CropForVerdict(asset_id=f"real-{i}", assigned_class="A",
                        eligible=True, effective_face="obverse"),
         _n([1.0, 0.3, 0.0, 0.02 * i]))
        for i in range(5)
    ]
    twins = [
        (CropForVerdict(asset_id=f"twin-{i}", assigned_class="A",
                        eligible=True, effective_face="obverse"), _n(u4))
        for i in range(2)
    ]
    crops = [c for c, _ in reals + twins]
    vecs = np.stack([v for _, v in reals + twins])
    out = compute_closed_set_verdicts(
        crops, vecs, class_anchor_rows=CLASS_ANCHORS, bank_matrix=BANK,
        intruder_margin=0.05,
    )
    by_id = {r.asset_id: r for r in out}
    for i in range(2):
        r = by_id[f"twin-{i}"]
        assert r.is_intruder is True
        assert r.intruder_reason == "outlier"  # personne ne le réclame (marge)
    for i in range(5):
        assert by_id[f"real-{i}"].is_intruder is False


def test_min_consensus_guard_falls_back_to_anchor():
    # 3 crops éligibles → LOO n'en laisse que 2 < MIN_CONSENSUS_CROPS (3) :
    # pas de consensus, l'ancre faible redevient seule juge → flagués. Le
    # garde-fou évite que 2-3 intrus jumeaux se valident mutuellement.
    crops = [
        CropForVerdict(asset_id=f"c{i}", assigned_class="A",
                       eligible=True, effective_face="obverse")
        for i in range(3)
    ]
    vecs = np.stack(REAL_A[:3])
    out = compute_closed_set_verdicts(
        crops, vecs, class_anchor_rows=CLASS_ANCHORS, bank_matrix=BANK,
        intruder_margin=0.05,
    )
    for r in out:
        assert r.consensus_sim is None
        assert r.is_intruder is True  # l'ancre faible ne les sauve pas


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
