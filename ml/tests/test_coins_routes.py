"""Tests endpoints /coins/* + /sets/* (P.8a).

Stratégie : DB tmp seedée à minima (1 coin + relations), TestClient sur
l'app FastAPI rebound vers la DB tmp.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api import coins_routes, sets_routes  # noqa: E402
from state.store import Store  # noqa: E402


REAL_DB = ML_DIR / "state" / "eurio.db"


@pytest.fixture
def tmp_store(tmp_path: Path):
    """Copie la DB courante, bootstrap, rebind les routers, yield Store.

    IMPORTANT : on importe ``api.server`` AVANT le bind pour absorber le
    bind initial (qui pointerait vers eurio.db réelle). Ensuite, le rebind
    vers tmp prend effet pour la durée du test."""
    if not REAL_DB.exists():
        pytest.skip(f"eurio.db absent: {REAL_DB}")
    target = tmp_path / "eurio.db"
    shutil.copy2(REAL_DB, target)
    # Force initial wiring (no-op si déjà importé).
    from api import server as _server  # noqa: F401
    store = Store(target)
    coins_routes.bind(store)
    sets_routes.bind(store)
    yield store


@pytest.fixture
def seeded_store(tmp_store: Store) -> Store:
    """Seed 1 coin + 1 image + 1 cross_ref + 1 source_ref + 1 i18n + 1 alias
    + 1 market_quote + 1 embedding pour les tests d'endpoint."""
    conn = tmp_store._connection()
    eurio_id = "test-2025-2eur-fixture"
    conn.execute(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value, "
        "currency, is_commemorative, theme, numista_id) "
        "VALUES (?, 'eu', 'European Union', 2025, 2.0, 'EUR', 1, 'Test theme', 99999)",
        (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, url) "
        "VALUES (?, 'numista_api', 'obverse', 'https://example.com/o.jpg')",
        (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_cross_refs (eurio_id, ref_type, ref_value) "
        "VALUES (?, 'krause_mishler', 'KM-FIXTURE')", (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_source_refs (target_kind, target_id, source, source_native_id) "
        "VALUES ('coin', ?, 'numista_api', '99999')", (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_source_refs (target_kind, target_id, source, source_native_id) "
        "VALUES ('coin', ?, 'bce_official', 'bce-url')", (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_names_i18n (eurio_id, lang, title, source, method) "
        "VALUES (?, 'fr', 'Test', 'numista_api', NULL)", (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_aliases (eurio_id, lang, alias, source) "
        "VALUES (?, 'fr', 'alias_test', 'numista_api')", (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_market_quotes (id, eurio_id, source, condition_raw, "
        "condition_normalized, currency, p10, p50, p90, sample_size, period_start, period_end) "
        "VALUES ('q1', ?, 'numista_api', 'UNC', 'UNC', 'EUR', 5.0, 5.0, 5.0, 1, '2026-05-26', '2026-05-26')",
        (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_embeddings (eurio_id, model_version) VALUES (?, 'v2.0.0')",
        (eurio_id,),
    )
    return tmp_store


@pytest.fixture
def client() -> TestClient:
    from api.server import app
    return TestClient(app)


# ─── Lookups ──────────────────────────────────────────────────────────────


def test_lookups_trained(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/lookups/trained")
    assert resp.status_code == 200
    assert "test-2025-2eur-fixture" in resp.json()


def test_lookups_source_counts(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/lookups/source-counts")
    assert resp.status_code == 200
    data = resp.json()
    # Seed inséré : numista_api + bce_official sur 1 coin.
    assert data["numista"] >= 1
    assert data["bce"] >= 1
    assert "wikipedia" in data and "lmdlp" in data and "ebay" in data


# ─── Coin detail ──────────────────────────────────────────────────────────


def test_coin_detail(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/test-2025-2eur-fixture")
    assert resp.status_code == 200
    data = resp.json()
    assert data["eurio_id"] == "test-2025-2eur-fixture"
    assert data["country"] == "eu"
    assert data["face_value"] == 2.0
    assert data["is_commemorative"] is True
    assert data["cross_refs"] == {"krause_mishler": "KM-FIXTURE"}
    assert "numista_api" in data["sources_used"]
    assert "bce_official" in data["sources_used"]
    assert data["has_bce"] is True
    assert data["has_ebay"] is False
    assert len(data["images"]) == 1
    assert data["images"][0]["role"] == "obverse"


def test_coin_detail_not_found(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/nonexistent-id")
    assert resp.status_code == 404


def test_coin_i18n(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/test-2025-2eur-fixture/i18n")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["names"]) == 1
    assert data["names"][0]["lang"] == "fr"
    assert data["names"][0]["title"] == "Test"
    assert len(data["aliases"]) == 1
    assert data["aliases"][0]["alias"] == "alias_test"


def test_coin_prices(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/test-2025-2eur-fixture/prices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["type_level"]) == 1
    assert data["type_level"][0]["condition_normalized"] == "UNC"
    assert data["mint_release_level"] == []  # pas de mint_release seedé


def test_coin_embedding(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/test-2025-2eur-fixture/embedding")
    assert resp.status_code == 200
    assert resp.json() == {"model_version": "v2.0.0"}


def test_coin_embedding_none(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/nonexistent/embedding")
    assert resp.status_code == 200
    assert resp.json() == {"model_version": None}


def test_coin_series_none(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/test-2025-2eur-fixture/series")
    assert resp.status_code == 200
    assert resp.json() is None


def test_coin_patch_personal_owned(seeded_store: Store, client: TestClient) -> None:
    resp = client.patch(
        "/coins/test-2025-2eur-fixture",
        json={"personal_owned": True},
    )
    assert resp.status_code == 200
    assert resp.json()["personal_owned"] is True

    # Re-fetch confirme la persistance
    resp2 = client.get("/coins/test-2025-2eur-fixture")
    assert resp2.json()["personal_owned"] is True


def test_coin_patch_not_found(seeded_store: Store, client: TestClient) -> None:
    resp = client.patch("/coins/nonexistent", json={"personal_owned": True})
    assert resp.status_code == 404


# ─── Sets CRUD ────────────────────────────────────────────────────────────


def _new_set_payload(set_id: str = "test-set") -> dict:
    return {
        "id": set_id, "name_i18n": {"fr": "Mon Set", "en": "My Set"},
        "category": "theme", "kind": "static", "display_order": 0,
        "active": True,
    }


def test_sets_create_list_get(seeded_store: Store, client: TestClient) -> None:
    # Empty initially
    assert client.get("/sets").json() == []
    # Create
    resp = client.post("/sets", json=_new_set_payload("set-A"))
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "set-A"
    assert data["name_i18n"] == {"fr": "Mon Set", "en": "My Set"}
    # List
    assert len(client.get("/sets").json()) == 1
    # Get single
    resp = client.get("/sets/set-A")
    assert resp.status_code == 200
    assert resp.json()["id"] == "set-A"


def test_sets_create_duplicate(seeded_store: Store, client: TestClient) -> None:
    client.post("/sets", json=_new_set_payload("dup"))
    resp = client.post("/sets", json=_new_set_payload("dup"))
    assert resp.status_code == 409


def test_sets_update(seeded_store: Store, client: TestClient) -> None:
    client.post("/sets", json=_new_set_payload("upd"))
    payload = _new_set_payload("upd")
    payload["display_order"] = 99
    payload["active"] = False
    resp = client.put("/sets/upd", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_order"] == 99
    assert data["active"] is False


def test_sets_delete(seeded_store: Store, client: TestClient) -> None:
    client.post("/sets", json=_new_set_payload("del"))
    resp = client.delete("/sets/del")
    assert resp.status_code == 204
    assert client.get("/sets/del").status_code == 404


def test_sets_members_replace(seeded_store: Store, client: TestClient) -> None:
    client.post("/sets", json=_new_set_payload("mem"))
    # Initially empty
    assert client.get("/sets/mem/members").json() == []
    # Replace with 1 member (the seeded fixture coin)
    resp = client.post(
        "/sets/mem/members",
        json={"members": [{"eurio_id": "test-2025-2eur-fixture", "position": 1}]},
    )
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["eurio_id"] == "test-2025-2eur-fixture"
    assert members[0]["position"] == 1
    # The JOIN to coins should give the country/year
    assert members[0]["country"] == "eu"
    assert members[0]["year"] == 2025

    # Replace with empty → wipes
    resp = client.post("/sets/mem/members", json={"members": []})
    assert resp.status_code == 200
    assert resp.json() == []


def test_sets_patch_active(seeded_store: Store, client: TestClient) -> None:
    client.post("/sets", json=_new_set_payload("toggle"))
    resp = client.patch("/sets/toggle/active", json={"active": False})
    assert resp.status_code == 200
    assert resp.json()["active"] is False
