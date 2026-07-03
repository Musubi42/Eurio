"""Tests C2a local-sync — chaque mutation autoritative émet un event REJOUABLE.

Contrat vérifié : le dernier event porte ``detail_json.fields`` dont les valeurs
sont EXACTEMENT celles écrites en base (pas l'intention — la valeur), et une
entrée ``sync_outbox`` pending existe. Couvre les endpoints lab (TestClient) et
les writes review lean (fonctions directes).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402


def _seed_asset(conn, *, asset_id="a1", eurio="fr-2018-x", status="needs_review"):
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value, "
        " is_commemorative) VALUES (?, 'FR', 2018, 2.0, 1)",
        (eurio,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO source_images (id, source, source_ref, target_eurio_id) "
        "VALUES ('si1','ebay','ref1',?)",
        (eurio,),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, eurio_id, "
        " resolution_status) VALUES (?, 'si1', 'crops/x.jpg', ?, ?)",
        (asset_id, eurio, status),
    )


def _last_event(conn, asset_id="a1"):
    return conn.execute(
        "SELECT * FROM image_state_events WHERE asset_id=? ORDER BY id DESC LIMIT 1",
        (asset_id,),
    ).fetchone()


def _fields(ev) -> dict:
    body = json.loads(ev["detail_json"])
    assert body["v"] == 1
    return body["fields"]


def _assert_outbox_pending(conn, op_id):
    row = conn.execute(
        "SELECT status FROM sync_outbox WHERE op_id=?", (op_id,),
    ).fetchone()
    assert row is not None and row["status"] == "pending"


@pytest.fixture()
def lab(tmp_path, monkeypatch):
    import serving.lab_routes as lr

    store = Store(tmp_path / "t.db")
    lr.bind(store, object())  # runner inutile pour ces endpoints
    conn = store._connection()  # noqa: SLF001
    _seed_asset(conn)
    app = FastAPI()
    app.include_router(lr.router)
    with TestClient(app) as c:
        yield c, conn


# ─── Lab : funnel classification ─────────────────────────────────────────────


def test_training_eligible_emits_replayable_fields(lab):
    c, conn = lab
    r = c.post("/lab/assets/a1/training-eligible", json={"eligible": False})
    assert r.status_code == 200
    ev = _last_event(conn)
    assert ev["reason"] == "training_eligible"
    row = conn.execute(
        "SELECT training_eligible, quality_reason FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert _fields(ev) == {
        "image_assets.training_eligible": row["training_eligible"],
        "image_assets.quality_reason": row["quality_reason"],
    }
    _assert_outbox_pending(conn, ev["op_id"])

    # Ré-inclusion : quality_reason manual_triage effacé → fields = valeur relue.
    r = c.post("/lab/assets/a1/training-eligible", json={"eligible": True})
    ev = _last_event(conn)
    assert _fields(ev) == {
        "image_assets.training_eligible": 1,
        "image_assets.quality_reason": None,
    }


def test_reassign_emits_eurio_id(lab):
    c, conn = lab
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value, "
        " is_commemorative) VALUES ('de-2019-y', 'DE', 2019, 2.0, 1)"
    )
    r = c.post("/lab/assets/a1/reassign", json={"eurio_id": "de-2019-y"})
    assert r.status_code == 200
    ev = _last_event(conn)
    assert ev["reason"] == "reassign"
    assert ev["eurio_id"] == "de-2019-y"
    assert _fields(ev) == {"image_assets.eurio_id": "de-2019-y"}
    body = json.loads(ev["detail_json"])
    assert body["previous_eurio_id"] == "fr-2018-x"
    _assert_outbox_pending(conn, ev["op_id"])


def test_accept_training_fields_match_db(lab):
    c, conn = lab
    r = c.post("/lab/assets/a1/accept-training")
    assert r.status_code == 200
    ev = _last_event(conn)
    assert ev["reason"] == "accepted_from_training_set"
    f = _fields(ev)
    row = conn.execute(
        "SELECT resolution_status, resolution_confidence, training_eligible, "
        "resolved_at FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert f["image_assets.resolution_status"] == row["resolution_status"]
    assert f["image_assets.resolution_confidence"] == row["resolution_confidence"]
    assert f["image_assets.training_eligible"] == row["training_eligible"]
    assert f["image_assets.resolved_at"] == row["resolved_at"]
    assert f["review_queue.status"] == "done"


def test_reopen_review_fields_match_db(lab):
    c, conn = lab
    r = c.post("/lab/assets/a1/reopen-review")
    assert r.status_code == 200
    ev = _last_event(conn)
    assert ev["reason"] == "reopened_from_training_set"
    f = _fields(ev)
    rq = conn.execute(
        "SELECT * FROM review_queue WHERE image_asset_id='a1'"
    ).fetchone()
    assert f["image_assets.resolution_status"] == "needs_review"
    assert f["image_assets.training_eligible"] == 0
    for col in ("status", "priority", "enqueued_at", "kind", "decision_notes",
                "lane", "lane_source", "decided_eurio_id", "decided_at"):
        assert f[f"review_queue.{col}"] == rq[col], col


def test_intruder_dismiss_emits_best_effort_fields(lab):
    c, conn = lab
    r = c.post("/lab/assets/a1/intruder-dismiss")
    assert r.status_code == 200
    ev = _last_event(conn)
    assert ev["reason"] == "intruder_dismiss"
    assert _fields(ev) == {"cohort_training_scan_results.dismissed": 1}


# ─── Review writes lean (fonctions directes) ─────────────────────────────────


@pytest.fixture()
def review_conn(tmp_path):
    store = Store(tmp_path / "r.db")
    conn = store._connection()  # noqa: SLF001
    _seed_asset(conn)
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, priority, "
        "enqueued_at, kind) VALUES ('rq1', 'a1', 'open', 10, datetime('now'), "
        "'single')"
    )
    return conn


def _lean_client(conn):
    """Monte le router lean writes avec la conn de test injectée."""
    from serving import deps
    from serving.auth_principal import Principal
    from serving.review_queue import writes

    app = FastAPI()
    app.include_router(writes.router)
    app.dependency_overrides[deps.db_connection] = lambda: conn
    app.dependency_overrides[writes._require_write] = lambda: Principal(  # noqa: SLF001
        user_id="test", email="t@t", roles=["owner"], scopes={"review:write"},
    )
    return TestClient(app)


def test_decide_review_fields_match_db(review_conn):
    c = _lean_client(review_conn)
    r = c.post(
        "/review-queue/rq1/decide",
        json={"eurio_id": "fr-2018-x", "face": "obverse", "notes": "ok"},
    )
    assert r.status_code == 200, r.text
    ev = _last_event(review_conn)
    assert ev["reason"] == "human_decided"
    f = _fields(ev)
    a = review_conn.execute("SELECT * FROM image_assets WHERE id='a1'").fetchone()
    rq = review_conn.execute("SELECT * FROM review_queue WHERE id='rq1'").fetchone()
    assert f["image_assets.eurio_id"] == a["eurio_id"]
    assert f["image_assets.face"] == a["face"]
    assert f["image_assets.resolution_status"] == "manual"
    assert f["image_assets.resolved_at"] == a["resolved_at"]
    assert f["review_queue.status"] == rq["status"] == "done"
    assert f["review_queue.decided_by"] == rq["decided_by"]
    assert f["review_queue.decision_metadata_json"] == rq["decision_metadata_json"]
    _assert_outbox_pending(review_conn, ev["op_id"])


def test_reject_review_fields_match_db(review_conn):
    c = _lean_client(review_conn)
    r = c.post("/review-queue/rq1/reject", json={"reason": "not_a_coin"})
    assert r.status_code == 200, r.text
    ev = _last_event(review_conn)
    f = _fields(ev)
    a = review_conn.execute("SELECT * FROM image_assets WHERE id='a1'").fetchone()
    assert f["image_assets.resolution_status"] == a["resolution_status"] == "rejected"
    assert f["image_assets.quality_reason"] == a["quality_reason"] == "not_a_coin"
    assert f["image_assets.training_eligible"] == 0


def test_skip_review_fields_match_db(review_conn):
    c = _lean_client(review_conn)
    r = c.post("/review-queue/rq1/skip")
    assert r.status_code == 200, r.text
    ev = _last_event(review_conn)
    f = _fields(ev)
    rq = review_conn.execute("SELECT * FROM review_queue WHERE id='rq1'").fetchone()
    assert f["review_queue.priority"] == rq["priority"]
    assert f["review_queue.decision_notes"] == "skipped"


def test_restore_rejected_fields_match_db(review_conn):
    c = _lean_client(review_conn)
    c.post("/review-queue/rq1/reject")
    r = c.post("/review-queue/restore", json={"review_ids": ["rq1"]})
    assert r.status_code == 200, r.text
    assert r.json()["restored"] == 1
    ev = _last_event(review_conn)
    assert ev["reason"] == "restored"
    f = _fields(ev)
    a = review_conn.execute("SELECT * FROM image_assets WHERE id='a1'").fetchone()
    rq = review_conn.execute("SELECT * FROM review_queue WHERE id='rq1'").fetchone()
    assert f["image_assets.resolution_status"] == a["resolution_status"] == "needs_review"
    assert f["image_assets.quality_reason"] is None
    assert f["review_queue.status"] == rq["status"] == "open"
    assert f["review_queue.priority"] == rq["priority"]
