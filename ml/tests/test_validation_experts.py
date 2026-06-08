"""C1 — gate de non-régression des experts d'auto-validation.

Invariant : les experts (text + dino) capturent les signaux SANS PERTE. Un
verdict reconstruit depuis leurs ``Signal`` est strictement identique au verdict
canonique calculé directement par ``_verdict_from_signals``. Cf.
docs/work-in-progress/autovalidation-redesign.md (C1).

L'essentiel du gate est DB-free (fonctions pures sur les 6 branches du verdict).
Un test end-to-end optionnel rejoue ``collect_signals`` sur eurio.db si présent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from review.validation.experts import (
    EXPERTS,
    CropQuality,
    CropQualityExpert,
    DinoExpert,
    Signal,
    TextExpert,
    collect_signals,
    crop_signal,
    dino_signal,
    text_signal,
)
from training.foundation.auto_validate import (
    _verdict_from_signals,
    compute_auto_validate_view,
)

# (target, top1, sim, spread, text_verdict) couvrant les 6 branches du verdict.
_SCENARIOS = [
    pytest.param(None, None, None, None, None, id="no-data->unknown"),
    pytest.param("fr-x", "fr-x", 0.90, 0.10, "contradict", id="contradict->divergent"),
    pytest.param(None, "fr-x", 0.90, 0.10, None, id="no-target->unknown"),
    pytest.param("fr-x", "de-y", 0.90, 0.10, "convergent", id="top1!=target->divergent"),
    pytest.param("fr-x", "fr-x", 0.90, 0.10, "convergent", id="all-pass->auto_candidate"),
    pytest.param("fr-x", "fr-x", 0.40, 0.10, "convergent", id="sim-low->partial"),
    pytest.param("fr-x", "fr-x", 0.90, 0.10, None, id="text-none->partial"),
]


@pytest.mark.parametrize("target, top1, sim, spread, text_verdict", _SCENARIOS)
def test_experts_reconstruct_canonical_verdict(target, top1, sim, spread, text_verdict):
    """Un verdict reconstruit depuis les Signals == le verdict direct."""
    direct = _verdict_from_signals(
        face=None, target=target, top1=top1, sim=sim, spread=spread,
        text_verdict=text_verdict,
    )

    t = text_signal(text_verdict)
    d = dino_signal(target=target, top1=top1, sim=sim, spread=spread)
    reconstructed = _verdict_from_signals(
        face=None,
        target=d.raw["target"],
        top1=d.raw["top1"],
        sim=d.raw["sim"],
        spread=d.raw["spread"],
        text_verdict=t.raw["vs_target_verdict"],
    )

    # AutoValidateVerdict est une dataclass frozen → égalité de tous les champs
    # (level, reason, decided_eurio_id, signaux). Capture sans perte prouvée.
    assert reconstructed == direct


def test_text_expert_labels_and_scores():
    assert text_signal("convergent") == Signal(
        "text", 1.0, "convergent", "texte convergent", {"vs_target_verdict": "convergent"}
    )
    assert text_signal("contradict").score == 0.0
    assert text_signal("partial").score == 0.5
    # None et 'absent' → label 'absent', score None (pas de donnée exploitable).
    assert text_signal(None).label == "absent"
    assert text_signal(None).score is None
    assert text_signal("absent").score is None


def test_dino_expert_labels_and_scores():
    match = dino_signal(target="fr-x", top1="fr-x", sim=0.9, spread=0.1)
    assert match.label == "match"
    assert match.score == 0.9
    assert match.raw["sim_pass"] is True and match.raw["spread_pass"] is True

    mism = dino_signal(target="fr-x", top1="de-y", sim=0.9, spread=0.1)
    assert mism.label == "mismatch"

    # Pas de prédiction → absent, score None.
    none = dino_signal(target="fr-x", top1=None, sim=None, spread=None)
    assert none.label == "absent"
    assert none.score is None

    # Pas de cible → absent même si DINO a un top1.
    no_target = dino_signal(target=None, top1="fr-x", sim=0.9, spread=0.1)
    assert no_target.label == "absent"

    # Seuils : sim sous le seuil ne passe pas.
    low = dino_signal(target="fr-x", top1="fr-x", sim=0.40, spread=0.10)
    assert low.raw["sim_pass"] is False


def test_crop_quality_expert_penalty_rule():
    # Label humain too_tilted → pénalité dure.
    human = crop_signal(CropQuality(None, None, None, "too_tilted"))
    assert human.label == "too_tilted" and human.score == 0.0

    # quality_reason de review (PAS crop) → ignoré → abstention.
    review = crop_signal(CropQuality(None, None, None, "rejected_in_review"))
    assert review.label == "unmeasured" and review.score is None

    # Tilt fiable au-dessus du seuil (30°) → pénalité.
    tilted = crop_signal(CropQuality(35.0, 1, None, None))
    assert tilted.label == "too_tilted" and tilted.score == 0.0

    # Tilt fiable sous le seuil → OK (crop géométriquement bon).
    ok = crop_signal(CropQuality(12.0, 1, None, None))
    assert ok.label == "ok" and ok.score == 1.0

    # Tilt NON fiable (trustworthy=0), même élevé → abstention (pas de pénalité).
    untrusted = crop_signal(CropQuality(40.0, 0, None, None))
    assert untrusted.label == "unmeasured" and untrusted.score is None

    # Tilt NULL, pas de quality_score → abstention.
    none = crop_signal(CropQuality(None, None, None, None))
    assert none.label == "unmeasured" and none.score is None

    # quality_score peuplé (forward-compat) : prioritaire sur le tilt.
    good_q = crop_signal(CropQuality(40.0, 1, 0.8, None))
    assert good_q.label == "good" and good_q.score == 0.8
    low_q = crop_signal(CropQuality(5.0, 1, 0.2, None))
    assert low_q.label == "low_quality" and low_q.score == 0.2


def test_expert_registry_order_and_names():
    assert [e.name for e in EXPERTS] == ["text", "dino", "crop_quality"]
    assert isinstance(EXPERTS[0], TextExpert)
    assert isinstance(EXPERTS[1], DinoExpert)
    assert isinstance(EXPERTS[2], CropQualityExpert)


# ── End-to-end optionnel sur eurio.db ───────────────────────────────────

_DB = Path(__file__).resolve().parents[1] / "state" / "eurio.db"


@pytest.mark.skipif(not _DB.exists(), reason="eurio.db absent (CI sans état)")
def test_collect_signals_matches_canonical_view_on_db():
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    try:
        ids = [
            r["asset_id"]
            for r in conn.execute(
                "SELECT asset_id FROM image_asset_dino_predictions "
                "WHERE anchors_kind='2eur_commemo' LIMIT 200"
            )
        ]
        assert ids, "aucune prédiction DINO en base"
        for aid in ids:
            signals = collect_signals(conn, aid)
            assert [s.expert for s in signals] == ["text", "dino", "crop_quality"]
            by = {s.expert: s for s in signals}
            view = compute_auto_validate_view(conn, aid)
            reconstructed = _verdict_from_signals(
                face=None,
                target=by["dino"].raw["target"],
                top1=by["dino"].raw["top1"],
                sim=by["dino"].raw["sim"],
                spread=by["dino"].raw["spread"],
                text_verdict=by["text"].raw["vs_target_verdict"],
            )
            assert reconstructed.level == view.level
            assert reconstructed.reason == view.reason
    finally:
        conn.close()
