"""FastAPI integration tests for the LIGHT recipe CRUD (``serving.recipe_routes``).

Recipes are canonical metadata served by ``eurio-api`` (single writer). This
router imports **only** the Store + the pure validator — no cv2/torch — so the
test app mounts just that router against a temp SQLite Store.

Run: `.venv/bin/python -m pytest ml/tests/test_recipe_routes.py -q`
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


@pytest.fixture()
def client(tmp_path: Path):
    """Minimal app with only the light recipe router + a temp Store."""
    from serving import recipe_routes
    from store import Store

    recipe_routes.bind(Store(tmp_path / "t.db"))
    app = FastAPI()
    app.include_router(recipe_routes.router)
    with TestClient(app) as c:
        yield c


def test_recipe_crud(client: TestClient):
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
    resp = client.post("/recipes", json=payload)
    assert resp.status_code == 200, resp.json()
    created = resp.json()
    assert created["name"] == "test-recipe"
    assert created["zone"] == "orange"
    recipe_id = created["id"]

    # Duplicate name → 409
    dup = client.post("/recipes", json=payload)
    assert dup.status_code == 409

    # Get by id AND by name
    by_id = client.get(f"/recipes/{recipe_id}")
    by_name = client.get("/recipes/test-recipe")
    assert by_id.status_code == 200 and by_name.status_code == 200
    assert by_id.json()["id"] == by_name.json()["id"]

    # List filtered by zone
    listed = client.get("/recipes?zone=orange")
    assert listed.status_code == 200
    assert any(r["id"] == recipe_id for r in listed.json())

    # Update
    upd = client.put(f"/recipes/{recipe_id}", json={"zone": "red"})
    assert upd.status_code == 200
    assert upd.json()["zone"] == "red"

    # Delete
    dele = client.delete(f"/recipes/{recipe_id}")
    assert dele.status_code == 200
    missing = client.get(f"/recipes/{recipe_id}")
    assert missing.status_code == 404


def test_create_recipe_rejects_bad_bounds(client: TestClient):
    payload = {
        "name": "bad-recipe",
        "config": {"layers": [{"type": "relighting", "ambient": 1.5}]},
    }
    resp = client.post("/recipes", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"]["param"] == "ambient"


def test_create_recipe_rejects_unknown_layer(client: TestClient):
    payload = {"name": "bad-layer", "config": {"layers": [{"type": "wat"}]}}
    resp = client.post("/recipes", json=payload)
    assert resp.status_code == 400


def test_create_recipe_rejects_bad_name(client: TestClient):
    payload = {"name": "Not_kebab-case", "config": {"layers": []}}
    resp = client.post("/recipes", json=payload)
    assert resp.status_code == 400


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
