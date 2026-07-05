"""Jumeaux LEAN des corrections de routage review (`serving/review_queue/writes.py`).

Direction A / C3 : requalify-lot/single, correct-listing, move-lane sont servis à
l'identique sur le VPS lean (front → eurioApi). Ces routes n'existaient QUE dans
`review/review_queue_routes.py` (skippé sur le VPS via `import cv2`). Ici on vérifie
que le jumeau lean produit le MÊME effet DB — la logique SQL est partagée
(`store.decisions`), on teste le câblage lean (dep `db_connection` via EURIO_DB_PATH,
scope `review:write`). Les seeds sont réutilisés de `test_review_requalify`.
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
from test_review_requalify import _kinds, _seed_listing, _seed_lts


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["reviewer"],
        scopes=set(scopes), auth_method="api_token",
    )


@pytest.fixture()
def lean(tmp_path, monkeypatch):
    """Client sur le router lean review_writes + un Store tmp (EURIO_DB_PATH)."""
    from serving.review_queue import writes

    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))

    app = FastAPI()
    app.include_router(writes.router)
    app.dependency_overrides[require_principal] = lambda: _principal(("review:write",))
    return conn, TestClient(app)


def test_lean_requalify_lot_flips_whole_listing(lean):
    conn, client = lean
    si, assets, review_ids = _seed_listing(conn, item_id="L1", n_crops=2, kind="single")
    _seed_lts(conn, si, "single")

    r = client.post(f"/review-queue/{review_ids[0]}/requalify-lot")
    assert r.status_code == 200, r.text
    assert r.json()["n_requalified"] == 2
    assert _kinds(conn, assets) == ["lot", "lot"]
    assert conn.execute(
        "SELECT listing_kind FROM listing_text_signals WHERE source_image_id=?", (si,),
    ).fetchone()["listing_kind"] == "lot"


def test_lean_requalify_single_flips_back(lean):
    conn, client = lean
    si, assets, _ = _seed_listing(conn, item_id="BACK1", n_crops=2, kind="lot")
    _seed_lts(conn, si, "lot")

    r = client.post("/review-queue/lots/ebay_BACK1/requalify-single")
    assert r.status_code == 200, r.text
    assert _kinds(conn, assets) == ["single", "single"]
    assert conn.execute(
        "SELECT listing_kind FROM listing_text_signals WHERE source_image_id=?", (si,),
    ).fetchone()["listing_kind"] == "single"


def test_lean_move_lane_to_manual(lean):
    conn, client = lean
    _si, _assets, review_ids = _seed_listing(conn, item_id="M1")
    r = client.post(f"/review-queue/{review_ids[0]}/move-lane")
    assert r.status_code == 200, r.text
    assert r.json()["lane"] == "manual"
    row = conn.execute(
        "SELECT lane, lane_source FROM review_queue WHERE id=?", (review_ids[0],),
    ).fetchone()
    assert row["lane"] == "manual" and row["lane_source"] == "human"


def test_lean_move_lane_404_when_not_open(lean):
    conn, client = lean
    _si, _assets, review_ids = _seed_listing(conn, item_id="M2")
    conn.execute("UPDATE review_queue SET status='done' WHERE id=?", (review_ids[0],))
    assert client.post(f"/review-queue/{review_ids[0]}/move-lane").status_code == 404


def test_lean_correct_listing(lean):
    conn, client = lean
    si, _assets, review_ids = _seed_listing(conn, item_id="C1")
    _seed_lts(conn, si, "single")

    r = client.post(f"/review-queue/{review_ids[0]}/correct-listing",
                    json={"listing_kind": "coffret", "condition": "UNC"})
    assert r.status_code == 200, r.text
    row = conn.execute(
        "SELECT listing_kind, condition_normalized, extractor_version "
        "FROM listing_text_signals WHERE source_image_id=?", (si,),
    ).fetchone()
    assert row["listing_kind"] == "coffret"
    assert row["condition_normalized"] == "UNC"
    assert row["extractor_version"] == "manual"


def test_lean_correct_listing_422_empty(lean):
    conn, client = lean
    _si, _assets, review_ids = _seed_listing(conn, item_id="C2")
    assert client.post(
        f"/review-queue/{review_ids[0]}/correct-listing", json={},
    ).status_code == 422
