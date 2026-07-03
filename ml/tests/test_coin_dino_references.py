"""Endpoints coin-detail des références Dino (improvement-loop B).

- GET  /coins/{eurio_id}/dino-references  → section « Références Dino »
- POST /coins/assets/{asset_id}/dino-reference {action} → pin/exclude/clear
- le badge dino_reference remonte dans GET /coins/{eurio_id}/assets
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

from serving import coin_assets_routes  # noqa: E402
from serving.coin_assets_routes import router as coins_router  # noqa: E402
from store import Store  # noqa: E402
from store.dino_references import DinoRefRow, replace_auto_references  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    coin_assets_routes.bind(store)
    app = FastAPI()
    app.include_router(coins_router)
    return store, TestClient(app)


def _seed_coin_and_asset(conn, eurio_id, asset_id, *, dg=None, status="manual"):
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, design_group_id, "
        "raw_payload_json) VALUES (?, 'FR', 'France', 2015, 2.0, 1, 111, ?, '{}')",
        (eurio_id, dg),
    )
    sid = f"SI_{asset_id}"
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref) VALUES (?, 'ebay', ?)",
        (sid, f"ref_{asset_id}"),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
        "resolution_status, face, denom, training_eligible, storage_path) "
        "VALUES (?, ?, 0, ?, ?, 'obverse', '2eur', 1, ?)",
        (asset_id, sid, eurio_id, status, f"p/{asset_id}.png"),
    )


def _seed_std_coin(conn, eurio_id, numista_id, *, dg, year):
    """2€ standard (is_commemorative=0) membre d'un design group (slug)."""
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, design_group_id, "
        "canonical_eurio_id, raw_payload_json) "
        "VALUES (?, 'BE', 'Belgique', ?, 2.0, 0, ?, ?, NULL, '{}')",
        (eurio_id, year, numista_id, dg),
    )


def _seed_asset_only(conn, eurio_id, asset_id):
    sid = f"SI_{asset_id}"
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref) VALUES (?, 'ebay', ?)",
        (sid, f"ref_{asset_id}"),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
        "resolution_status, face, denom, training_eligible, storage_path) "
        "VALUES (?, ?, 0, ?, 'manual', 'obverse', '2eur', 1, ?)",
        (asset_id, sid, eurio_id, f"p/{asset_id}.png"),
    )


def test_standard_design_group_resolves_to_rep_not_slug(client):
    """Régression du blocker : pour une 2€ standard en design group, la classe
    doit être le REP eurio_id (comme le builder), pas le slug design_group_id.
    Sinon la section est « never_built » et les overrides sont ignorés."""
    store, c = client
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
            ("be-albert-slug", "Albert II"),
        )
        # Design group 'be-albert-slug' : rep = plus ancien millésime (1999).
        _seed_std_coin(conn, "be-2007-albert", 200, dg="be-albert-slug", year=2007)
        _seed_std_coin(conn, "be-1999-albert", 201, dg="be-albert-slug", year=1999)
        _seed_asset_only(conn, "be-2007-albert", "asX")
        # Le builder écrit les refs sous le REP (be-1999-albert).
        replace_auto_references(conn, "2eur_all", [
            DinoRefRow("be-1999-albert", "be-1999-albert", None, "canonical", 0, None),
            DinoRefRow("be-1999-albert", "be-2007-albert", "asX", "fps", 1, 0.5),
        ])

    # Interrogé depuis le membre RÉCENT → doit retrouver la classe du rep.
    refs = c.get("/coins/be-2007-albert/dino-references").json()
    assert refs["never_built"] is False
    assert refs["class_id"] == "be-1999-albert"

    # Pin depuis le membre récent → override écrit sous le rep (que le builder
    # relira via overrides.get(rep)).
    c.post("/coins/assets/asX/dino-reference", json={"action": "pin"})
    refs_rep = c.get("/coins/be-1999-albert/dino-references").json()
    assert any(e["method"] == "manual_pin" and e["asset_id"] == "asX"
               for e in refs_rep["entries"])


def test_dino_references_section_and_badge(client):
    store, c = client
    with store._writing() as conn:
        _seed_coin_and_asset(conn, "fr-2015-a", "as1")
        # Une sélection auto : canonique + as1 (fps).
        replace_auto_references(conn, "2eur_all", [
            DinoRefRow("fr-2015-a", "fr-2015-a", None, "canonical", 0, None),
            DinoRefRow("fr-2015-a", "fr-2015-a", "as1", "fps", 1, 0.55),
        ])

    refs = c.get("/coins/fr-2015-a/dino-references").json()
    assert refs["never_built"] is False
    assert refs["class_id"] == "fr-2015-a"
    methods = [e["method"] for e in refs["entries"]]
    assert "canonical" in methods and "fps" in methods
    fps = next(e for e in refs["entries"] if e["method"] == "fps")
    assert fps["asset_id"] == "as1"
    assert fps["file_url"].endswith("/assets/as1/file")

    # Le badge remonte dans la galerie d'assets.
    assets = c.get("/coins/fr-2015-a/assets").json()["assets"]
    a1 = next(a for a in assets if a["id"] == "as1")
    assert a1["dino_reference"] == "fps"


def test_pin_then_clear_override(client):
    store, c = client
    with store._writing() as conn:
        _seed_coin_and_asset(conn, "fr-2015-a", "as1")

    r = c.post("/coins/assets/as1/dino-reference", json={"action": "pin"})
    assert r.status_code == 200
    assert r.json()["applied"] is True and r.json()["rebuild_required"] is True

    refs = c.get("/coins/fr-2015-a/dino-references").json()
    pin = next(e for e in refs["entries"] if e["method"] == "manual_pin")
    assert pin["asset_id"] == "as1"

    # clear → plus d'override.
    c.post("/coins/assets/as1/dino-reference", json={"action": "clear"})
    refs = c.get("/coins/fr-2015-a/dino-references").json()
    assert all(e["method"] != "manual_pin" for e in refs["entries"])


def test_exclude_override(client):
    store, c = client
    with store._writing() as conn:
        _seed_coin_and_asset(conn, "fr-2015-a", "as1")
    c.post("/coins/assets/as1/dino-reference", json={"action": "exclude"})
    refs = c.get("/coins/fr-2015-a/dino-references").json()
    assert any(e["method"] == "manual_exclude" and e["asset_id"] == "as1"
               for e in refs["entries"])


def test_dino_reference_action_404(client):
    _, c = client
    assert c.post("/coins/assets/nope/dino-reference",
                  json={"action": "pin"}).status_code == 404


def test_never_built_when_no_references(client):
    store, c = client
    with store._writing() as conn:
        _seed_coin_and_asset(conn, "fr-2015-a", "as1")
    refs = c.get("/coins/fr-2015-a/dino-references").json()
    assert refs["never_built"] is True
    assert refs["entries"] == []
