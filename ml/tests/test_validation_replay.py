"""Gold de replay — build relabellisé (2026-06-15).

Verrouille les invariants du relabel mix-zone-17 :
- une décision **admin** = label fiable, **même hors scope DINO** (standards inclus —
  c'était le bug « standards non mesurables ») ;
- les assets mix-zone-17 non décidés-admin = **diff-only** (ground_truth None) et
  apparaissent dans la worklist de relabel ;
- ``dino_in_scope`` reflète la présence d'une prédiction dans la banque du VERDICT.

``_snapshot`` est monkeypatché (le verdict lui-même est testé ailleurs) → on isole
la logique de sélection/étiquetage.

Run: `.venv/bin/python -m pytest ml/tests/test_validation_replay.py -q`
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from review.validation import replay  # noqa: E402
from shared.verdict_scope import (  # noqa: E402
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
)
from review.validation.replay import MIX_ZONE_17, build_gold, relabel_worklist  # noqa: E402

_SCHEMA = ML_DIR / "state" / "schema.sql"


@pytest.fixture
def conn(monkeypatch) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA.read_text())
    # _snapshot isolé : le verdict réel est couvert par test_validation_consensus.
    monkeypatch.setattr(
        replay, "_snapshot",
        lambda conn, aid, **_: ("unknown", "manual", {"text": "absent"}, []),
    )
    return c


def _asset(c, aid, run_id, status):
    c.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, resolution_status, "
        " variant_kind, training_eligible, storage_path, fetched_at, storage_status, run_id) "
        "VALUES (?, ?, 0, ?, 'unknown', 0, 'p', 't', 'present', ?)",
        (aid, f"si-{aid}", status, run_id),
    )


def _admin_decision(c, aid, eurio_id):
    c.execute(
        "INSERT INTO review_queue (id, image_asset_id, priority, status, enqueued_at, "
        " decision_metadata_json, lane_source, decided_by, decided_eurio_id) "
        "VALUES (?, ?, 0, 'done', 't', '{}', 'human', 'admin', ?)",
        (f"rq-{aid}", aid, eurio_id),
    )


def _dino(c, aid):
    c.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, anchors_kind, "
        " anchors_count, top_k_json, computed_at) "
        "VALUES (?, ?, ?, 1, '[]', 't')",
        (aid, VERDICT_ENCODER_VERSION, VERDICT_ANCHORS_KIND),
    )


def _seed(c):
    # cohort_jobs = bookkeeping LOCAL (split) : seed dans le store d'état local
    # (EURIO_LOCAL_STATE_DB isolé par le conftest), que lit replay._mix_zone_assets.
    from store import local_state_store
    local_state_store()._connection().execute(
        "INSERT INTO cohort_jobs (id, kind, cohort_id, status, n_done, n_produced, "
        " n_attributed_target, started_at, run_id, target_eurio_id) "
        "VALUES ('j1', 'scrape_ebay', ?, 'done', 0, 0, 0, 't', 'run-mz', 'x')",
        (MIX_ZONE_17,),
    )
    # commemo admin-décidé, in-scope dino
    _asset(c, "a-commemo", "run-mz", "manual"); _admin_decision(c, "a-commemo", "fr-2016-commemo"); _dino(c, "a-commemo")
    # standard admin-décidé, HORS scope dino (le cas qui était droppé)
    _asset(c, "a-standard", "run-mz", "manual"); _admin_decision(c, "a-standard", "at-2002-standard")
    # mix-zone-17 non décidé-admin → diff-only + worklist
    _asset(c, "a-needsrev", "run-mz", "needs_review")
    # admin-décidé hors cohorte → provenance human_admin
    _asset(c, "a-other", "run-other", "manual"); _admin_decision(c, "a-other", "de-2007-commemo")
    c.commit()


def test_build_labels_admin_including_out_of_scope_standards(conn):
    _seed(conn)
    gold = {g.asset_id: g for g in build_gold(conn)}
    assert set(gold) == {"a-commemo", "a-standard", "a-needsrev", "a-other"}

    # admin → label fiable, peu importe le scope dino
    assert gold["a-commemo"].ground_truth_eurio_id == "fr-2016-commemo"
    assert gold["a-commemo"].source == "mix_zone_17"
    assert gold["a-commemo"].dino_in_scope is True

    # LE FIX : standard décidé-admin hors scope dino = quand même labellisé
    assert gold["a-standard"].ground_truth_eurio_id == "at-2002-standard"
    assert gold["a-standard"].dino_in_scope is False

    # non décidé-admin → diff-only
    assert gold["a-needsrev"].ground_truth_eurio_id is None
    assert gold["a-needsrev"].source == "mix_zone_17"

    # provenance human_admin hors cohorte
    assert gold["a-other"].ground_truth_eurio_id == "de-2007-commemo"
    assert gold["a-other"].source == "human_admin"


def test_worklist_lists_unlabeled_mix_zone_assets(conn):
    _seed(conn)
    wl = relabel_worklist(conn)
    ids = [r["asset_id"] for r in wl]
    # seul l'asset mix-zone-17 non décidé-admin doit y être (les décidés-admin exclus)
    assert ids == ["a-needsrev"]
    assert wl[0]["resolution_status"] == "needs_review"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
