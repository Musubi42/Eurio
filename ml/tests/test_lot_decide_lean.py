"""C2a — décision de lot sur l'image lean (`serving/funnel_writes.py`).

Vérifie que `/review-queue/lots/{key}/decide` est servie sur le lean (elle était
piégée derrière `import cv2` dans review_queue_routes) et applique correctement
decide/reject/skip + le tri des erreurs cross-listing.
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


def _client(db):
    from serving import funnel_writes

    app = FastAPI()
    app.include_router(funnel_writes.router)
    # `review:arbitrate`, PAS `review:write` : depuis e851a343, la décision de
    # lot écrit le canonique en direct sans quarantaine, donc elle est fermée au
    # scope d'un ami (cf. la note sur `_require_write` dans funnel_writes.py).
    # Un principal `review:write` ici rend 403 sur TOUTES les routes du module,
    # et le test ne mesure alors plus rien de ce qu'il croit mesurer.
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes={"review:arbitrate"}, auth_method="api_token",
    )
    return TestClient(app)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    return conn, db


def test_lot_decide_mixed(env):
    conn, db = env
    for i in range(3):
        _seed_asset(conn, f"L{i}", ebay_item="99", si_id="si_lot", crop_index=i)
    _coin(conn, "fr-2003-2eur-z")
    client = _client(db)

    r = client.post("/review-queue/lots/ebay_99/decide", json={"assignments": [
        {"asset_id": "L0", "eurio_id": "fr-2003-2eur-z", "face": "obverse"},
        {"asset_id": "L1", "reject_reason": "not_a_coin"},
        {"asset_id": "L2", "skip": True},
    ]})
    assert r.status_code == 200, r.text
    assert r.json() == {"done": 1, "rejected": 1, "skipped": 1, "errors": []}
    assert conn.execute("SELECT resolution_status FROM image_assets WHERE id='L0'").fetchone()[0] == "manual"
    assert conn.execute("SELECT resolution_status FROM image_assets WHERE id='L1'").fetchone()[0] == "rejected"


def test_lot_decide_foreign_asset_errors(env):
    conn, db = env
    _seed_asset(conn, "L0", ebay_item="100", si_id="si_a", crop_index=0)
    _seed_asset(conn, "X9", ebay_item="200", si_id="si_b", crop_index=0)
    _coin(conn, "fr-2003-2eur-z")
    client = _client(db)

    r = client.post("/review-queue/lots/ebay_100/decide", json={"assignments": [
        {"asset_id": "X9", "eurio_id": "fr-2003-2eur-z", "face": "obverse"},
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["done"] == 0
    assert [e["asset_id"] for e in body["errors"]] == ["X9"]
    assert any("n'appartient pas" in e["message"] for e in body["errors"])


def test_lot_decide_unknown_listing_404(env):
    conn, db = env
    client = _client(db)
    r = client.post("/review-queue/lots/ebay_nope/decide", json={"assignments": [
        {"asset_id": "z", "skip": True},
    ]})
    assert r.status_code == 404
