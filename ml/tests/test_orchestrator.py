"""End-to-end smoke test for the 8-step pipeline skeleton (chunk 2.A).

At this stage the steps Persist..Enqueue are stubs — we only validate
that the orchestrator wires the run lifecycle correctly:

- a `source_runs` row is created with status='partial' (skeleton)
- `current_step` reaches 'enqueue' (= it walked all 8 steps)
- discover() actually consumed the mock fixtures (n_calls=1)
- dry_run=True stops after discover with status='success'
- re-runs are allowed (anti-double-run only triggers on 'running')
"""

from __future__ import annotations

import logging

import pytest

from sources._base.adapter import SourceQuery
from sources._base.orchestrator import run_pipeline
from sources._mock import MOCK_FIXTURES, MockAdapter
from state.store import Store


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


def test_pipeline_skeleton_runs_all_six_steps(store: Store, caplog) -> None:
    caplog.set_level(logging.INFO)
    adapter = MockAdapter()
    run_id = run_pipeline(adapter, SourceQuery(source_id="mock"), store=store)

    conn = store._connection()
    row = conn.execute(
        "SELECT * FROM source_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row is not None
    assert row["source"] == "mock"
    assert row["kind"] == "run"
    assert row["status"] == "success"
    assert row["current_step"] == "enqueue"
    assert row["n_calls"] == 1
    assert row["n_raws_added"] == 5
    assert row["n_review_enqueued"] == 5
    assert row["n_errors"] == 0
    assert row["error_summary"] is None

    messages = [r.message for r in caplog.records]
    assert any("discover sig=" in m and "5 new / 0 already-seen" in m for m in messages)
    assert any("persist → 5 added" in m for m in messages)
    assert any("enqueue → 5 new" in m for m in messages)


def test_dry_run_stops_after_discover(store: Store) -> None:
    adapter = MockAdapter()
    run_id = run_pipeline(
        adapter, SourceQuery(source_id="mock"), store=store, dry_run=True
    )

    row = store._connection().execute(
        "SELECT kind, status, current_step FROM source_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert row["kind"] == "dry"
    assert row["status"] == "success"
    assert row["current_step"] == "discover"


def test_discover_filters_by_country(store: Store) -> None:
    adapter = MockAdapter()
    items = list(adapter.discover(SourceQuery(source_id="mock", country="FR")))
    assert len(items) == 1
    assert items[0].listing_country == "FR"
    assert items[0].source_ref == "mock-64"


def test_discover_persist_idempotent_on_rerun(store: Store) -> None:
    """Run #1 inserts 5 rows. Run #2 (same query) inserts 0 — counters
    on `n_raws_added` must reflect the dedup, and `last_seen_at` on
    `discovery_log` must advance for re-discovered items.
    """
    adapter = MockAdapter()
    query = SourceQuery(source_id="mock")

    run1 = run_pipeline(adapter, query, store=store)
    conn = store._connection()

    counts1 = conn.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM discovery_log WHERE source='mock') as dl, "
        "(SELECT COUNT(*) FROM source_images WHERE source='mock') as si"
    ).fetchone()
    assert counts1["dl"] == 5
    assert counts1["si"] == 5

    row1 = conn.execute(
        "SELECT n_raws_added FROM source_runs WHERE id = ?", (run1,)
    ).fetchone()
    assert row1["n_raws_added"] == 5

    # 2.D: pipeline now goes through resolve too, state advances to 'resolved'.
    states = {r["pipeline_state"] for r in conn.execute(
        "SELECT pipeline_state FROM discovery_log WHERE source='mock'"
    ).fetchall()}
    assert states == {"resolved"}

    seen_before = {r["source_ref"]: r["last_seen_at"] for r in conn.execute(
        "SELECT source_ref, last_seen_at FROM discovery_log WHERE source='mock'"
    ).fetchall()}

    # SQLite's datetime('now') is second-precision; sleep enough to
    # guarantee a strictly greater last_seen_at on rerun.
    import time
    time.sleep(1.1)

    run2 = run_pipeline(adapter, query, store=store)
    counts2 = conn.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM discovery_log WHERE source='mock') as dl, "
        "(SELECT COUNT(*) FROM source_images WHERE source='mock') as si"
    ).fetchone()
    assert counts2["dl"] == 5
    assert counts2["si"] == 5

    row2 = conn.execute(
        "SELECT n_raws_added FROM source_runs WHERE id = ?", (run2,)
    ).fetchone()
    assert row2["n_raws_added"] == 0

    seen_after = {r["source_ref"]: r["last_seen_at"] for r in conn.execute(
        "SELECT source_ref, last_seen_at FROM discovery_log WHERE source='mock'"
    ).fetchall()}
    for ref, before in seen_before.items():
        assert seen_after[ref] > before, f"last_seen_at should advance for {ref}"


def test_download_and_detect_crop_idempotent(store: Store, tmp_path, monkeypatch, capsys) -> None:
    """Run #1: 5 raws on disk + 5 image_assets with phash. Run #2: 0
    new files, 0 new crops. Audit visuel: chemins imprimés en stdout.
    """
    # Redirect storage root inside tmp_path so we can inspect cleanly.
    from sources._base import storage
    monkeypatch.setattr(storage, "_STORAGE_ROOT", tmp_path / "sources")
    # Reload the modules that captured the path at import-time.
    import importlib
    from sources._base.steps import download as dl_mod, detect_crop as dc_mod
    importlib.reload(dl_mod)
    importlib.reload(dc_mod)
    from sources._base import orchestrator as orch_mod
    importlib.reload(orch_mod)

    adapter = MockAdapter()
    query = SourceQuery(source_id="mock")

    run1 = orch_mod.run_pipeline(adapter, query, store=store)
    conn = store._connection()

    # 5 raws on disk
    raws = list((tmp_path / "sources" / "mock" / "raw").rglob("*.jpg"))
    assert len(raws) == 5, f"expected 5 raws, got {len(raws)}: {raws}"

    # 5 crops on disk
    crops = sorted((tmp_path / "sources" / "mock" / "crops").rglob("*.png"))
    assert len(crops) == 5, f"expected 5 crops, got {len(crops)}: {crops}"

    # 5 image_assets with phash, all status='pending_match' (no prior data).
    rows = conn.execute(
        "SELECT phash, resolution_status, detection_method, width, height "
        "FROM image_assets ORDER BY phash"
    ).fetchall()
    assert len(rows) == 5
    for r in rows:
        assert r["phash"] is not None
        # 2.D: resolve marks all unresolved crops as needs_review.
        assert r["resolution_status"] == "needs_review"
        assert r["detection_method"].startswith(("contour", "hough"))
        assert (r["width"], r["height"]) == (224, 224)

    # All 5 phashes should be distinct (different coins).
    assert len({r["phash"] for r in rows}) == 5

    # Run counters
    counters1 = conn.execute(
        "SELECT n_raws_added, n_crops_added, n_errors FROM source_runs WHERE id=?",
        (run1,),
    ).fetchone()
    assert counters1["n_raws_added"] == 5
    assert counters1["n_crops_added"] == 5
    assert counters1["n_errors"] == 0

    # Capture mtimes for idempotence check
    raw_mtimes = {p.name: p.stat().st_mtime_ns for p in raws}
    crop_mtimes = {p.name: p.stat().st_mtime_ns for p in crops}

    # ── Re-run ──────────────────────────────────────────────────────
    run2 = orch_mod.run_pipeline(adapter, query, store=store)

    counters2 = conn.execute(
        "SELECT n_raws_added, n_crops_added, n_errors FROM source_runs WHERE id=?",
        (run2,),
    ).fetchone()
    assert counters2["n_raws_added"] == 0
    assert counters2["n_crops_added"] == 0
    assert counters2["n_errors"] == 0

    # Files untouched
    for p in raws:
        assert p.stat().st_mtime_ns == raw_mtimes[p.name], f"raw rewritten: {p}"
    for p in crops:
        assert p.stat().st_mtime_ns == crop_mtimes[p.name], f"crop rewritten: {p}"

    # Audit visuel: print crop paths so the human can `open` them.
    print("\n--- AUDIT VISUEL: crops produits ---")
    for p in crops:
        print(p)
    print("--- fin audit ---")


def test_review_queue_filled_and_idempotent(store: Store) -> None:
    """End-to-end: 5 review_queue rows after run #1, still 5 after run #2."""
    adapter = MockAdapter()
    query = SourceQuery(source_id="mock")

    run1 = run_pipeline(adapter, query, store=store)
    conn = store._connection()

    queue = conn.execute(
        "SELECT image_asset_id, priority, status FROM review_queue ORDER BY priority"
    ).fetchall()
    assert len(queue) == 5
    for q in queue:
        assert q["status"] == "open"
        assert q["priority"] == 100  # no target_eurio_id on the mock fixtures

    counters1 = conn.execute(
        "SELECT n_review_enqueued, status FROM source_runs WHERE id=?", (run1,)
    ).fetchone()
    assert counters1["n_review_enqueued"] == 5
    assert counters1["status"] == "success"

    # Re-run: review_queue.UNIQUE(image_asset_id) blocks duplicates.
    run2 = run_pipeline(adapter, query, store=store)
    queue2 = conn.execute("SELECT COUNT(*) AS c FROM review_queue").fetchone()
    assert queue2["c"] == 5

    counters2 = conn.execute(
        "SELECT n_review_enqueued FROM source_runs WHERE id=?", (run2,)
    ).fetchone()
    assert counters2["n_review_enqueued"] == 0


def test_priority_drops_when_target_known(store: Store) -> None:
    """A targeted fetch (target_eurio_id set on the listing) → priority 70."""
    from sources._base.dedup import upsert_source_image, SourceImageRow
    from sources._base.steps.enqueue import run_enqueue
    from sources._base.steps.resolve import run_resolve
    from sources._base.run_logger import start_run

    conn = store._connection()
    with start_run(conn, source="mock", kind="run") as run:
        sid = upsert_source_image(conn, SourceImageRow(
            source="mock",
            source_ref="targeted-1",
            target_eurio_id="EURIO-FR-2EUR-2002",
        ))
        # Manually create one image_asset in needs_review to skip the
        # heavy crop step in this focused test.
        from sources._base.dedup import upsert_image_asset, ImageAssetRow
        upsert_image_asset(conn, ImageAssetRow(
            source_image_id=sid,
            crop_index=0,
            resolution_status="needs_review",
            phash=42,
            storage_path="/tmp/dummy.png",
        ))
        run_enqueue(
            conn=conn, run=run, source_id="mock",
            source_image_ids={"targeted-1": sid},
        )
        run.end("success")

    row = conn.execute("SELECT priority FROM review_queue").fetchone()
    assert row["priority"] == 70


def test_query_signature_is_stable() -> None:
    from sources._base.query_sig import compute_query_signature

    q1 = SourceQuery(source_id="mock", country="FR", limit=5)
    q2 = SourceQuery(source_id="mock", country="FR", limit=5)
    assert compute_query_signature(q1) == compute_query_signature(q2)

    q3 = SourceQuery(source_id="mock", country="DE", limit=5)
    assert compute_query_signature(q1) != compute_query_signature(q3)


def test_mock_fixtures_have_real_files() -> None:
    """Guards against silent dataset moves — fail loud, not at runtime."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "datasets"
    for nid, *_ in MOCK_FIXTURES:
        assert (root / str(nid) / "obverse.jpg").is_file(), (
            f"missing fixture obverse for numista_id={nid}"
        )


# ─── Phase 3.A: target_eurio_ids (plural) batching ──────────────────────────


def test_source_query_rejects_both_singular_and_plural_target() -> None:
    """target_eurio_id and target_eurio_ids are mutually exclusive (D-19)."""
    with pytest.raises(ValueError, match="mutually exclusive"):
        SourceQuery(
            source_id="mock",
            target_eurio_id="x",
            target_eurio_ids=("y", "z"),
        )


def test_source_query_accepts_list_for_target_eurio_ids() -> None:
    """Ergonomics: callers pass a list; __post_init__ coerces to tuple."""
    q = SourceQuery(source_id="mock", target_eurio_ids=["a", "b"])  # type: ignore[arg-type]
    assert q.target_eurio_ids == ("a", "b")


def test_query_signature_order_independent_for_target_eurio_ids() -> None:
    from sources._base.query_sig import compute_query_signature

    q1 = SourceQuery(source_id="mock", target_eurio_ids=("a", "b", "c"))
    q2 = SourceQuery(source_id="mock", target_eurio_ids=("c", "a", "b"))
    assert compute_query_signature(q1) == compute_query_signature(q2)

    q3 = SourceQuery(source_id="mock", target_eurio_ids=("a", "b"))
    assert compute_query_signature(q1) != compute_query_signature(q3)


class _RecordingMockAdapter:
    """Tracks every SourceQuery passed to discover() — used to verify
    the orchestrator synthesizes one sub-query per eurio_id (D-21)."""

    source_id = "mock"

    def __init__(self) -> None:
        self.calls: list[SourceQuery] = []

    def discover(self, query: SourceQuery, *, record_search=None, record_discarded=None):
        self.calls.append(query)
        # Yield the matching mock fixture if numista_id matches; else nothing.
        # Map target_eurio_id "mock-fixture-<nid>" → that fixture.
        if query.target_eurio_id and query.target_eurio_id.startswith("mock-fixture-"):
            nid = int(query.target_eurio_id.split("-")[-1])
            for fid, country, year, price, title in MOCK_FIXTURES:
                if fid == nid:
                    from sources._base.adapter import DiscoveredItem

                    yield DiscoveredItem(
                        source_ref=f"mock-{nid}",
                        source_url=f"mock://numista/{nid}/obverse",
                        listing_title=title,
                        listing_country=country,
                        listing_year=year,
                        listing_price=price,
                        listing_currency="EUR",
                        target_eurio_id=query.target_eurio_id,
                        raw_payload={"numista_id": nid, "fixture": True},
                    )

    def download_raw(self, item, dest):  # pragma: no cover — not exercised here
        raise NotImplementedError


def test_target_eurio_ids_loops_one_subquery_per_eurio_id(store: Store, tmp_path, monkeypatch) -> None:
    """Orchestrator unfolds a batch query into N sub-queries at the Discover step.

    Verified by giving the adapter 3 eurio_ids, and asserting it
    received 3 mono-eurio_id calls. Two of the eurio_ids match real
    mock fixtures (so we get 2 items), the third doesn't match
    (no item yielded) — proving the loop runs even when one returns 0.
    """
    # Reroute storage so we don't pollute the repo's ml/datasets/sources.
    from sources._base import storage

    monkeypatch.setattr(storage, "_STORAGE_ROOT", tmp_path / "sources")

    adapter = _RecordingMockAdapter()
    run_pipeline(
        adapter,
        SourceQuery(
            source_id="mock",
            target_eurio_ids=(
                "mock-fixture-64",
                "mock-fixture-80",
                "mock-fixture-9999",  # no match
            ),
        ),
        store=store,
    )

    assert len(adapter.calls) == 3
    # Each sub-query has a single target_eurio_id, plural cleared.
    seen_targets = {c.target_eurio_id for c in adapter.calls}
    assert seen_targets == {
        "mock-fixture-64",
        "mock-fixture-80",
        "mock-fixture-9999",
    }
    for c in adapter.calls:
        assert c.target_eurio_ids is None

    # 2 fixtures matched → 2 source_images persisted.
    n_si = (
        store._connection()  # noqa: SLF001
        .execute("SELECT count(*) FROM source_images WHERE source = 'mock'")
        .fetchone()[0]
    )
    assert n_si == 2
