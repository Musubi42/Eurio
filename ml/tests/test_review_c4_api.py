"""Tests API du chunk C4a — audit listing dans la review.

Couvre :
- enrichissement du payload ReviewItem (listing_kind, condition, âge…),
- POST /review-queue/{id}/correct-listing (propage à tout le listing,
  marque extractor_version='manual'),
- GET /sources/ebay/market-quotes (dernier coin_market_quotes par tier).
"""

from __future__ import annotations

import json
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

from review import review_queue_routes
from serving import sources_routes  # noqa: E402
from store import Store  # noqa: E402


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    monkeypatch.setattr(review_queue_routes, "_store", lambda: store)
    monkeypatch.setattr(sources_routes, "_store", lambda: store)
    app = FastAPI()
    app.include_router(review_queue_routes.router)
    app.include_router(sources_routes.router)
    return store, store._connection(), TestClient(app)


def _seed_review_item(
    conn: sqlite3.Connection,
    *,
    review_id: str,
    item_id: str = "IT1",
    img_idx: int = 0,
    listing_url: str = "https://ebay/IT1",
    listing_kind: str = "single",
    condition: str = "UNC",
    kind_conf: float = 0.70,
    cond_conf: float = 0.20,
) -> str:
    """Crée 1 source_image + listing_text_signals + image_asset + review_queue.

    Retourne le source_image_id.
    """
    sid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, source_url, target_eurio_id,
          listing_title, listing_price, listing_currency,
          listing_origin_date, sold_qty, storage_path
        ) VALUES (?, 'ebay', ?, ?, 'de-2016-2eur-x', '2 Euro DE 2016',
                  8.50, 'EUR', '2026-02-01T00:00:00Z', 0, '')
        """,
        (sid, f"ebay_{item_id}_img{img_idx}", listing_url),
    )
    conn.execute(
        """
        INSERT INTO listing_text_signals (
          source_image_id, extractor_version, coverage,
          listing_kind, listing_kind_confidence,
          condition_normalized, condition_confidence
        ) VALUES (?, 'v2', 'rich', ?, ?, ?, ?)
        """,
        (sid, listing_kind, kind_conf, condition, cond_conf),
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
    return sid


def _signals(conn: sqlite3.Connection, sid: str) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM listing_text_signals WHERE source_image_id = ?", (sid,)
    ).fetchone()


# ── Payload ReviewItem enrichi ──────────────────────────────────────────────


def test_review_queue_item_carries_listing_context(app_client):
    _, conn, client = app_client
    _seed_review_item(conn, review_id="r1", listing_kind="coffret",
                      condition="UNC")

    item = client.get("/review-queue").json()[0]
    assert item["listing_kind"] == "coffret"
    assert item["condition"] == "UNC"
    assert item["listing_origin_date"] == "2026-02-01T00:00:00Z"
    assert item["sold_qty"] == 0
    assert item["listing_kind_confidence"] == pytest.approx(0.70)


def test_get_single_review_carries_listing_context(app_client):
    _, conn, client = app_client
    _seed_review_item(conn, review_id="r1", listing_kind="graded_slab")
    item = client.get("/review-queue/r1").json()
    assert item["listing_kind"] == "graded_slab"


# ── correct-listing ─────────────────────────────────────────────────────────


def test_correct_listing_updates_and_marks_manual(app_client):
    _, conn, client = app_client
    sid = _seed_review_item(conn, review_id="r1", listing_kind="single",
                            condition="UNC")

    resp = client.post("/review-queue/r1/correct-listing",
                        json={"listing_kind": "coffret", "condition": "TTB"})
    assert resp.status_code == 200

    row = _signals(conn, sid)
    assert row["listing_kind"] == "coffret"
    assert row["condition_normalized"] == "TTB"
    assert row["listing_kind_confidence"] == 1.0
    assert row["condition_confidence"] == 1.0
    # extractor_version='manual' → gèle contre une ré-extraction C2.
    assert row["extractor_version"] == "manual"


def test_correct_listing_propagates_to_all_listing_images(app_client):
    """Les N photos d'un listing partagent source_url → toutes corrigées."""
    _, conn, client = app_client
    sid0 = _seed_review_item(conn, review_id="r1", item_id="IT1", img_idx=0,
                             listing_url="https://ebay/IT1")
    sid1 = _seed_review_item(conn, review_id="r2", item_id="IT1", img_idx=1,
                             listing_url="https://ebay/IT1")

    client.post("/review-queue/r1/correct-listing",
                json={"listing_kind": "lot"})

    # La correction sur r1 touche aussi la 2e photo du même listing.
    assert _signals(conn, sid0)["listing_kind"] == "lot"
    assert _signals(conn, sid1)["listing_kind"] == "lot"


def test_correct_listing_partial_only_touches_given_field(app_client):
    _, conn, client = app_client
    sid = _seed_review_item(conn, review_id="r1", listing_kind="single",
                            condition="UNC")
    client.post("/review-queue/r1/correct-listing",
                json={"condition": "TB"})
    row = _signals(conn, sid)
    assert row["condition_normalized"] == "TB"
    assert row["listing_kind"] == "single"  # inchangé


def test_correct_listing_rejects_empty_payload(app_client):
    _, conn, client = app_client
    _seed_review_item(conn, review_id="r1")
    assert client.post("/review-queue/r1/correct-listing", json={}).status_code == 422


def test_correct_listing_rejects_bad_kind(app_client):
    _, conn, client = app_client
    _seed_review_item(conn, review_id="r1")
    resp = client.post("/review-queue/r1/correct-listing",
                       json={"listing_kind": "boxed"})
    assert resp.status_code == 422


def test_correct_listing_404_on_unknown_review(app_client):
    _, _, client = app_client
    resp = client.post("/review-queue/nope/correct-listing",
                       json={"condition": "TB"})
    assert resp.status_code == 404


# ── market-quotes ───────────────────────────────────────────────────────────


def _seed_quote(conn, *, eurio_id, condition, p50, period_start):
    conn.execute(
        """
        INSERT INTO coin_market_quotes (
          id, eurio_id, source, condition_raw, condition_normalized,
          p10, p50, p90, sample_size, period_start, period_end
        ) VALUES (?, ?, 'ebay', ?, ?, ?, ?, ?, 5, ?, ?)
        """,
        (uuid.uuid4().hex, eurio_id, condition, condition,
         p50 * 0.8, p50, p50 * 1.2, period_start, period_start),
    )
    conn.commit()


def test_market_quotes_returns_latest_per_tier(app_client):
    _, conn, client = app_client
    _seed_quote(conn, eurio_id="de-2016-2eur-x", condition="UNC", p50=5.0,
                period_start="2026-04-01T00:00:00Z")
    _seed_quote(conn, eurio_id="de-2016-2eur-x", condition="UNC", p50=6.0,
                period_start="2026-05-01T00:00:00Z")  # plus récent
    _seed_quote(conn, eurio_id="de-2016-2eur-x", condition="TB", p50=2.5,
                period_start="2026-05-01T00:00:00Z")

    body = client.get("/sources/ebay/market-quotes",
                      params={"eurio_ids": "de-2016-2eur-x"}).json()
    quotes = {q["condition"]: q for q in body["quotes"]["de-2016-2eur-x"]}
    assert quotes["UNC"]["p50"] == 6.0  # le plus récent gagne
    assert quotes["TB"]["p50"] == 2.5


def test_market_quotes_empty_for_uncovered_coin(app_client):
    _, _, client = app_client
    body = client.get("/sources/ebay/market-quotes",
                      params={"eurio_ids": "xx-9999-2eur-none"}).json()
    assert body["quotes"] == {}
