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
from store import Store


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
    from shared.api_quota import ensure_schema as ensure_quota_schema
    ensure_quota_schema(tmp_path / "t.db")
    _seed_minimal_referential(test_store)

    # Build a minimal FastAPI app — bypass server.py boot which loads
    # supabase + training_runner.
    from serving import sources_routes
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
    from serving.sources_routes import _today_period

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
    from serving.sources_routes import estimate_calls_per_eurio_id
    val = estimate_calls_per_eurio_id(client.test_store)  # type: ignore[attr-defined]
    assert val == 7.0


def test_estimate_uses_history_when_3_plus_runs(client: TestClient):
    from serving.sources_routes import estimate_calls_per_eurio_id

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
    from serving.sources_routes import _today_period

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


# ── B5 — /sources/ebay/marketplace-map ──────────────────────────────────────


def test_marketplace_map_lists_de_and_es(client: TestClient):
    resp = client.get("/sources/ebay/marketplace-map")
    assert resp.status_code == 200
    payload = resp.json()
    # Routage uniforme : EBAY_DE puis EBAY_ES, pour toutes les origines.
    assert [m["marketplace"] for m in payload["marketplaces"]] == [
        "EBAY_DE", "EBAY_ES",
    ]


def test_run_funnel_aggregates(client: TestClient):
    """L'endpoint /funnel agrège discovery + détection + rejets + steps."""
    conn = client.test_store._connection()  # type: ignore[attr-defined]
    conn.execute(
        "INSERT INTO source_runs (id, source, kind, started_at, ended_at, "
        "status, current_step, n_review_enqueued, n_quotes_added, n_errors) "
        "VALUES ('run-f','ebay','run','2026-05-21 08:00:00',"
        "'2026-05-21 08:10:00','success','price_aggregate',3,2,0)"
    )
    for i, (n0, n3) in enumerate([(50, 30), (40, 20)]):
        conn.execute(
            "INSERT INTO discovery_searches (id, run_id, source, target_eurio_id, "
            "endpoint, status, n_summaries, n_after_groups, n_kept_results) "
            "VALUES (?, 'run-f', 'ebay', 'x', 'ebay.browse.search', 'success', ?, ?, ?)",
            (f"s{i}", n0, n0, n3),
        )
    for i, cs in enumerate(["success", "success", "zero_crops"]):
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, run_id, "
            "crop_status, storage_path) VALUES (?, 'ebay', ?, 'run-f', ?, '')",
            (f"sif{i}", f"ebay_funnel_{i}_img0", cs),
        )
    for i, reason in enumerate(["theme_mismatch", "theme_mismatch", "noise_title"]):
        conn.execute(
            "INSERT INTO discarded_listings (id, run_id, source, source_ref, reason) "
            "VALUES (?, 'run-f', 'ebay', ?, ?)",
            (f"df{i}", f"ebay_disc_{i}_img0", reason),
        )
    conn.commit()

    body = client.get("/sources/ebay/runs/run-f/funnel").json()
    assert body["n_searches"] == 2
    assert body["n_summaries"] == 90
    assert body["n_kept"] == 50
    assert body["n_images"] == 3
    assert body["n_cropped"] == 2
    assert body["n_zero_crops"] == 1
    assert body["n_discarded"] == 3
    reasons = {d["reason"]: d["count"] for d in body["discards"]}
    assert reasons["theme_mismatch"] == 2
    # Run success → les 9 steps du pipeline sont 'done'.
    assert len(body["steps"]) == 9
    assert all(s["status"] == "done" for s in body["steps"])


def test_run_funnel_404_on_unknown_run(client: TestClient):
    assert client.get("/sources/ebay/runs/nope/funnel").status_code == 404


def test_marketplace_map_payload_shape(client: TestClient):
    resp = client.get("/sources/ebay/marketplace-map")
    by_mkt = {m["marketplace"]: m for m in resp.json()["marketplaces"]}
    assert by_mkt["EBAY_DE"]["query_lang"] == "de"
    assert by_mkt["EBAY_ES"]["query_lang"] == "es"
    # GB retiré du routage (0 listing EUR exploitable).
    assert "EBAY_GB" not in by_mkt


# ── B6 — /sources/ebay/filter-config ────────────────────────────────────────


def test_filter_config_lists_expected_rules(client: TestClient):
    resp = client.get("/sources/ebay/filter-config")
    assert resp.status_code == 200
    payload = resp.json()
    names = {r["name"] for r in payload["rules"]}
    assert {
        "noise_title", "below_face", "above_extreme", "non_eur",
        "year_mismatch", "theme_mismatch", "is_lot_suspected",
    }.issubset(names)
    assert payload["source_path"] == "ml/sources/ebay/filters.py"


def test_filter_config_thresholds_match_runtime(client: TestClient):
    """Endpoint reflète bien les constantes courantes — pas de chiffres figés."""
    from sources.ebay import filters
    by_name = {r["name"]: r for r in client.get("/sources/ebay/filter-config").json()["rules"]}
    assert by_name["below_face"]["threshold"] == filters.FACE_VALUE_FACTOR_LOW
    assert by_name["above_extreme"]["threshold"] == filters.FACE_VALUE_FACTOR_HIGH
    assert by_name["year_mismatch"]["policy"] == "accept-on-missing"
    assert by_name["is_lot_suspected"]["kind"] == "flag"
    assert by_name["noise_title"]["kind"] == "reject"


# ── chunk 2 — freshness queue groupée + run preview ─────────────────────────


def _seed_two_coin_group(store) -> None:
    """Ajoute un groupe de 2 commémos-sœurs (LU/2099) au référentiel de test."""
    conn = store._connection()
    for i in range(2):
        conn.execute(
            "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
            "face_value, is_commemorative, theme, raw_payload_json) "
            "VALUES (?,?,?,?,?,?,?,'{}')",
            (f"lu-2099-2eur-sib-{i}", "LU", "Luxembourg", 2099, 2.0, 1, f"t{i}"),
        )
    conn.commit()


def test_freshness_groups_returns_buckets(client: TestClient):
    resp = client.get("/sources/ebay/freshness-groups")
    assert resp.status_code == 200
    body = resp.json()
    # 6 coins seedés, années toutes distinctes → 6 groupes d'1 pièce.
    assert body["buckets"]["total"] == 6
    assert body["buckets"]["never"] == 3
    assert body["buckets"]["stale_90d"] == 2
    assert body["buckets"]["fresh"] == 1
    assert all(g["n_coins"] == 1 for g in body["items"])
    # NULLS FIRST : les groupes jamais enrichis en tête.
    assert [g["status"] for g in body["items"]][:3] == ["never"] * 3


def test_freshness_groups_aggregates_siblings(client: TestClient):
    _seed_two_coin_group(client.test_store)  # type: ignore[attr-defined]
    body = client.get("/sources/ebay/freshness-groups").json()
    lu = [g for g in body["items"] if g["country"] == "LU" and g["year"] == 2099]
    assert len(lu) == 1, "les 2 sœurs LU/2099 forment UN groupe"
    assert lu[0]["n_coins"] == 2


def test_run_preview_counts_coins_and_calls(client: TestClient):
    _seed_two_coin_group(client.test_store)  # type: ignore[attr-defined]
    resp = client.post(
        "/sources/ebay/run-preview",
        json={"discovery_groups": [
            {"denomination": 2.0, "country": "LU", "year": 2099},
            {"denomination": 2.0, "country": "DE", "year": 2000},
        ]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_groups"] == 2
    assert body["total_coins"] == 3   # LU/2099 = 2 + DE/2000 = 1
    by_country = {g["country"]: g for g in body["groups"]}
    assert by_country["LU"]["n_coins"] == 2
    assert by_country["DE"]["n_coins"] == 1
    # Pas d'historique → estimate = 7 calls/pièce × 3 pièces.
    assert body["estimate_calls"] == 21
    assert body["ok"] is True


def test_estimate_handles_grouped_runs(client: TestClient):
    _seed_two_coin_group(client.test_store)  # type: ignore[attr-defined]
    from serving.sources_routes import estimate_calls_per_eurio_id

    conn = client.test_store._connection()  # type: ignore[attr-defined]
    # 3 runs groupés, n_calls=10, groupe LU/2099 = 2 pièces → ratio = 5.
    for i in range(3):
        conn.execute(
            """
            INSERT INTO source_runs (id, source, kind, started_at, ended_at, status,
              n_calls, n_raws_added, filters_json)
            VALUES (?, 'ebay', 'run', datetime('now', ?), datetime('now', ?), 'success',
              10, 0, '{"discovery_groups":[{"denomination":2.0,"country":"LU","year":2099}]}')
            """,
            (f"grp-run-{i}", f"-{i+1} hour", f"-{i} hour"),
        )
    val = estimate_calls_per_eurio_id(client.test_store)  # type: ignore[attr-defined]
    assert val == 5.0


def test_trigger_run_400_on_empty_discovery_scope(client: TestClient):
    """Run eBay sans discovery_groups ni target → 400 empty_discovery_scope
    (front périmé qui POST un body vide), rejeté avant tout run."""
    resp = client.post("/sources/ebay/runs", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "empty_discovery_scope"


# ── chunk 4 — retry des téléchargements échoués ─────────────────────────────


def test_run_snapshot_exposes_n_downloads_failed(client: TestClient):
    conn = client.test_store._connection()  # type: ignore[attr-defined]
    conn.execute(
        "INSERT INTO source_runs (id, source, kind, started_at, status) "
        "VALUES ('dlrun-1', 'ebay', 'run', datetime('now'), 'partial')"
    )
    for i, st in enumerate(["failed", "failed", "success"]):
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, run_id, target_eurio_id, "
            "storage_path, fetched_at, license, download_status) "
            "VALUES (?,?,?,?,?,?,datetime('now'),'fair_use_research',?)",
            (f"si-dl-{i}", "ebay", f"ebay_DL_{i}_img0", "dlrun-1",
             "de-2000-2eur-never-0", f"/tmp/{i}.jpg", st),
        )
    conn.commit()

    snap = client.get("/sources/ebay/runs/dlrun-1").json()
    assert snap["n_downloads_failed"] == 2


def test_retry_downloads_404_on_unknown_run(client: TestClient):
    resp = client.post("/sources/ebay/runs/does-not-exist/retry-downloads")
    assert resp.status_code == 404


def test_retry_downloads_400_when_nothing_failed(client: TestClient):
    conn = client.test_store._connection()  # type: ignore[attr-defined]
    conn.execute(
        "INSERT INTO source_runs (id, source, kind, started_at, status) "
        "VALUES ('cleanrun-1', 'ebay', 'run', datetime('now'), 'success')"
    )
    conn.commit()
    resp = client.post("/sources/ebay/runs/cleanrun-1/retry-downloads")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "nothing_to_retry"
