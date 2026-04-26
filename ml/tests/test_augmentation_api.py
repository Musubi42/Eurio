"""FastAPI integration tests for /augmentation/* (Bloc 1).

Uses a temporary SQLite store + a patched supabase fetcher that raises. The
/preview endpoint is NOT exercised here (it would require a real obverse
image) — that path is covered manually by running the app.

Run: `.venv/bin/python -m pytest ml/tests/test_augmentation_api.py -q`
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh TestClient with a temp SQLite DB and no supabase dependency."""
    from state import Store

    test_store = Store(tmp_path / "t.db")

    # Reset the augmentation module's bound state, then re-bind with our store.
    import api.augmentation_routes as ar

    def _no_supabase():
        raise HTTPException(
            status_code=503, detail="Supabase disabled in tests"
        )

    ar.bind(test_store, _no_supabase)
    # Point cleanup to a temp tree to avoid touching real ml/output.
    monkeypatch.setattr(ar, "PREVIEW_ROOT", tmp_path / "previews")

    # Build a minimal FastAPI app with only the augmentation router — avoids
    # booting the entire server (which loads supabase + training_runner).
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(ar.router)

    with TestClient(app) as c:
        yield c


def test_get_schema(client: TestClient):
    resp = client.get("/augmentation/schema")
    assert resp.status_code == 200
    data = resp.json()
    layers = data["layers"]
    assert len(layers) == 3
    assert {l["type"] for l in layers} == {"perspective", "relighting", "overlays"}
    assert data["zones"] == ["green", "orange", "red"]
    assert data["default_recipe"]["count"] > 0
    assert data["limits"]["preview_count_max"] == 64


def test_get_overlays(client: TestClient):
    resp = client.get("/augmentation/overlays")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"patina", "dust", "scratches", "fingerprints"}


def test_recipe_crud(client: TestClient):
    # Create
    payload = {
        "name": "test-recipe",
        "zone": "orange",
        "config": {
            "count": 16,
            "layers": [
                {"type": "perspective", "max_tilt_degrees": 10, "probability": 0.5}
            ],
        },
    }
    resp = client.post("/augmentation/recipes", json=payload)
    assert resp.status_code == 200, resp.json()
    created = resp.json()
    assert created["name"] == "test-recipe"
    assert created["zone"] == "orange"
    recipe_id = created["id"]

    # Duplicate name → 409
    dup = client.post("/augmentation/recipes", json=payload)
    assert dup.status_code == 409

    # Get by id AND by name
    by_id = client.get(f"/augmentation/recipes/{recipe_id}")
    by_name = client.get("/augmentation/recipes/test-recipe")
    assert by_id.status_code == 200 and by_name.status_code == 200
    assert by_id.json()["id"] == by_name.json()["id"]

    # List filtered by zone
    listed = client.get("/augmentation/recipes?zone=orange")
    assert listed.status_code == 200
    assert any(r["id"] == recipe_id for r in listed.json())

    # Update
    upd = client.put(
        f"/augmentation/recipes/{recipe_id}",
        json={"zone": "red"},
    )
    assert upd.status_code == 200
    assert upd.json()["zone"] == "red"

    # Delete
    dele = client.delete(f"/augmentation/recipes/{recipe_id}")
    assert dele.status_code == 200
    missing = client.get(f"/augmentation/recipes/{recipe_id}")
    assert missing.status_code == 404


def test_create_recipe_rejects_bad_bounds(client: TestClient):
    payload = {
        "name": "bad-recipe",
        "config": {"layers": [{"type": "relighting", "ambient": 1.5}]},
    }
    resp = client.post("/augmentation/recipes", json=payload)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["param"] == "ambient"


def test_create_recipe_rejects_unknown_layer(client: TestClient):
    payload = {
        "name": "bad-layer",
        "config": {"layers": [{"type": "wat"}]},
    }
    resp = client.post("/augmentation/recipes", json=payload)
    assert resp.status_code == 400


def test_create_recipe_rejects_bad_name(client: TestClient):
    payload = {
        "name": "Not_kebab-case",
        "config": {"layers": []},
    }
    resp = client.post("/augmentation/recipes", json=payload)
    assert resp.status_code == 400


def test_preview_count_cap(client: TestClient):
    payload = {
        "recipe": {"layers": [{"type": "perspective"}]},
        "eurio_id": "dummy",
        "count": 200,
    }
    resp = client.post("/augmentation/preview", json=payload)
    assert resp.status_code == 400
    assert "cap" in resp.json()["detail"].lower()


def test_preview_missing_source_identifier(client: TestClient):
    payload = {
        "recipe": {"layers": [{"type": "perspective"}]},
        "count": 4,
    }
    resp = client.post("/augmentation/preview", json=payload)
    assert resp.status_code == 400


def test_preview_invalid_recipe(client: TestClient):
    payload = {
        "recipe": {"layers": [{"type": "relighting", "ambient": 10.0}]},
        "eurio_id": "dummy",
        "count": 4,
    }
    resp = client.post("/augmentation/preview", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"]["param"] == "ambient"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
