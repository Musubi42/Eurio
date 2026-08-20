"""Tests de `shared.stats.sweep` — balayage précision/couverture et calibration.

Le test qui compte est `test_seuils_derives_des_donnees_pas_de_zero_a_un` :
c'est lui qui prouve P6-4. Balayer [0,1] en dur sur un encodeur dont les
spreads vivent dans [0,02 ; 0,06] rendrait une courbe à un seul point utile,
sans lever la moindre erreur.

Le garde de calibration (P3) est testé à part :
`tests/test_threshold_calibration.py`.
"""
from __future__ import annotations

import json

import pytest

from shared.stats.sweep import (
    SweepPoint,
    curve_to_json,
    precision_coverage_curve,
    threshold_for_precision,
)


def _jeu_realiste() -> list[tuple[float, bool]]:
    """100 items : plus le score est haut, plus c'est souvent correct."""
    items: list[tuple[float, bool]] = []
    for i in range(100):
        score = 0.02 + 0.04 * i / 99  # dans [0,02 ; 0,06]
        items.append((score, i >= 20))  # les 20 plus bas sont faux
    return items


# ─── precision_coverage_curve ───────────────────────────────────────────────


def test_couverture_decroissante_en_seuil() -> None:
    curve = precision_coverage_curve(_jeu_realiste(), n_steps=21)
    covs = [p.n_covered for p in curve]
    assert covs == sorted(covs, reverse=True)
    assert curve[0].n_covered == 100  # seuil = min observé → tout est couvert
    assert curve[0].coverage == pytest.approx(1.0)


def test_seuils_derives_des_donnees_pas_de_zero_a_un() -> None:
    """P6-4 : l'échelle de balayage est celle de l'encodeur, pas [0,1]."""
    curve = precision_coverage_curve(_jeu_realiste(), n_steps=11)
    thresholds = [p.threshold for p in curve]
    assert thresholds[0] == pytest.approx(0.02)
    assert thresholds[-1] == pytest.approx(0.06)
    assert all(0.02 <= t <= 0.06 for t in thresholds)
    assert len(thresholds) == 11


def test_n_covered_zero_ne_divise_pas_par_zero() -> None:
    curve = precision_coverage_curve(
        [(0.1, True), (0.2, False)], thresholds=[0.5, 0.9]
    )
    assert [p.n_covered for p in curve] == [0, 0]
    assert [p.precision for p in curve] == [0.0, 0.0]
    assert [p.coverage for p in curve] == [0.0, 0.0]


def test_items_vide_rend_courbe_vide() -> None:
    assert precision_coverage_curve([]) == []


def test_scores_tous_egaux_rend_un_seul_seuil() -> None:
    curve = precision_coverage_curve([(0.3, True), (0.3, False)], n_steps=7)
    assert len(curve) == 1
    assert curve[0].threshold == pytest.approx(0.3)
    assert curve[0].precision == pytest.approx(0.5)


def test_precision_calculee_sur_les_couverts_seulement() -> None:
    items = [(0.1, False), (0.5, True), (0.9, True)]
    curve = precision_coverage_curve(items, thresholds=[0.0, 0.5])
    assert curve[0].precision == pytest.approx(2 / 3)
    assert curve[1].precision == pytest.approx(1.0)
    assert curve[1].coverage == pytest.approx(2 / 3)


# ─── threshold_for_precision ────────────────────────────────────────────────


def test_rend_le_seuil_le_plus_bas_qualifiant() -> None:
    curve = precision_coverage_curve(_jeu_realiste(), n_steps=101)
    point = threshold_for_precision(curve, 0.97, min_covered=30)
    assert point is not None
    # le plus bas qualifiant : aucun point strictement plus bas ne qualifie
    plus_bas = [
        p
        for p in curve
        if p.threshold < point.threshold
        and p.n_covered >= 30
        and p.precision >= 0.97
    ]
    assert plus_bas == []
    assert point.precision >= 0.97


def test_cible_inatteignable_rend_none() -> None:
    """« Aucun seuil n'atteint 97 % » est une réponse, pas une erreur."""
    items = [(0.1 * i, i % 2 == 0) for i in range(100)]  # ~50 % partout
    curve = precision_coverage_curve(items, n_steps=51)
    assert threshold_for_precision(curve, 0.97, min_covered=10) is None


def test_min_covered_est_respecte() -> None:
    """Un point à 100 % sur 3 crops n'est pas une calibration."""
    curve = [
        SweepPoint(threshold=0.1, n_covered=100, coverage=1.0, n_correct=50, precision=0.5),
        SweepPoint(threshold=0.5, n_covered=3, coverage=0.03, n_correct=3, precision=1.0),
        SweepPoint(threshold=0.4, n_covered=40, coverage=0.4, n_correct=40, precision=1.0),
    ]
    assert threshold_for_precision(curve, 0.97, min_covered=30).threshold == pytest.approx(0.4)
    assert threshold_for_precision(curve, 0.97, min_covered=200) is None


# ─── curve_to_json ──────────────────────────────────────────────────────────


def test_curve_to_json_borne_et_conserve_les_extremites() -> None:
    curve = precision_coverage_curve(_jeu_realiste(), n_steps=101)
    payload = json.loads(curve_to_json(curve, max_points=16))
    assert len(payload) <= 16
    assert payload[0]["threshold"] == pytest.approx(curve[0].threshold, abs=1e-6)
    assert payload[-1]["threshold"] == pytest.approx(curve[-1].threshold, abs=1e-6)
    assert "threshold" in payload[0] and "precision" in payload[0]


def test_curve_to_json_courte_reste_entiere() -> None:
    curve = precision_coverage_curve(_jeu_realiste(), n_steps=5)
    assert len(json.loads(curve_to_json(curve, max_points=64))) == 5


# ─── non-régression du déménagement de mcnemar_exact ────────────────────────


def test_replay_corpus_reexporte_le_meme_objet() -> None:
    from scripts.replay_corpus import mcnemar_exact as via_script
    from shared.stats.paired import mcnemar_exact as via_paquet

    assert via_script is via_paquet
