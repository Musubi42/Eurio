"""Tests pour resolve.py + enqueue.py — quote pending + lot routing (3.F).

Couvre :
- resolve : pending_quote créée pour single non-lot avec prix
- resolve : pas de pending_quote pour lot
- resolve : pas de pending_quote pour image non-canonique (image_index > 0)
- resolve : idempotence (re-run → 0 nouvelle quote)
- enqueue : kind='lot' si is_lot_suspected
- enqueue : kind='lot' si n_crops > 1 sur la source_image (multi-coin photo)
- enqueue : kind='single' sinon
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from sources._base.run_logger import start_run
from sources._base.steps.enqueue import run_enqueue
from sources._base.steps.resolve import run_resolve
from state import Store


def _seed_source_image(
    conn,
    *,
    sid: str,
    source: str = "ebay",
    source_ref: str | None = None,
    target_eurio_id: str | None = None,
    listing_price: float | None = None,
    is_lot_suspected: bool = False,
    image_index: int = 0,
    title: str = "Test listing",
) -> None:
    raw_payload = json.dumps({"image_index": image_index, "ebay_item_id": "ITEM_X"})
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, target_eurio_id, listing_title,
          listing_price, listing_currency, condition_raw,
          storage_path, license, is_lot_suspected, raw_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, 'EUR', 'Used', '/tmp/x.jpg',
                  'fair_use_research', ?, ?)
        """,
        (
            sid, source, source_ref or f"{source}_{sid}",
            target_eurio_id, title, listing_price, int(is_lot_suspected),
            raw_payload,
        ),
    )


def _seed_image_asset(conn, *, sid: str, source_image_id: str,
                     resolution_status: str = "pending_match",
                     crop_index: int = 0) -> None:
    conn.execute(
        """
        INSERT INTO image_assets (
          id, source_image_id, crop_index, storage_path, resolution_status,
          variant_kind
        ) VALUES (?, ?, ?, ?, ?, 'auction_listing')
        """,
        (sid, source_image_id, crop_index, "/tmp/asset.png", resolution_status),
    )


@pytest.fixture()
def store_run(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    with start_run(conn, source="ebay", kind="run", filters={}, force=True) as run:
        yield store, conn, run


# ── resolve : pending_quotes ──────────────────────────────────────────────


def test_resolve_creates_pending_quote_for_single_listing(store_run):
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=12.5, is_lot_suspected=False, image_index=0)
    _seed_image_asset(conn, sid="A1", source_image_id="S1")

    res = run_resolve(
        conn=conn, run=run, source_id="ebay",
        source_image_ids={"ebay_S1": "S1"},
    )
    assert res.n_pending_quotes_added == 1
    n = conn.execute("SELECT count(*) FROM pending_quotes").fetchone()[0]
    assert n == 1
    row = conn.execute(
        "SELECT price, currency, condition_raw FROM pending_quotes"
    ).fetchone()
    assert row["price"] == 12.5
    assert row["currency"] == "EUR"
    assert row["condition_raw"] == "Used"


def test_resolve_skips_pending_quote_for_lot(store_run):
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=20.0, is_lot_suspected=True, image_index=0)
    _seed_image_asset(conn, sid="A1", source_image_id="S1")

    res = run_resolve(
        conn=conn, run=run, source_id="ebay",
        source_image_ids={"ebay_S1": "S1"},
    )
    assert res.n_pending_quotes_added == 0
    assert conn.execute("SELECT count(*) FROM pending_quotes").fetchone()[0] == 0


def test_resolve_skips_pending_quote_for_non_canonical_image(store_run):
    """Une listing eBay = N source_images (1 par photo). Seule img0 produit
    une pending_quote — img1, img2, ... sont ignorées (sinon doublons)."""
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1_IMG0", listing_price=8.0, image_index=0,
                       source_ref="ebay_ITEM_X_img0")
    _seed_source_image(conn, sid="S1_IMG1", listing_price=8.0, image_index=1,
                       source_ref="ebay_ITEM_X_img1")
    _seed_image_asset(conn, sid="A1", source_image_id="S1_IMG0")
    _seed_image_asset(conn, sid="A2", source_image_id="S1_IMG1")

    res = run_resolve(
        conn=conn, run=run, source_id="ebay",
        source_image_ids={"ebay_ITEM_X_img0": "S1_IMG0", "ebay_ITEM_X_img1": "S1_IMG1"},
    )
    # Une seule pending_quote (img0), même si 2 source_images partagent le même prix.
    assert res.n_pending_quotes_added == 1
    quote = conn.execute(
        "SELECT source_image_id FROM pending_quotes"
    ).fetchone()
    assert quote["source_image_id"] == "S1_IMG0"


def test_resolve_skips_pending_quote_when_price_zero_or_null(store_run):
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=0, is_lot_suspected=False)
    _seed_source_image(conn, sid="S2", listing_price=None, is_lot_suspected=False,
                       source_ref="ebay_S2_ref")
    _seed_image_asset(conn, sid="A1", source_image_id="S1")
    _seed_image_asset(conn, sid="A2", source_image_id="S2")

    res = run_resolve(
        conn=conn, run=run, source_id="ebay",
        source_image_ids={"ebay_S1": "S1", "ebay_S2_ref": "S2"},
    )
    assert res.n_pending_quotes_added == 0


def test_resolve_idempotent_pending_quote(store_run):
    """2 runs successifs → 1 seule pending_quote (dedup par source_image_id)."""
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=5.0, is_lot_suspected=False)
    _seed_image_asset(conn, sid="A1", source_image_id="S1")

    run_resolve(conn=conn, run=run, source_id="ebay", source_image_ids={"ebay_S1": "S1"})
    run_resolve(conn=conn, run=run, source_id="ebay", source_image_ids={"ebay_S1": "S1"})
    n = conn.execute("SELECT count(*) FROM pending_quotes").fetchone()[0]
    assert n == 1


# ── enqueue : kind ────────────────────────────────────────────────────────


def test_enqueue_kind_single_for_normal_listing(store_run):
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=5.0, is_lot_suspected=False)
    _seed_image_asset(conn, sid="A1", source_image_id="S1", resolution_status="needs_review")

    run_enqueue(conn=conn, run=run, source_id="ebay", source_image_ids={"ebay_S1": "S1"})
    kind = conn.execute("SELECT kind FROM review_queue WHERE image_asset_id = ?", ("A1",)).fetchone()
    assert kind["kind"] == "single"


def test_enqueue_kind_lot_when_is_lot_suspected(store_run):
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=20.0, is_lot_suspected=True,
                       title="Coffret 5 pièces")
    _seed_image_asset(conn, sid="A1", source_image_id="S1", resolution_status="needs_review")

    run_enqueue(conn=conn, run=run, source_id="ebay", source_image_ids={"ebay_S1": "S1"})
    kind = conn.execute("SELECT kind FROM review_queue WHERE image_asset_id = ?", ("A1",)).fetchone()
    assert kind["kind"] == "lot"


def test_enqueue_kind_lot_when_multiple_crops_per_source_image(store_run):
    """D-26 niveau 2 : 1 image avec >1 crops (multi-coin photo) → kind='lot'."""
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=5.0, is_lot_suspected=False)
    # 2 crops sur la même source_image (= une photo avec 2 pièces visibles)
    _seed_image_asset(conn, sid="A1", source_image_id="S1", resolution_status="needs_review", crop_index=0)
    _seed_image_asset(conn, sid="A2", source_image_id="S1", resolution_status="needs_review", crop_index=1)

    run_enqueue(conn=conn, run=run, source_id="ebay", source_image_ids={"ebay_S1": "S1"})
    rows = conn.execute("SELECT kind FROM review_queue").fetchall()
    assert len(rows) == 2
    assert all(r["kind"] == "lot" for r in rows)


def test_enqueue_idempotent_with_kind(store_run):
    store, conn, run = store_run
    _seed_source_image(conn, sid="S1", listing_price=5.0, is_lot_suspected=False)
    _seed_image_asset(conn, sid="A1", source_image_id="S1", resolution_status="needs_review")
    run_enqueue(conn=conn, run=run, source_id="ebay", source_image_ids={"ebay_S1": "S1"})
    run_enqueue(conn=conn, run=run, source_id="ebay", source_image_ids={"ebay_S1": "S1"})
    n = conn.execute("SELECT count(*) FROM review_queue").fetchone()[0]
    assert n == 1
