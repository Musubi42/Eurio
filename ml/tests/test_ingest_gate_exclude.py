"""C4a — `POST /ingest/crops/exclude` + `POST /ingest/gate/reject`.

Ferme deux writers locaux « vivants » hors Direction A : l'exclusion de crops du
bench et le rejet du gate vision standard. Vérifie l'écriture canonique, la garde
d'appartenance au run, l'atomicité review_queue-first du reject, et le scope.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from store import Store
from test_decisions_parity import _seed_asset


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes=set(scopes), auth_method="api_token",
    )


@pytest.fixture()
def env(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:write"})
    return store._connection(), TestClient(app)  # noqa: SLF001


# ── /ingest/crops/exclude ────────────────────────────────────────────────────


def test_exclude_marks_training_ineligible(env):
    conn, client = env
    _seed_asset(conn, "a1", training=1)  # run_id='r1'
    r = client.post("/ingest/crops/exclude", json={"run_id": "r1", "asset_ids": ["a1"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"excluded": 1, "skipped": []}
    row = conn.execute(
        "SELECT training_eligible, quality_reason, resolution_status FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert row["training_eligible"] == 0
    assert row["quality_reason"] == "too_tilted"
    assert row["resolution_status"] == "needs_review"  # préservé (réversible)


def test_exclude_skips_non_run_asset(env):
    conn, client = env
    _seed_asset(conn, "a1")
    r = client.post("/ingest/crops/exclude", json={"run_id": "r1", "asset_ids": ["a1", "ghost"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"excluded": 1, "skipped": ["ghost"]}


def test_exclude_unknown_run_all_skipped(env):
    conn, client = env
    _seed_asset(conn, "a1")
    r = client.post("/ingest/crops/exclude", json={"run_id": "nope", "asset_ids": ["a1"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"excluded": 0, "skipped": ["a1"]}


def test_exclude_missing_scope_403(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:run"})
    _seed_asset(store._connection(), "a1")  # noqa: SLF001
    assert TestClient(app).post(
        "/ingest/crops/exclude", json={"run_id": "r1", "asset_ids": ["a1"]}
    ).status_code == 403


# ── /ingest/gate/reject ──────────────────────────────────────────────────────


def test_gate_reject_writes_three(env):
    conn, client = env
    _seed_asset(conn, "g1")  # rq_g1 open
    r = client.post("/ingest/gate/reject", json={
        "review_id": "rq_g1", "asset_id": "g1", "label": "junk", "confidence": 0.9,
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"written": True}
    ia = conn.execute(
        "SELECT resolution_status, training_eligible, quality_reason FROM image_assets WHERE id='g1'"
    ).fetchone()
    assert ia["resolution_status"] == "rejected"
    assert ia["training_eligible"] == 0
    assert ia["quality_reason"] == "vision_standard_gate"
    rq = conn.execute(
        "SELECT status, decided_by FROM review_queue WHERE id='rq_g1'"
    ).fetchone()
    assert rq["status"] == "done" and rq["decided_by"] == "vision_gate"
    ev = conn.execute(
        "SELECT to_state, actor, reason FROM image_state_events WHERE asset_id='g1' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert ev["to_state"] == "rejected" and ev["actor"] == "ccproxy"
    assert ev["reason"] == "vision_standard_gate:junk"


def test_gate_reject_already_closed_no_mutation(env):
    conn, client = env
    _seed_asset(conn, "g2", rq_status="done")  # review déjà close
    r = client.post("/ingest/gate/reject", json={
        "review_id": "rq_g2", "asset_id": "g2", "label": "junk", "confidence": 0.9,
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"written": False}
    # image_assets NON muté (review_queue vérifiée en premier)
    assert conn.execute(
        "SELECT resolution_status FROM image_assets WHERE id='g2'"
    ).fetchone()[0] == "needs_review"


def test_gate_reject_idempotent_second_call(env):
    conn, client = env
    _seed_asset(conn, "g3")
    body = {"review_id": "rq_g3", "asset_id": "g3", "label": "wrong_coin", "confidence": 0.88}
    assert client.post("/ingest/gate/reject", json=body).json() == {"written": True}
    # re-POST : la review est maintenant 'done' → written False, pas de double
    assert client.post("/ingest/gate/reject", json=body).json() == {"written": False}


def test_gate_reject_missing_scope_403(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:run"})
    _seed_asset(store._connection(), "g4")  # noqa: SLF001
    assert TestClient(app).post("/ingest/gate/reject", json={
        "review_id": "rq_g4", "asset_id": "g4", "label": "junk", "confidence": 0.9,
    }).status_code == 403


# ── client helpers : no-op quand sync désactivée ─────────────────────────────


def test_push_helpers_noop_without_sync(monkeypatch):
    import client.ingest as ci

    monkeypatch.delenv("EURIO_API_URL", raising=False)
    assert ci.push_exclude_crops("r1", ["a1"]) is None
    assert ci.push_gate_reject(
        review_id="rq", asset_id="a", label="junk", confidence=0.9,
        engine_version="vision_standard_gate_v1",
    ) is None
