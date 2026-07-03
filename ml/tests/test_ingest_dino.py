"""C4d — `POST /ingest/dino` : write-half SQL-pure des prédictions Dino.

Miroir de ``test_ingest_crops.py`` (C2b/C3) : UPSERT idempotent, tolérance aux
asset_id inconnus (``missing``), préservation de ``run_id`` backfill existant,
scope ``ingest:write``.
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


def _pred(asset_id, **over):
    base = dict(
        asset_id=asset_id, encoder_version="dinov2-vits14",
        anchors_kind="2eur_commemo", anchors_count=42,
        top_k=[{"eurio_id": "fr-2001-2eur-x", "sim": 0.9}],
        top1_eurio_id="fr-2001-2eur-x", top1_sim=0.9,
    )
    base.update(over)
    return base


def test_ingest_dino_writes_row(env):
    conn, client = env
    _seed_asset(conn, "a1")
    r = client.post("/ingest/dino", json={"predictions": [_pred("a1")]})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 1, "missing": []}
    row = conn.execute(
        "SELECT top1_eurio_id, top1_sim, anchors_count FROM image_asset_dino_predictions "
        "WHERE asset_id='a1' AND encoder_version='dinov2-vits14' AND anchors_kind='2eur_commemo'"
    ).fetchone()
    assert row["top1_eurio_id"] == "fr-2001-2eur-x"
    assert row["top1_sim"] == 0.9
    assert row["anchors_count"] == 42


def test_unknown_asset_goes_to_missing(env):
    conn, client = env
    _seed_asset(conn, "a2")
    r = client.post("/ingest/dino", json={"predictions": [_pred("a2"), _pred("ghost")]})
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 1, "missing": ["ghost"]}


def test_idempotent_upsert(env):
    conn, client = env
    _seed_asset(conn, "a3")
    body = {"predictions": [_pred("a3", top1_sim=0.7)]}
    assert client.post("/ingest/dino", json=body).json() == {"updated": 1, "missing": []}
    assert client.post("/ingest/dino", json=body).json() == {"updated": 1, "missing": []}
    rows = conn.execute(
        "SELECT COUNT(*) FROM image_asset_dino_predictions WHERE asset_id='a3'"
    ).fetchone()[0]
    assert rows == 1  # PK composée (asset_id, encoder_version, anchors_kind) → pas de doublon


def test_preserves_existing_run_id_when_ingest_run_id_null(env):
    conn, client = env
    _seed_asset(conn, "a4")
    # backfill préalable avec run_id (simulate C4c ingest_run)
    from store.dino import DinoPredictionRow, _upsert_dino_rows_sql

    conn.execute("BEGIN")
    _upsert_dino_rows_sql(conn, [DinoPredictionRow(
        asset_id="a4", encoder_version="dinov2-vits14", anchors_kind="2eur_commemo",
        anchors_count=10, top_k=[], run_id="r1",  # 'r1' = run inséré par _seed_asset
    )])
    conn.execute("COMMIT")

    r = client.post("/ingest/dino", json={"predictions": [_pred("a4")]})
    assert r.status_code == 200, r.text
    row = conn.execute(
        "SELECT run_id, anchors_count FROM image_asset_dino_predictions WHERE asset_id='a4'"
    ).fetchone()
    assert row["run_id"] == "r1"  # préservé (COALESCE)
    assert row["anchors_count"] == 42  # le reste est bien mis à jour


def test_missing_scope_403(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:run"})  # pas ingest:write
    client = TestClient(app)
    _seed_asset(store._connection(), "a5")  # noqa: SLF001
    assert client.post("/ingest/dino", json={"predictions": [_pred("a5")]}).status_code == 403
