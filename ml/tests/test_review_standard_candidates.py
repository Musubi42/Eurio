"""Tests API — review « N-contre-designs » pour les standards.

Un crop issu d'un scrape STANDARD (recherche large pays, ``listing_year``
NULL) doit :

* exposer ``standard_candidates`` = les *design groups* avers du pays (1 par
  ``COALESCE(design_group_id, eurio_id)``, Types fusionnés), affichés en
  priorité pour que le reviewer tranche entre N designs ;
* être SERVI quand la review est scopée sur un eurio_id *standard*
  (``?eurio_id=…``) même si ``target_eurio_id`` est NULL — sinon les crops
  ambigus (sans année propre) resteraient invisibles et la classe starve.
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

from api import review_queue_routes  # noqa: E402
from store import Store  # noqa: E402


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    monkeypatch.setattr(review_queue_routes, "_store", lambda: store)
    app = FastAPI()
    app.include_router(review_queue_routes.router)
    return store._connection(), TestClient(app)


def _seed_standard(
    conn: sqlite3.Connection,
    *,
    eurio_id: str,
    year: int,
    design_group_id: str | None,
    country: str = "BE",
) -> None:
    conn.execute(
        """
        INSERT INTO coins (eurio_id, country, country_name, year, face_value,
                           is_commemorative, design_group_id, numista_id)
        VALUES (?, ?, 'Belgique', ?, 2.0, 0, ?, 12345)
        """,
        (eurio_id, country, year, design_group_id),
    )


def _seed_design_group(conn: sqlite3.Connection, gid: str, designation: str) -> None:
    conn.execute(
        "INSERT INTO design_groups (id, designation) VALUES (?, ?)",
        (gid, designation),
    )


def _seed_standard_crop(
    conn: sqlite3.Connection,
    *,
    review_id: str,
    target_eurio_id: str | None = None,
    listing_country: str | None = "BE",
    listing_year: int | None = None,  # NULL = scrape standard
) -> None:
    sid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, source_url, target_eurio_id,
          listing_title, listing_country, listing_year,
          listing_price, listing_currency, storage_path
        ) VALUES (?, 'ebay', ?, 'https://ebay/x', ?,
                  '2 Euro Belgien Kursmünze', ?, ?, 7.0, 'EUR', '')
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
        "'2026-06-07T08:00:00')",
        (review_id, asset_id),
    )
    conn.commit()


def test_standard_crop_exposes_design_groups_collapsed(app_client):
    """target NULL + year NULL → design groups du pays, Types fusionnés."""
    conn, client = app_client
    _seed_design_group(conn, "be-2euro-albert-ii-t1", "BE 2€ Albert II (1er type)")
    # Albert II t1 = 2 Types (1999, 2007) → 1 seul candidat (collapse).
    _seed_standard(conn, eurio_id="be-1999-std", year=1999,
                   design_group_id="be-2euro-albert-ii-t1")
    _seed_standard(conn, eurio_id="be-2007-std", year=2007,
                   design_group_id="be-2euro-albert-ii-t1")
    # Philippe = pas de design_group → reste son propre groupe (legacy).
    _seed_standard(conn, eurio_id="be-2014-philippe", year=2014,
                   design_group_id=None)
    _seed_standard_crop(conn, review_id="r1")

    item = client.get("/review-queue").json()[0]
    cands = item["standard_candidates"]
    ids = {c["eurio_id"] for c in cands}
    # 2 designs : Albert II t1 (représentant = plus ancien = be-1999) + Philippe.
    assert ids == {"be-1999-std", "be-2014-philippe"}
    albert = next(c for c in cands if c["eurio_id"] == "be-1999-std")
    assert albert["label"] == "BE 2€ Albert II (1er type)"
    # Trié par millésime croissant.
    assert [c["year"] for c in cands] == [1999, 2014]


def test_commemo_crop_has_no_standard_candidates(app_client):
    """Crop avec année (commémo) → pas de design groups standard."""
    conn, client = app_client
    _seed_standard(conn, eurio_id="be-1999-std", year=1999, design_group_id=None)
    _seed_standard_crop(conn, review_id="r1", listing_year=2016)

    item = client.get("/review-queue").json()[0]
    assert item["standard_candidates"] == []


def test_standard_eurio_scope_serves_null_target_pool(app_client):
    """?eurio_id=<standard> sert tout le pool pays (incl. target NULL)."""
    conn, client = app_client
    _seed_standard(conn, eurio_id="be-1999-std", year=1999, design_group_id=None)
    # Crop ambigu (target NULL) — invisible sous l'ancien scope target=eurio_id.
    _seed_standard_crop(conn, review_id="r1", target_eurio_id=None)

    items = client.get("/review-queue?eurio_id=be-1999-std").json()
    assert [i["id"] for i in items] == ["r1"]
    assert {c["eurio_id"] for c in items[0]["standard_candidates"]} == {"be-1999-std"}
