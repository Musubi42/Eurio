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
from state.source_status import upsert_source_status  # noqa: E402
from store import Store  # noqa: E402


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
        "INSERT INTO coin_descriptions_i18n "
        "(eurio_id, source, lang, title, description, method, confidence) "
        "VALUES (?, 'bce_official', 'fr', 'Titre BCE', 'Description officielle BCE', "
        "'scrape', 'canon')", (eurio_id,),
    )
    conn.execute(
        "INSERT INTO coin_descriptions_i18n "
        "(eurio_id, source, lang, title, description, method, confidence) "
        "VALUES (?, 'bce_official', 'de', 'BCE Titel', 'Offizielle EZB-Beschreibung', "
        "'scrape', 'canon')", (eurio_id,),
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


def test_coin_descriptions(seeded_store: Store, client: TestClient) -> None:
    resp = client.get("/coins/test-2025-2eur-fixture/descriptions")
    assert resp.status_code == 200
    data = resp.json()
    descs = {d["lang"]: d for d in data["descriptions"]}
    assert set(descs) == {"fr", "de"}
    assert descs["fr"]["title"] == "Titre BCE"
    assert descs["fr"]["description"] == "Description officielle BCE"
    assert descs["fr"]["source"] == "bce_official"
    assert descs["de"]["title"] == "BCE Titel"


def test_coin_descriptions_empty(seeded_store: Store, client: TestClient) -> None:
    # Pièce sans description i18n → liste vide, pas d'erreur.
    seeded_store._connection().execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, currency, "
        "is_commemorative) VALUES ('bare-2025-2eur', 'eu', 2025, 2.0, 'EUR', 0)",
    )
    resp = client.get("/coins/bare-2025-2eur/descriptions")
    assert resp.status_code == 200
    assert resp.json()["descriptions"] == []


def test_coin_source_status_endpoint(seeded_store: Store, client: TestClient) -> None:
    # Pose un statut ok sur BCE pour le coin fixture ; les autres sources
    # doivent défauter à never.
    seeded_store._connection().execute(
        "INSERT INTO coin_source_status (eurio_id, source, state, detail_json, last_checked_at) "
        "VALUES ('test-2025-2eur-fixture', 'bce_official', 'ok', "
        "'{\"axes\": {\"description\": true}}', '2026-05-30T10:00:00')"
    )
    resp = client.get("/coins/test-2025-2eur-fixture/source-status")
    assert resp.status_code == 200
    data = resp.json()
    by_src = {s["source"]: s for s in data["sources"]}
    # Les 6 sources affichées (DISPLAYED_SOURCES) sont présentes.
    assert set(by_src) == {"bce_official", "numista_api", "eurlex_jo",
                           "ebay_browse", "lmdlp", "wikipedia"}
    assert by_src["bce_official"]["state"] == "ok"
    assert by_src["bce_official"]["axes"] == {"description": True}
    assert by_src["bce_official"]["last_checked_at"] == "2026-05-30T10:00:00"
    # Source sans row → never.
    assert by_src["numista_api"]["state"] == "never"
    assert by_src["wikipedia"]["state"] == "never"


# ── Refresh par source (chunk 2) ────────────────────────────────────────────


def test_refresh_rejects_unknown_source(seeded_store: Store, client: TestClient) -> None:
    resp = client.post("/coins/test-2025-2eur-fixture/refresh?source=wikipedia")
    assert resp.status_code == 400


def test_refresh_404_unknown_coin(seeded_store: Store, client: TestClient) -> None:
    resp = client.post("/coins/nope/refresh?source=bce")
    assert resp.status_code == 404


def test_refresh_concurrent_returns_409(seeded_store: Store, client: TestClient) -> None:
    # Un run numista 'running' → refresh numista sans force = 409.
    seeded_store._connection().execute(
        "INSERT INTO source_runs (id, source, kind, status) "
        "VALUES ('run-x', 'numista', 'run', 'running')"
    )
    resp = client.post("/coins/test-2025-2eur-fixture/refresh?source=numista")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "run_already_running"


def test_refresh_numista_no_id_sets_error(seeded_store: Store) -> None:
    # Coin sans numista_id → verdict error 'no_numista_id', AUCUN réseau.
    from referential.coin_refresh import refresh_numista_coin
    conn = seeded_store._connection()
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, currency, is_commemorative) "
        "VALUES ('no-nid-2025-2eur', 'eu', 2025, 2.0, 'EUR', 1)"
    )
    refresh_numista_coin(seeded_store, "no-nid-2025-2eur")
    row = conn.execute(
        "SELECT state, detail_json FROM coin_source_status "
        "WHERE eurio_id='no-nid-2025-2eur' AND source='numista_api'"
    ).fetchone()
    assert row["state"] == "error"
    assert json.loads(row["detail_json"])["error"] == "no_numista_id"


def test_resolve_numista_id_variant_uses_canonical(seeded_store: Store) -> None:
    from referential.coin_refresh import _resolve_numista_id
    conn = seeded_store._connection()
    # canonique avec numista_id, variante sans (pointe la canonique).
    conn.execute("INSERT INTO coins (eurio_id, country, year, face_value, currency, "
                 "is_commemorative, numista_id) VALUES ('canon-x','eu',2025,2.0,'EUR',1,12345)")
    conn.execute("INSERT INTO coins (eurio_id, country, year, face_value, currency, "
                 "is_commemorative, canonical_eurio_id) VALUES ('var-x','eu',2025,2.0,'EUR',1,'canon-x')")
    assert _resolve_numista_id(conn, "var-x") == 12345


def test_upsert_source_status_partial(seeded_store: Store) -> None:
    conn = seeded_store._connection()
    upsert_source_status(conn, eurio_id="test-2025-2eur-fixture", source="bce_official",
                         state="ok", axes={"description": True}, partial=True,
                         error="facts:boom")
    row = conn.execute(
        "SELECT state, detail_json, last_checked_at FROM coin_source_status "
        "WHERE eurio_id='test-2025-2eur-fixture' AND source='bce_official'"
    ).fetchone()
    detail = json.loads(row["detail_json"])
    assert row["state"] == "ok"
    assert detail["partial"] is True
    assert detail["error"] == "facts:boom"
    assert row["last_checked_at"] is not None  # checked=True par défaut


def test_bce_i18n_target_filters(seeded_store: Store, monkeypatch) -> None:
    """harvest avec target_eurio_ids n'écrit QUE le coin ciblé (writes scopés)."""
    import referential.scrape_bce_i18n as m
    from sources.bce.adapter import BceAdapter
    conn = seeded_store._connection()
    for eid in ("t1-2024-2eur", "t2-2024-2eur"):
        conn.execute("INSERT INTO coins (eurio_id, country, year, face_value, currency, "
                     "is_commemorative) VALUES (?, 'fr', 2024, 2.0, 'EUR', 1)", (eid,))
    conn.commit()
    fake_coins = [
        {"country": "FR", "theme_slug": "a", "feature": "Coin A", "description": "desc A",
         "_field_order": ["feature", "description"], "_block_index": 0},
        {"country": "FR", "theme_slug": "b", "feature": "Coin B", "description": "desc B",
         "_field_order": ["feature", "description"], "_block_index": 1},
    ]
    monkeypatch.setattr(m, "_fetch_lang_page", lambda year, lang, **kw: "<html/>")
    monkeypatch.setattr(m, "parse_bce_page", lambda html, year: fake_coins)
    monkeypatch.setattr(m, "parse_bce_lang_blocks", lambda html: {0: [], 1: []})
    monkeypatch.setattr(BceAdapter, "_load_referential", lambda self: {})
    monkeypatch.setattr(BceAdapter, "match_group",
                        lambda self, ref, items: ["t1-2024-2eur", "t2-2024-2eur"])

    m.harvest(seeded_store, years=[2024], langs=["en"], target_eurio_ids={"t1-2024-2eur"})
    rows = {r[0] for r in conn.execute(
        "SELECT eurio_id FROM coin_descriptions_i18n WHERE source='bce_official'")}
    assert "t1-2024-2eur" in rows
    assert "t2-2024-2eur" not in rows
    # Chunk 4 : le run bulk i18n upsert aussi coin_source_status ok (checked).
    st = conn.execute(
        "SELECT state, last_checked_at FROM coin_source_status "
        "WHERE eurio_id='t1-2024-2eur' AND source='bce_official'").fetchone()
    assert st is not None and st["state"] == "ok"
    assert st["last_checked_at"] is not None
    assert conn.execute(
        "SELECT 1 FROM coin_source_status WHERE eurio_id='t2-2024-2eur'").fetchone() is None


def test_bce_axes_derivation(seeded_store: Store) -> None:
    from state.source_status import bce_axes
    conn = seeded_store._connection()
    conn.execute("INSERT INTO coins (eurio_id, country, year, face_value, currency, "
                 "is_commemorative) VALUES ('ax-2024-2eur', 'fr', 2024, 2.0, 'EUR', 1)")
    conn.execute("INSERT INTO coin_descriptions_i18n (eurio_id, source, lang, title) "
                 "VALUES ('ax-2024-2eur', 'bce_official', 'fr', 'T')")
    conn.execute("INSERT INTO coin_observations (eurio_id, source, observation_type, payload_json) "
                 "VALUES ('ax-2024-2eur', 'bce_official', 'mintage_official', '{}')")
    assert bce_axes(conn, "ax-2024-2eur") == {"description": True, "mintage": True}


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
