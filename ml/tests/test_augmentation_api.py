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
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh TestClient with a temp SQLite DB (Modèle B : aucune dépendance Supabase)."""
    from store import Store

    test_store = Store(tmp_path / "t.db")

    # Reset the augmentation module's bound state, then re-bind with our store.
    import serving.augmentation_routes as ar

    ar.bind(test_store)
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
    assert len(layers) == 4
    assert {l["type"] for l in layers} == {"background", "perspective", "relighting", "overlays"}
    assert data["zones"] == ["green", "orange", "red"]
    assert data["default_recipe"]["count"] > 0
    assert data["limits"]["preview_count_max"] == 64


def test_get_overlays(client: TestClient):
    resp = client.get("/augmentation/overlays")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"patina", "dust", "scratches", "fingerprints"}


# NB : le CRUD des recettes a migré vers le router LÉGER canonique
# (``serving.recipe_routes`` → ``/recipes``). Ses tests vivent dans
# ``test_recipe_routes.py``. Ici on ne garde que le rendu lourd (schema/overlays/
# preview), qui reste servi par ``augmentation_routes`` sur le ML local :8042.


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
