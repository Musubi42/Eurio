"""FastAPI integration tests pour les endpoints eBay (phase 3.C).

Couverture :
- GET /sources/ebay/quota-status : retourne calls_today, limit, remaining
- GET /sources/ebay/freshness : trie par last_enriched_at NULLS FIRST,
  buckets cohérents
- estimate_calls_per_eurio_id : fallback 7 si <3 runs, moyenne sinon
- POST /sources/ebay/runs : 409 quota_insufficient si batch trop gros
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts.bootstrap_coins_from_referential import bootstrap as bootstrap_coins
from state import Store


def _seed_minimal_referential(store: Store, *, never_count=3, stale_count=2, fresh_count=1):
    """Seed coins + source_images with controlled freshness distribution."""
    conn = store._connection()  # noqa: SLF001

    coins = []
    seq = 2000
    for i in range(never_count):
        coins.append((f"de-{seq+i}-2eur-never-{i}", "DE", seq + i, "Allemagne", 2.0, 1, "n"))
    for i in range(stale_count):
        coins.append((f"fr-{seq+10+i}-2eur-stale-{i}", "FR", seq + 10 + i, "France", 2.0, 1, "s"))
    for i in range(fresh_count):
        coins.append((f"es-{seq+20+i}-2eur-fresh-{i}", "ES", seq + 20 + i, "Espagne", 2.0, 1, "f"))

    for eid, country, year, country_name, fv, comm, theme in coins:
        conn.execute(
            "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
            "face_value, is_commemorative, theme, raw_payload_json) VALUES (?,?,?,?,?,?,?,'{}')",
            (eid, country, country_name, year, fv, comm, theme),
        )

    # Add a stale source_image (>90 days ago) for each "stale" coin
    stale_dt = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
    for i in range(stale_count):
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
            "storage_path, fetched_at, license) VALUES (?,?,?,?,?,?,?)",
            (
                f"si-stale-{i}", "ebay", f"ebay_STALE_{i}_img0",
                f"fr-{seq+10+i}-2eur-stale-{i}", f"/tmp/stale-{i}.jpg",
                stale_dt, "fair_use_research",
            ),
        )

    # Add a fresh source_image (today) for each "fresh" coin
    fresh_dt = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for i in range(fresh_count):
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
            "storage_path, fetched_at, license) VALUES (?,?,?,?,?,?,?)",
            (
                f"si-fresh-{i}", "ebay", f"ebay_FRESH_{i}_img0",
                f"es-{seq+20+i}-2eur-fresh-{i}", f"/tmp/fresh-{i}.jpg",
                fresh_dt, "fair_use_research",
            ),
        )


@pytest.fixture()
def client(tmp_path: Path):
    test_store = Store(tmp_path / "t.db")
    # api_call_log is provisioned by api_quota.ensure_schema (separate from
    # state/schema.sql, see api_quota.py) — load it for the test DB.
    from api_quota import ensure_schema as ensure_quota_schema
    ensure_quota_schema(tmp_path / "t.db")
    _seed_minimal_referential(test_store)

    # Build a minimal FastAPI app — bypass server.py boot which loads
    # supabase + training_runner.
    from api import sources_routes
    sources_routes.reset_orphan_runs(test_store)

    # Patch _store() to return our test store.
    original_store = sources_routes._store
    sources_routes._store = lambda: test_store  # type: ignore[assignment]

    app = FastAPI()
    app.include_router(sources_routes.router)
    try:
        with TestClient(app) as c:
            c.test_store = test_store  # type: ignore[attr-defined]
            yield c
    finally:
        sources_routes._store = original_store  # type: ignore[assignment]


# ── /sources/ebay/quota-status ──────────────────────────────────────────────


def test_quota_status_zero_at_start(client: TestClient):
    resp = client.get("/sources/ebay/quota-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["calls_today"] == 0
    assert body["limit"] == 5000
    assert body["remaining"] == 5000
    assert body["exhausted"] is False
    # No history yet → fallback bootstrap
    assert body["avg_calls_per_eurio_id"] == 7.0


def test_quota_status_reflects_api_call_log(client: TestClient):
    """Inserer manuellement des calls dans api_call_log doit se refléter."""
    from api.sources_routes import _today_period

    conn = client.test_store._connection()  # type: ignore[attr-defined]
    conn.execute(
        """
        INSERT INTO api_call_log (source, key_hash, window, period, calls, exhausted, last_call_at)
        VALUES ('ebay', '', 'daily', ?, 1234, 0, datetime('now'))
        """,
        (_today_period(),),
    )

    resp = client.get("/sources/ebay/quota-status")
    body = resp.json()
    assert body["calls_today"] == 1234
    assert body["remaining"] == 5000 - 1234


# ── /sources/ebay/freshness ────────────────────────────────────────────────


def test_freshness_returns_buckets_and_sorted_items(client: TestClient):
    resp = client.get("/sources/ebay/freshness?limit=20")
    assert resp.status_code == 200
    body = resp.json()

    assert body["buckets"]["never"] == 3
    assert body["buckets"]["stale_90d"] == 2
    assert body["buckets"]["fresh"] == 1
    assert body["buckets"]["total"] == 6

    items = body["items"]
    assert len(items) == 6

    # NULLS FIRST: les 3 first sont "never"
    statuses = [i["status"] for i in items]
    assert statuses[:3] == ["never", "never", "never"]
    # Puis les stale, puis les fresh
    assert "stale" in statuses[3:5]
    assert "fresh" in statuses[5:]


def test_freshness_respects_limit(client: TestClient):
    resp = client.get("/sources/ebay/freshness?limit=2")
    body = resp.json()
    assert len(body["items"]) == 2
    # Buckets reflètent l'ensemble, pas le slice
    assert body["buckets"]["total"] == 6


# ── estimate_calls_per_eurio_id ──────────────────────────────────────────────


def test_estimate_falls_back_to_7_with_no_history(client: TestClient):
    from api.sources_routes import estimate_calls_per_eurio_id
    val = estimate_calls_per_eurio_id(client.test_store)  # type: ignore[attr-defined]
    assert val == 7.0


def test_estimate_uses_history_when_3_plus_runs(client: TestClient):
    from api.sources_routes import estimate_calls_per_eurio_id

    conn = client.test_store._connection()  # type: ignore[attr-defined]
    # 3 runs avec n_calls=10 et 2 target_eurio_ids → ratio = 5
    for i in range(3):
        conn.execute(
            """
            INSERT INTO source_runs (id, source, kind, started_at, ended_at, status,
              n_calls, n_raws_added, filters_json)
            VALUES (?, 'ebay', 'run', datetime('now', ?), datetime('now', ?), 'success',
              10, 0, '{"target_eurio_ids":["a","b"]}')
            """,
            (f"run-{i}", f"-{i+1} hour", f"-{i} hour"),
        )

    val = estimate_calls_per_eurio_id(client.test_store)  # type: ignore[attr-defined]
    assert val == 5.0


# ── pre-flight check sur POST /runs ─────────────────────────────────────────


def test_trigger_run_returns_409_if_quota_insufficient(client: TestClient):
    """Avec moins de 5000-bootstrap*7*1.3 = 4936 quota restant et 100 eurio_ids
    en target, le pre-flight refuse avec 409 quota_insufficient."""
    from api.sources_routes import _today_period

    conn = client.test_store._connection()  # type: ignore[attr-defined]
    # Consomme 4900 calls aujourd'hui → reste 100
    conn.execute(
        """
        INSERT INTO api_call_log (source, key_hash, window, period, calls, exhausted, last_call_at)
        VALUES ('ebay', '', 'daily', ?, 4900, 0, datetime('now'))
        """,
        (_today_period(),),
    )

    # Demande un batch de 50 → estimate = 50*7 = 350, *1.3 = 455 > 100 → refuse
    resp = client.post(
        "/sources/ebay/runs",
        json={"target_eurio_ids": [f"de-{2000+i}-2eur-never-{i}" for i in range(3)] * 17},
    )
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["code"] == "quota_insufficient"
    assert body["estimate"] > body["remaining"]
    assert body["max_safe_batch"] >= 0


def test_trigger_run_503_if_no_ebay_creds(client: TestClient, monkeypatch):
    """Sans EBAY_CLIENT_ID/SECRET, l'endpoint refuse avec 503 (pas 500)."""
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    resp = client.post(
        "/sources/ebay/runs",
        json={"target_eurio_ids": ["de-2000-2eur-never-0"]},
    )
    assert resp.status_code == 503
    assert "EBAY_CLIENT_ID" in resp.json()["detail"]
