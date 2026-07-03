"""C2a — routes lean funnel (`serving/funnel_writes.py`) bout-en-bout.

Vérifie le câblage réel de l'image lean : dep `db_connection` (via EURIO_DB_PATH),
scope `review:write`, et que chaque endpoint mute bien la base. Le 403 valide le
durcissement auth. La logique SQL est testée séparément (test_decisions_parity).
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
from test_decisions_parity import _coin, _seed_asset


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["reviewer"],
        scopes=set(scopes), auth_method="api_token",
    )


def _make_client(db, scopes=("review:write",)):
    from serving import funnel_writes

    app = FastAPI()
    app.include_router(funnel_writes.router)
    app.dependency_overrides[require_principal] = lambda: _principal(scopes)
    return TestClient(app)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    return conn, db


def test_accept_training(env):
    conn, db = env
    _seed_asset(conn, "a1")
    client = _make_client(db)
    r = client.post("/lab/assets/a1/accept-training")
    assert r.status_code == 200, r.text
    assert r.json()["training_eligible"] is True
    row = conn.execute("SELECT resolution_status, training_eligible FROM image_assets WHERE id='a1'").fetchone()
    assert row["resolution_status"] == "manual" and row["training_eligible"] == 1


def test_training_eligible_toggle(env):
    conn, db = env
    _seed_asset(conn, "a2", training=1)
    client = _make_client(db)
    assert client.post("/lab/assets/a2/training-eligible", json={"eligible": False}).status_code == 200
    assert conn.execute("SELECT training_eligible FROM image_assets WHERE id='a2'").fetchone()[0] == 0


def test_reopen_review(env):
    conn, db = env
    _seed_asset(conn, "a3", status="manual", training=1, rq_status="done")
    client = _make_client(db)
    r = client.post("/lab/assets/a3/reopen-review")
    assert r.status_code == 200, r.text
    assert conn.execute("SELECT resolution_status FROM image_assets WHERE id='a3'").fetchone()[0] == "needs_review"


def test_reassign(env):
    conn, db = env
    _seed_asset(conn, "a4", eurio_id="fr-2001-2eur-x")
    _coin(conn, "fr-2002-2eur-y")
    client = _make_client(db)
    r = client.post("/lab/assets/a4/reassign", json={"eurio_id": "fr-2002-2eur-y"})
    assert r.status_code == 200, r.text
    assert conn.execute("SELECT eurio_id FROM image_assets WHERE id='a4'").fetchone()[0] == "fr-2002-2eur-y"


def test_reassign_unknown_coin_404(env):
    conn, db = env
    _seed_asset(conn, "a5")
    client = _make_client(db)
    assert client.post("/lab/assets/a5/reassign", json={"eurio_id": "nope"}).status_code == 404


def test_accept_training_idempotent(env):
    conn, db = env
    _seed_asset(conn, "a6")
    client = _make_client(db)
    assert client.post("/lab/assets/a6/accept-training").status_code == 200
    # rejeu : la row review est déjà 'done' → no-op, toujours 200 (write-behind C3)
    assert client.post("/lab/assets/a6/accept-training").status_code == 200


def test_missing_scope_403(env):
    conn, db = env
    _seed_asset(conn, "a7")
    client = _make_client(db, scopes=())  # authentifié mais sans review:write
    assert client.post("/lab/assets/a7/accept-training").status_code == 403
