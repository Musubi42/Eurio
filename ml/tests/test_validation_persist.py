"""Persistance du verdict de consensus (``consensus_verdicts``).

Vérifie l'upsert versionné : écriture, REPLACE sur même (asset, version),
coexistence des versions, snapshot signals_json, relecture, abstention si pas
de signal. DB en mémoire bootstrappée depuis le schema réel (la contrainte FK
sur image_assets est désactivée — on teste la table verdict isolément).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from review.validation.consensus import RULE_VERSION, consensus_verdict
from review.validation.experts import CropQuality, crop_signal, dino_signal, text_signal
from review.validation.persist import (
    load_consensus_verdict,
    upsert_consensus_verdict,
)

_SCHEMA = Path(__file__).resolve().parent.parent / "state" / "schema.sql"
_GOOD = CropQuality(None, None, 0.95, None)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA.read_text())
    return c


def _signals(text_verdict, *, target, top1, sim, spread, crop=_GOOD):
    return [
        text_signal(text_verdict),
        dino_signal(target=target, top1=top1, sim=sim, spread=spread),
        crop_signal(crop),
    ]


def test_upsert_writes_one_row_and_reads_back(conn):
    sig = _signals("convergent", target="fr-x", top1="fr-x", sim=0.9, spread=0.1)
    cv = upsert_consensus_verdict(conn, "asset-1", signals=sig)
    assert cv is not None and cv.rule == "strong_accept"

    n = conn.execute("SELECT COUNT(*) FROM consensus_verdicts").fetchone()[0]
    assert n == 1
    loaded = load_consensus_verdict(conn, "asset-1")
    assert loaded == cv


def test_rerun_same_version_replaces_not_duplicates(conn):
    # 1er verdict : strong_accept.
    upsert_consensus_verdict(
        conn, "asset-1",
        signals=_signals("convergent", target="fr-x", top1="fr-x", sim=0.9, spread=0.1),
    )
    # Re-run avec un crop tilté → crop_cap (needs_review). Même (asset, version).
    cv2 = upsert_consensus_verdict(
        conn, "asset-1",
        signals=_signals("convergent", target="fr-x", top1="fr-x", sim=0.9,
                         spread=0.1, crop=CropQuality(40.0, 1, None, None)),
    )
    rows = conn.execute(
        "SELECT outcome, rule FROM consensus_verdicts WHERE image_asset_id='asset-1'"
    ).fetchall()
    assert len(rows) == 1  # REPLACE, pas un 2e INSERT
    assert rows[0] == ("needs_review", "crop_cap") == (cv2.outcome, cv2.rule)


def test_distinct_rule_versions_coexist(conn):
    sig = _signals("convergent", target="fr-x", top1="fr-x", sim=0.9, spread=0.1)
    upsert_consensus_verdict(conn, "asset-1", signals=sig, rule_version=1)
    upsert_consensus_verdict(conn, "asset-1", signals=sig, rule_version=2)
    n = conn.execute(
        "SELECT COUNT(*) FROM consensus_verdicts WHERE image_asset_id='asset-1'"
    ).fetchone()[0]
    assert n == 2


def test_signals_json_snapshot_round_trips(conn):
    sig = _signals("contradict", target="fr-x", top1="de-y", sim=0.9, spread=0.1)
    upsert_consensus_verdict(conn, "asset-1", signals=sig)
    raw = conn.execute(
        "SELECT signals_json FROM consensus_verdicts WHERE image_asset_id='asset-1'"
    ).fetchone()[0]
    snap = json.loads(raw)
    assert {s["expert"] for s in snap} == {"text", "dino", "crop_quality"}
    dino = next(s for s in snap if s["expert"] == "dino")
    assert dino["label"] == "mismatch" and dino["raw"]["top1"] == "de-y"


def test_no_signal_writes_nothing(conn):
    cv = upsert_consensus_verdict(conn, "ghost", signals=[])
    assert cv is None
    n = conn.execute("SELECT COUNT(*) FROM consensus_verdicts").fetchone()[0]
    assert n == 0


def test_persisted_verdict_matches_consensus_verdict(conn):
    sig = _signals("contradict", target="fr-x", top1="fr-x", sim=0.9, spread=0.1)
    expected = consensus_verdict(sig)  # text_contradict_rescue
    cv = upsert_consensus_verdict(conn, "asset-1", signals=sig)
    assert (cv.outcome, cv.lane, cv.rule) == (
        expected.outcome, expected.lane, expected.rule
    )
    assert load_consensus_verdict(conn, "asset-1").rule == "text_contradict_rescue"
