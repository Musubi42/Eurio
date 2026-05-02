"""Smoke tests for `ml/sources/_base/` foundations.

These tests validate that:
- the new tables (source_runs, source_images, image_assets,
  coin_market_quotes, pending_quotes, review_queue) are created by the
  Store bootstrap;
- run_logger handles the full lifecycle (start → step → bump → end)
  + the anti-double-run guard;
- dedup helpers are idempotent on a second call with the same input.
"""

from __future__ import annotations

import sqlite3

import pytest

from sources._base import dedup, run_logger
from sources._base.run_logger import RunAlreadyRunning, start_run
from state.store import Store


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    store = Store(tmp_path / "t.db")
    return store._connection()  # noqa: SLF001 — tests reach into the store deliberately


def test_schema_tables_exist(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('source_runs','source_images','image_assets','coin_market_quotes',"
        "'pending_quotes','review_queue')"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert names == {
        "source_runs", "source_images", "image_assets",
        "coin_market_quotes", "pending_quotes", "review_queue",
    }


def test_run_lifecycle(conn: sqlite3.Connection) -> None:
    with start_run(conn, source="ebay", kind="run", filters={"limit": 5}) as run:
        run.set_step("discover")
        run.bump(n_calls=3)
        run.set_step("persist")
        run.bump(n_raws_added=2)
        run.end("success")

    row = conn.execute("SELECT * FROM source_runs").fetchone()
    assert row["status"] == "success"
    assert row["n_calls"] == 3
    assert row["n_raws_added"] == 2
    assert row["current_step"] == "persist"
    assert row["ended_at"] is not None


def test_run_logger_marks_failed_on_exception(conn: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError):
        with start_run(conn, source="ebay", kind="run") as run:
            run.bump(n_calls=1)
            raise RuntimeError("boom")

    row = conn.execute("SELECT * FROM source_runs").fetchone()
    assert row["status"] == "failed"
    assert "boom" in (row["error_summary"] or "")


def test_anti_double_run(conn: sqlite3.Connection) -> None:
    ctx = start_run(conn, source="ebay", kind="run")
    ctx.__enter__()
    try:
        with pytest.raises(RunAlreadyRunning):
            start_run(conn, source="ebay", kind="run")
        # force=True bypasses the check
        ctx2 = start_run(conn, source="ebay", kind="run", force=True)
        ctx2.__enter__().end("success")
        ctx2.__exit__(None, None, None)
    finally:
        ctx.__enter__().end("success")
        ctx.__exit__(None, None, None)


def test_upsert_source_image_idempotent(conn: sqlite3.Connection) -> None:
    row = dedup.SourceImageRow(
        source="ebay",
        source_ref="ebay_listing_123",
        listing_title="2 euros Belgique 2002",
        listing_country="BE",
        listing_year=2002,
        listing_price=4.50,
        license="fair_use_research",
        redistributable=False,
    )
    sid1 = dedup.upsert_source_image(conn, row)
    sid2 = dedup.upsert_source_image(conn, row)
    assert sid1 == sid2

    n = conn.execute("SELECT COUNT(*) AS n FROM source_images").fetchone()["n"]
    assert n == 1


def test_upsert_image_asset_idempotent(conn: sqlite3.Connection) -> None:
    sid = dedup.upsert_source_image(conn, dedup.SourceImageRow(
        source="ebay", source_ref="ebay_listing_42",
    ))
    asset = dedup.ImageAssetRow(
        source_image_id=sid,
        crop_index=0,
        storage_path="/tmp/foo.jpg",
        bbox={"x": 1, "y": 2, "w": 3, "h": 4},
        detection_method="yolo",
    )
    aid1 = dedup.upsert_image_asset(conn, asset)
    aid2 = dedup.upsert_image_asset(conn, asset)
    assert aid1 == aid2

    n = conn.execute("SELECT COUNT(*) AS n FROM image_assets").fetchone()["n"]
    assert n == 1


def test_quote_unique_uses_condition_raw(conn: sqlite3.Connection) -> None:
    base = {
        "eurio_id": "BE-2EUR-2002",
        "source": "ebay_active",
        "period_start": "2026-05-01T00:00:00",
        "period_end": "2026-05-31T00:00:00",
        "condition_normalized": "UNC",
    }
    # Two distinct fine grades that both normalize to UNC must produce
    # two separate rows (regression check on the schema decision in
    # `schema.md` §coin_market_quotes).
    dedup.upsert_coin_market_quote(conn, dedup.CoinMarketQuoteRow(**base, condition_raw="FDC", p50=10.0))
    dedup.upsert_coin_market_quote(conn, dedup.CoinMarketQuoteRow(**base, condition_raw="SUP-62", p50=8.0))
    n = conn.execute("SELECT COUNT(*) AS n FROM coin_market_quotes").fetchone()["n"]
    assert n == 2


def test_pending_quote_insert_and_delete(conn: sqlite3.Connection) -> None:
    sid = dedup.upsert_source_image(conn, dedup.SourceImageRow(
        source="ebay", source_ref="ebay_listing_99",
    ))
    pid = dedup.insert_pending_quote(conn, dedup.PendingQuoteRow(
        source_image_id=sid, source="ebay_active", price=5.5,
    ))
    assert pid
    n = dedup.delete_pending_quotes_for(conn, sid)
    assert n == 1
