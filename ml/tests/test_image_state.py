"""Tests du modèle d'état explicite des crops — emit_state_event (chunk C2).

Vérifie : création de l'état courant au 1er event, transition (from_state résolu +
UPSERT current + last_event_id), pose de l'eurio_id, héritage COALESCE du
target_eurio_id, et garde-fou warn-and-write sur transition illégale.
"""

from __future__ import annotations

import logging

import pytest

from store import Store, emit_state_event


def _seed_asset(conn, *, asset_id="a1", target="fr-2018-x", eurio=None):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id) "
        "VALUES ('si1','ebay','ref1',?)",
        (target,),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, eurio_id) "
        "VALUES (?, 'si1', 'crops/x.jpg', ?)",
        (asset_id, eurio),
    )


@pytest.fixture()
def conn(tmp_path):
    store = Store(tmp_path / "t.db")
    c = store._connection()  # noqa: SLF001
    _seed_asset(c)
    return c


def _current(conn, asset_id="a1"):
    return conn.execute(
        "SELECT * FROM image_state_current WHERE asset_id=?", (asset_id,)
    ).fetchone()


def _events(conn, asset_id="a1"):
    return conn.execute(
        "SELECT * FROM image_state_events WHERE asset_id=? ORDER BY id", (asset_id,)
    ).fetchall()


def test_first_event_creates_current(conn):
    eid = emit_state_event(
        conn, asset_id="a1", to_state="detected", actor="pipeline",
        reason="crop_detected", target_eurio_id="fr-2018-x",
    )
    cur = _current(conn)
    assert cur["current_state"] == "detected"
    assert cur["last_event_id"] == eid
    assert cur["target_eurio_id"] == "fr-2018-x"
    assert cur["actor"] == "pipeline"
    evs = _events(conn)
    assert len(evs) == 1
    assert evs[0]["from_state"] is None
    assert evs[0]["to_state"] == "detected"


def test_transition_resolves_from_state_and_inherits_target(conn):
    emit_state_event(conn, asset_id="a1", to_state="detected", actor="pipeline",
                     target_eurio_id="fr-2018-x")
    emit_state_event(conn, asset_id="a1", to_state="queued", actor="pipeline",
                     reason="enqueued")  # pas de target → hérité par COALESCE
    cur = _current(conn)
    assert cur["current_state"] == "queued"
    assert cur["target_eurio_id"] == "fr-2018-x"  # conservé
    evs = _events(conn)
    assert len(evs) == 2
    assert evs[1]["from_state"] == "detected"
    assert evs[1]["to_state"] == "queued"


def test_resolved_sets_eurio_id(conn):
    emit_state_event(conn, asset_id="a1", to_state="detected", actor="pipeline")
    emit_state_event(conn, asset_id="a1", to_state="queued", actor="pipeline")
    emit_state_event(conn, asset_id="a1", to_state="resolved", actor="human",
                     reason="human_decided", eurio_id="fr-2018-x-classic")
    cur = _current(conn)
    assert cur["current_state"] == "resolved"
    assert cur["eurio_id"] == "fr-2018-x-classic"
    assert cur["actor"] == "human"
    assert _events(conn)[-1]["eurio_id"] == "fr-2018-x-classic"


def test_illegal_transition_warns_but_writes(conn, caplog):
    emit_state_event(conn, asset_id="a1", to_state="detected", actor="pipeline")
    with caplog.at_level(logging.WARNING, logger="state.store"):
        emit_state_event(conn, asset_id="a1", to_state="resolved", actor="human",
                         reason="oops")  # detected → resolved : illégal
    assert any("transition inattendue" in r.message for r in caplog.records)
    # warn-and-write : l'écriture a quand même eu lieu (on observe, on ne casse pas).
    assert _current(conn)["current_state"] == "resolved"
    assert len(_events(conn)) == 2


def test_unknown_state_raises(conn):
    with pytest.raises(ValueError):
        emit_state_event(conn, asset_id="a1", to_state="bogus", actor="human")


def test_cohort_job_lifecycle(tmp_path):
    from store import (
        Store, cohort_job_finish, cohort_job_progress, cohort_job_start,
    )

    store = Store(tmp_path / "j.db")
    c = store._connection()  # noqa: SLF001
    c.execute("INSERT INTO experiment_cohorts (id, name, eurio_ids_json) "
              "VALUES ('co1','c','[]')")
    jid = cohort_job_start(c, kind="recrop_zero", cohort_id="co1",
                           eurio_id="x", n_total=10, tau=0.55)
    row = c.execute("SELECT * FROM cohort_jobs WHERE id=?", (jid,)).fetchone()
    assert row["status"] == "running" and row["n_total"] == 10 and row["n_done"] == 0

    cohort_job_progress(c, jid, n_done=4)
    assert c.execute("SELECT n_done FROM cohort_jobs WHERE id=?", (jid,)).fetchone()[0] == 4

    cohort_job_finish(c, jid, status="done", n_done=10, n_produced=0,
                      note="épuisé à τ=0.55")
    r2 = c.execute("SELECT status, n_produced, note, finished_at "
                   "FROM cohort_jobs WHERE id=?", (jid,)).fetchone()
    assert r2["status"] == "done" and r2["n_produced"] == 0
    assert r2["note"] == "épuisé à τ=0.55" and r2["finished_at"] is not None


class TestDetailObservationnel:
    """``detail`` observe, ``detail_fields`` affecte — et la nuance compte.

    La bbox d'origine du détecteur est journalisée en ``detail`` (cf.
    ``sources/_base/steps/detect_crop.py``). Si elle passait par
    ``detail_fields``, le replay distant la RÉAFFECTERAIT à
    ``image_assets.bbox_json`` — et écraserait un recadrage humain arrivé
    entre-temps par un autre chemin. Ce test fige la distinction.
    """

    def test_detail_seul_ne_produit_ni_v_ni_fields(self, conn):
        import json

        emit_state_event(
            conn, asset_id="a1", to_state="detected", actor="pipeline",
            reason="crop_detected",
            detail={"bbox": {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
                    "detection_method": "hough"},
        )
        body = json.loads(_events(conn)[-1]["detail_json"])
        assert body["bbox"] == {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}
        assert body["detection_method"] == "hough"
        # Le replay distant ne matérialise que ce qui est sous "fields".
        assert "fields" not in body and "v" not in body

    def test_detail_fields_lui_produit_bien_v_et_fields(self, conn):
        import json

        emit_state_event(
            conn, asset_id="a1", to_state="queued", actor="human",
            reason="manual_recrop",
            detail_fields={"image_assets.bbox_json": "{}"},
        )
        body = json.loads(_events(conn)[-1]["detail_json"])
        assert body["v"] == 1 and "image_assets.bbox_json" in body["fields"]
