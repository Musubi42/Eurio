"""Tests de `shared.stats.paired` — McNemar exact et comparaison appariée.

Pourquoi ces tests : sur ~1 900 crops, deux R@1 indépendants qui diffèrent de
deux points ne prouvent rien. Ce qui fait foi, ce sont les paires discordantes.
Un bug ici passerait inaperçu — il rendrait juste un p-value plausible.
"""
from __future__ import annotations

import pytest

from shared.stats.paired import PairedResult, mcnemar_exact, paired_compare


# ─── mcnemar_exact ──────────────────────────────────────────────────────────


def test_mcnemar_aucune_paire_discordante_vaut_1() -> None:
    assert mcnemar_exact(0, 0) == 1.0


def test_mcnemar_est_symetrique() -> None:
    assert mcnemar_exact(3, 9) == mcnemar_exact(9, 3)
    assert mcnemar_exact(0, 10) == mcnemar_exact(10, 0)


def test_mcnemar_valeurs_calculees_a_la_main() -> None:
    # n=8, k=1 : 2 * (C(8,0)+C(8,1)) / 2^8 = 2 * 9/256 = 18/256
    assert mcnemar_exact(1, 7) == pytest.approx(18 / 256)
    # n=10, k=0 : 2 * 1/1024 = 2/1024
    assert mcnemar_exact(0, 10) == pytest.approx(2 / 1024)
    # n=5, k=2 : 2 * (1+5+10)/32 = 32/32 = 1.0 (borné)
    assert mcnemar_exact(2, 3) == pytest.approx(1.0)


def test_mcnemar_borne_a_1() -> None:
    for b in range(0, 8):
        for c in range(0, 8):
            assert 0.0 <= mcnemar_exact(b, c) <= 1.0


def test_mcnemar_une_seule_paire_nest_pas_significatif() -> None:
    assert mcnemar_exact(0, 1) == 1.0


def test_mcnemar_dix_contre_zero_est_tres_petit() -> None:
    assert mcnemar_exact(0, 10) < 0.005


# ─── paired_compare ─────────────────────────────────────────────────────────


def test_paired_compare_cles_disjointes_ne_compare_rien() -> None:
    """D16 — deux runs sans un seul crop en commun ne se comparent pas.

    Avant : ``delta_acc=0.0, p_value=1.0``, soit « aucune différence
    significative » — un verdict, alors qu'il n'y a pas eu de test. Le ``1.0``
    partait tel quel dans ``encoder_bench_runs.mcnemar_p``, sans marqueur.
    """
    res = paired_compare({"a": True, "b": False}, {"c": True})
    assert res == PairedResult(
        n_paired=0,
        both_correct=0,
        a_only=0,
        b_only=0,
        neither=0,
        acc_a=None,
        acc_b=None,
        delta_acc=None,
        p_value=None,
    )
    assert res.comparable is False
    assert res.to_dict()["p_value"] is None


def test_paired_compare_intersection_non_vide_reste_comparable() -> None:
    """Un apparié sans paire DISCORDANTE garde p=1.0 : là, le test a eu lieu."""
    res = paired_compare({"a": True, "b": False}, {"a": True, "b": False})
    assert res.n_paired == 2
    assert res.comparable is True
    assert res.p_value == 1.0
    assert res.delta_acc == 0.0


def test_paired_compare_table_de_contingence_exacte() -> None:
    a = {"1": True, "2": True, "3": False, "4": False, "5": True}
    b = {"1": True, "2": False, "3": True, "4": False, "5": False}
    res = paired_compare(a, b)
    assert res.n_paired == 5
    assert res.both_correct == 1  # "1"
    assert res.a_only == 2  # "2", "5"
    assert res.b_only == 1  # "3"
    assert res.neither == 1  # "4"
    assert res.acc_a == pytest.approx(3 / 5)
    assert res.acc_b == pytest.approx(2 / 5)
    assert res.delta_acc == pytest.approx(-1 / 5)
    assert res.p_value == pytest.approx(mcnemar_exact(2, 1))


def test_paired_compare_nutilise_que_lintersection() -> None:
    """Un run qui a tourné sur plus de crops ne doit pas diluer l'autre."""
    a = {"1": True, "2": True, "3": True}
    b = {"1": False, "2": False}
    res = paired_compare(a, b)
    assert res.n_paired == 2
    assert res.acc_a == pytest.approx(1.0)
    assert res.acc_b == pytest.approx(0.0)
    assert res.a_only == 2 and res.b_only == 0


def test_paired_compare_delta_de_bon_signe() -> None:
    a = {str(i): False for i in range(10)}
    b = {str(i): True for i in range(10)}
    res = paired_compare(a, b)
    assert res.delta_acc == pytest.approx(1.0)
    assert res.b_only == 10 and res.a_only == 0
    assert res.p_value < 0.01
