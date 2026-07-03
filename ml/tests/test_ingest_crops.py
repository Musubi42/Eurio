"""C2b — `POST /ingest/crops` : write-half SQL-pure de la géométrie de recrop.

Vérifie l'écriture des colonnes (bbox/method/dims/phash/storage_status), la
tolérance aux asset_id inconnus (``missing``), l'idempotence, le COALESCE de
storage_status, et le scope ``ingest:write``.
"""
from __future__ import annotations

import json
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


def _crop(asset_id, **over):
    base = dict(asset_id=asset_id, bbox_json=json.dumps({"x": 1, "y": 2, "w": 10, "h": 10}),
                detection_method="manual+lotcrop", width=224, height=224, phash=42)
    base.update(over)
    return base


def test_ingest_crops_writes_columns(env):
    conn, client = env
    _seed_asset(conn, "a1")
    r = client.post("/ingest/crops", json={"crops": [_crop("a1", storage_status="present")]})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 1, "missing": []}
    row = conn.execute(
        "SELECT bbox_json, detection_method, width, height, phash, storage_status "
        "FROM image_assets WHERE id='a1'").fetchone()
    assert row["detection_method"] == "manual+lotcrop"
    assert row["width"] == 224 and row["height"] == 224 and row["phash"] == 42
    assert row["storage_status"] == "present"
    ev = conn.execute(
        "SELECT reason, actor FROM image_state_events WHERE asset_id='a1' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert ev["reason"] == "recrop_ingest" and ev["actor"] == "pipeline"


def test_unknown_asset_goes_to_missing(env):
    conn, client = env
    _seed_asset(conn, "a2")
    r = client.post("/ingest/crops", json={"crops": [_crop("a2"), _crop("ghost")]})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 1, "missing": ["ghost"]}


def test_storage_status_coalesced_when_omitted(env):
    conn, client = env
    _seed_asset(conn, "a3")
    conn.execute("UPDATE image_assets SET storage_status='present' WHERE id='a3'")
    # payload sans storage_status → COALESCE préserve 'present'
    r = client.post("/ingest/crops", json={"crops": [_crop("a3")]})
    assert r.status_code == 200, r.text
    assert conn.execute("SELECT storage_status FROM image_assets WHERE id='a3'").fetchone()[0] == "present"


def test_idempotent(env):
    conn, client = env
    _seed_asset(conn, "a4")
    body = {"crops": [_crop("a4", storage_status="present")]}
    assert client.post("/ingest/crops", json=body).json() == {"updated": 1, "missing": []}
    before = conn.execute("SELECT bbox_json, phash, width FROM image_assets WHERE id='a4'").fetchone()
    assert client.post("/ingest/crops", json=body).status_code == 200
    after = conn.execute("SELECT bbox_json, phash, width FROM image_assets WHERE id='a4'").fetchone()
    assert tuple(before) == tuple(after)


def test_missing_scope_403(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:run"})  # pas ingest:write
    client = TestClient(app)
    _seed_asset(store._connection(), "a5")  # noqa: SLF001
    assert client.post("/ingest/crops", json={"crops": [_crop("a5")]}).status_code == 403


# ── /ingest/faces (C3 — remontée des verdicts face du scan Dino au VPS) ──────


def test_ingest_faces_writes_when_null(env):
    conn, client = env
    _seed_asset(conn, "f1")
    conn.execute("UPDATE image_assets SET face=NULL WHERE id='f1'")
    r = client.post("/ingest/faces", json={"faces": [{"asset_id": "f1", "face": "reverse"}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 1, "skipped": 0, "missing": []}
    assert conn.execute("SELECT face FROM image_assets WHERE id='f1'").fetchone()[0] == "reverse"
    ev = conn.execute(
        "SELECT reason, actor FROM image_state_events WHERE asset_id='f1' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert ev["reason"] == "face_ingest" and ev["actor"] == "pipeline"


def test_ingest_faces_skips_labeled(env):
    conn, client = env
    _seed_asset(conn, "f2")  # face='obverse' par défaut → garde NULL/unknown
    r = client.post("/ingest/faces", json={"faces": [{"asset_id": "f2", "face": "reverse"}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 0, "skipped": 1, "missing": []}
    assert conn.execute("SELECT face FROM image_assets WHERE id='f2'").fetchone()[0] == "obverse"


def test_ingest_faces_missing_and_scope(env, tmp_path):
    conn, client = env
    r = client.post("/ingest/faces", json={"faces": [{"asset_id": "ghost", "face": "obverse"}]})
    assert r.status_code == 200 and r.json()["missing"] == ["ghost"]
    # scope : ingest:run ne suffit pas (ingest:write requis)
    from serving import ingest_routes
    store2 = Store(tmp_path / "s2.db")
    ingest_routes.bind(store2)
    app2 = FastAPI()
    app2.include_router(ingest_routes.router)
    app2.dependency_overrides[require_principal] = lambda: _principal({"ingest:run"})
    _seed_asset(store2._connection(), "f3")  # noqa: SLF001
    assert TestClient(app2).post("/ingest/faces", json={"faces": [{"asset_id": "f3", "face": "obverse"}]}).status_code == 403
