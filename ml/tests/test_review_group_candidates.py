"""Tests API du chunk 5b — pièces du groupe dans la review.

Quand le theme-match n'a pas tranché (verdict ambigu → `target_eurio_id`
NULL), le payload ReviewItem expose `group_candidates` : toutes les 2 €
commémoratives du groupe `(pays, année)`, sélectionnables d'un clic.
Quand une proposition existe (`target_eurio_id` posé), `group_candidates`
reste vide — la proposition suffit.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from review import review_queue_routes  # noqa: E402
from store import Store  # noqa: E402


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    monkeypatch.setattr(review_queue_routes, "_store", lambda: store)
    app = FastAPI()
    app.include_router(review_queue_routes.router)
    return store._connection(), TestClient(app)


def _seed_coin(
    conn: sqlite3.Connection,
    *,
    eurio_id: str,
    country: str = "BE",
    year: int = 2016,
    face_value: float = 2.0,
    is_commemorative: int = 1,
    theme: str | None = "thème",
) -> None:
    conn.execute(
        """
        INSERT INTO coins (eurio_id, country, country_name, year,
                           face_value, is_commemorative, theme, numista_id)
        VALUES (?, ?, 'Belgique', ?, ?, ?, ?, 12345)
        """,
        (eurio_id, country, year, face_value, is_commemorative, theme),
    )


def _seed_review_item(
    conn: sqlite3.Connection,
    *,
    review_id: str,
    target_eurio_id: str | None,
    listing_country: str | None = "BE",
    listing_year: int | None = 2016,
) -> None:
    """1 source_image + image_asset + review_queue (single, open)."""
    sid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, source_url, target_eurio_id,
          listing_title, listing_country, listing_year,
          listing_price, listing_currency, storage_path
        ) VALUES (?, 'ebay', ?, 'https://ebay/x', ?, '2 Euro',
                  ?, ?, 7.0, 'EUR', '')
        """,
        (sid, f"ebay_{review_id}_img0", target_eurio_id,
         listing_country, listing_year),
    )
    asset_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, "
        "storage_path, resolution_status) VALUES (?, ?, 0, '', 'needs_review')",
        (asset_id, sid),
    )
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, kind, "
        "priority, enqueued_at) VALUES (?, ?, 'open', 'single', 0, "
        "'2026-05-21T08:00:00')",
        (review_id, asset_id),
    )
    conn.commit()


def test_ambiguous_listing_exposes_group_candidates(app_client):
    """target NULL → toutes les 2 € commémo du groupe (BE, 2016)."""
    conn, client = app_client
    _seed_coin(conn, eurio_id="be-2016-2eur-childfocus", theme="Child Focus")
    _seed_coin(conn, eurio_id="be-2016-2eur-rio", theme="Rio Olympics")
    _seed_review_item(conn, review_id="r1", target_eurio_id=None)

    item = client.get("/review-queue").json()[0]
    assert item["target_candidate"] is None
    ids = {c["eurio_id"] for c in item["group_candidates"]}
    assert ids == {"be-2016-2eur-childfocus", "be-2016-2eur-rio"}


def test_group_candidates_excludes_non_commemorative_and_other_denoms(app_client):
    """Le groupe = 2 € commémo uniquement : ni circulante, ni autre dénom."""
    conn, client = app_client
    _seed_coin(conn, eurio_id="be-2016-2eur-comm", theme="Comm")
    _seed_coin(conn, eurio_id="be-2016-2eur-circ", is_commemorative=0)
    _seed_coin(conn, eurio_id="be-2016-1eur-comm", face_value=1.0)
    _seed_coin(conn, eurio_id="be-2015-2eur-comm", year=2015)
    _seed_review_item(conn, review_id="r1", target_eurio_id=None)

    item = client.get("/review-queue").json()[0]
    ids = {c["eurio_id"] for c in item["group_candidates"]}
    assert ids == {"be-2016-2eur-comm"}


def test_resolved_listing_has_no_group_candidates(app_client):
    """Une proposition existe (target posé) → group_candidates vide."""
    conn, client = app_client
    _seed_coin(conn, eurio_id="be-2016-2eur-childfocus", theme="Child Focus")
    _seed_coin(conn, eurio_id="be-2016-2eur-rio", theme="Rio Olympics")
    _seed_review_item(conn, review_id="r1",
                      target_eurio_id="be-2016-2eur-childfocus")

    item = client.get("/review-queue").json()[0]
    assert item["target_candidate"] is not None
    assert item["group_candidates"] == []


def test_group_candidates_empty_when_listing_has_no_year(app_client):
    """Pas de pays/année sur le listing → pas de groupe, pas de crash."""
    conn, client = app_client
    _seed_coin(conn, eurio_id="be-2016-2eur-comm", theme="Comm")
    _seed_review_item(conn, review_id="r1", target_eurio_id=None,
                      listing_country=None, listing_year=None)

    item = client.get("/review-queue").json()[0]
    assert item["group_candidates"] == []
