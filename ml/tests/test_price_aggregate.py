"""Tests de l'agrégation de prix (chunk C3 — pipeline prix).

Deux niveaux :
- module pur ``sources/pricing/aggregate`` — pondération vélocité,
  quantiles, nettoyage outliers, agrégation par tier.
- step ``sources/_base/steps/price_aggregate`` — I/O DB : lecture des
  annonces single du run, dédup par listing, écriture coin_market_quotes.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sources._base.steps.price_aggregate import run_price_aggregate
from sources.pricing import (
    PricedListing,
    aggregate_priced_listings,
    clean_outliers,
    velocity_weight,
    weighted_quantile,
    years_since,
)
from sources.pricing.aggregate import MIN_SAMPLES_FOR_OUTLIER
from store import Store

NOW = datetime(2026, 5, 21, tzinfo=timezone.utc)


# ── Module pur ──────────────────────────────────────────────────────────────


def test_years_since_defaults_when_missing():
    assert years_since(None) == 0.5
    assert years_since("pas-une-date") == 0.5


def test_years_since_parses_iso():
    assert years_since("2025-05-21T00:00:00Z", now=NOW) > 0.9
    assert years_since("2025-05-21T00:00:00Z", now=NOW) < 1.1


def test_velocity_weight_recent_beats_old():
    recent = PricedListing(10.0, "UNC", origin_date="2026-05-01")
    old = PricedListing(10.0, "UNC", origin_date="2022-01-01")
    assert velocity_weight(recent, now=NOW) > velocity_weight(old, now=NOW)


def test_velocity_weight_sold_adds_bonus():
    base = PricedListing(10.0, "UNC", origin_date="2026-04-01")
    sold = PricedListing(10.0, "UNC", origin_date="2026-04-01", sold_qty=10)
    assert velocity_weight(sold, now=NOW) > velocity_weight(base, now=NOW)


def test_velocity_weight_has_floor():
    ancient = PricedListing(10.0, "UNC", origin_date="2010-01-01")
    assert velocity_weight(ancient, now=NOW) >= 0.05


def test_weighted_quantile_basic():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    w = [1.0] * 5
    assert weighted_quantile(vals, w, 0.5) == 3.0


def test_weighted_quantile_empty_is_none():
    assert weighted_quantile([], [], 0.5) is None


def test_weighted_quantile_zero_weights_falls_back():
    # Poids tous nuls → fallback non-pondéré, pas de division par zéro.
    assert weighted_quantile([1.0, 2.0, 3.0], [0.0, 0.0, 0.0], 0.5) == 2.0


def test_clean_outliers_drops_extremes():
    ls = [PricedListing(p, "UNC") for p in [5, 5, 6, 5, 4, 60, 0.5]]
    kept = {p.price for p in clean_outliers(ls)}
    assert 60 not in kept and 0.5 not in kept
    assert 5 in kept


def test_clean_outliers_skips_small_sample():
    # < MIN_SAMPLES_FOR_OUTLIER → on ne nettoie pas (échantillon trop mince).
    ls = [PricedListing(p, "UNC") for p in [5, 5, 99][:MIN_SAMPLES_FOR_OUTLIER - 1]]
    assert len(clean_outliers(ls)) == len(ls)


def test_aggregate_groups_by_tier():
    ls = (
        [PricedListing(5.0, "UNC", origin_date="2026-04-01")] * 3
        + [PricedListing(3.0, "TB", origin_date="2026-04-01")] * 2
    )
    quotes = {q.condition: q for q in aggregate_priced_listings(ls, now=NOW)}
    assert set(quotes) == {"UNC", "TB"}
    assert quotes["UNC"].p50 == 5.0
    assert quotes["TB"].p50 == 3.0


def test_aggregate_reports_sample_and_raw_counts():
    ls = [PricedListing(p, "UNC", origin_date="2026-04-01")
          for p in [5, 5, 6, 5, 4, 80]]
    (q,) = aggregate_priced_listings(ls, now=NOW)
    assert q.n_raw == 6
    assert q.sample_size == 5  # le 80 est écarté


def test_aggregate_empty_returns_no_quotes():
    assert aggregate_priced_listings([]) == []


def test_aggregate_drops_tier_far_above_unc():
    """Un tier circulé au p50 >> UNC = échantillon contaminé → supprimé."""
    ls = (
        [PricedListing(5.0, "UNC", origin_date="2026-04-01")] * 4
        + [PricedListing(50.0, "TB", origin_date="2026-04-01")] * 3
    )
    conds = {q.condition for q in aggregate_priced_listings(ls, now=NOW)}
    assert conds == {"UNC"}  # TB (50 € >> 3×5) écarté


def test_aggregate_keeps_tier_within_unc_bound():
    """Un tier circulé à un prix plausible (≤ 3× UNC) est conservé."""
    ls = (
        [PricedListing(10.0, "UNC", origin_date="2026-04-01")] * 4
        + [PricedListing(8.0, "TB", origin_date="2026-04-01")] * 3
    )
    conds = {q.condition for q in aggregate_priced_listings(ls, now=NOW)}
    assert conds == {"UNC", "TB"}


# ── Step DB ─────────────────────────────────────────────────────────────────


def _seed_run(conn: sqlite3.Connection, run_id: str, source: str = "ebay") -> None:
    conn.execute(
        "INSERT INTO source_runs (id, source, kind, started_at, status) "
        "VALUES (?, ?, 'run', ?, 'running')",
        (run_id, source, "2026-05-21T08:00:00Z"),
    )


def _seed_listing(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    eurio_id: str,
    item_id: str,
    price: float,
    listing_kind: str = "single",
    condition: str = "UNC",
    n_images: int = 1,
    source: str = "ebay",
) -> None:
    """Insère un listing : n_images source_images + 1 listing_text_signals/img."""
    for i in range(n_images):
        sid = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO source_images (
              id, source, source_ref, source_url, target_eurio_id,
              listing_price, listing_currency, run_id, storage_path
            ) VALUES (?, ?, ?, ?, ?, ?, 'EUR', ?, '')
            """,
            (sid, source, f"ebay_{item_id}_img{i}",
             f"https://ebay/{item_id}", eurio_id, price, run_id),
        )
        conn.execute(
            "INSERT INTO listing_text_signals "
            "(source_image_id, coverage, listing_kind, condition_normalized) "
            "VALUES (?, 'rich', ?, ?)",
            (sid, listing_kind, condition),
        )
    conn.commit()


def _quotes(conn: sqlite3.Connection, eurio_id: str) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM coin_market_quotes WHERE eurio_id = ?", (eurio_id,)
    ).fetchall()
    return {r["condition_raw"]: r for r in rows}


def test_step_aggregates_single_listings(tmp_path: Path):
    store = Store(tmp_path / "agg.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    run_id = "run-1"
    _seed_run(conn, run_id)
    for i, price in enumerate([4.0, 5.0, 5.0, 6.0]):
        _seed_listing(conn, run_id=run_id, eurio_id="fr-2012-2eur-x",
                      item_id=f"it{i}", price=price)

    res = run_price_aggregate(conn=conn, run_id=run_id, source="ebay")

    assert res.n_coins == 1
    assert res.n_listings == 4
    q = _quotes(conn, "fr-2012-2eur-x")
    assert "UNC" in q
    assert q["UNC"]["p50"] == 5.0
    assert q["UNC"]["sample_size"] == 4


def test_step_excludes_lots_coffrets_graded(tmp_path: Path):
    store = Store(tmp_path / "agg.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    run_id = "run-2"
    _seed_run(conn, run_id)
    _seed_listing(conn, run_id=run_id, eurio_id="de-2016-2eur-y",
                  item_id="single1", price=8.0, listing_kind="single")
    _seed_listing(conn, run_id=run_id, eurio_id="de-2016-2eur-y",
                  item_id="lot1", price=99.0, listing_kind="lot")
    _seed_listing(conn, run_id=run_id, eurio_id="de-2016-2eur-y",
                  item_id="cof1", price=40.0, listing_kind="coffret")
    _seed_listing(conn, run_id=run_id, eurio_id="de-2016-2eur-y",
                  item_id="slab1", price=120.0, listing_kind="graded_slab")

    run_price_aggregate(conn=conn, run_id=run_id, source="ebay")

    q = _quotes(conn, "de-2016-2eur-y")
    # Seul le single compte : p50 = 8.0, pas de pollution lot/coffret/slab.
    assert q["UNC"]["p50"] == 8.0
    assert q["UNC"]["sample_size"] == 1


def test_step_dedups_images_of_same_listing(tmp_path: Path):
    store = Store(tmp_path / "agg.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    run_id = "run-3"
    _seed_run(conn, run_id)
    # 1 listing, 4 images → doit compter comme 1 annonce.
    _seed_listing(conn, run_id=run_id, eurio_id="it-2004-2eur-z",
                  item_id="multi", price=7.0, n_images=4)

    res = run_price_aggregate(conn=conn, run_id=run_id, source="ebay")
    assert res.n_listings == 1
    assert _quotes(conn, "it-2004-2eur-z")["UNC"]["sample_size"] == 1


def test_step_separates_condition_tiers(tmp_path: Path):
    store = Store(tmp_path / "agg.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    run_id = "run-4"
    _seed_run(conn, run_id)
    _seed_listing(conn, run_id=run_id, eurio_id="es-2010-2eur-w",
                  item_id="unc1", price=5.0, condition="UNC")
    _seed_listing(conn, run_id=run_id, eurio_id="es-2010-2eur-w",
                  item_id="tb1", price=2.5, condition="TB")

    run_price_aggregate(conn=conn, run_id=run_id, source="ebay")
    q = _quotes(conn, "es-2010-2eur-w")
    assert q["UNC"]["p50"] == 5.0
    assert q["TB"]["p50"] == 2.5


def test_step_bumps_quotes_counter(tmp_path: Path):
    """Le step écrit n_quotes_added sur source_runs (colonne QUOTES UI)."""
    store = Store(tmp_path / "agg.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    run_id = "run-5"
    _seed_run(conn, run_id)
    for i, price in enumerate([4.0, 5.0, 5.0, 6.0]):
        _seed_listing(conn, run_id=run_id, eurio_id="fr-2012-2eur-x",
                      item_id=f"it{i}", price=price)

    res = run_price_aggregate(conn=conn, run_id=run_id, source="ebay")
    n = conn.execute(
        "SELECT n_quotes_added FROM source_runs WHERE id = ?", (run_id,)
    ).fetchone()[0]
    assert n == res.n_quotes
    assert n >= 1
