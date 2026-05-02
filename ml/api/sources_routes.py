"""FastAPI router for the sources orchestrator (`/sources/...`).

Two surfaces:
- `GET /sources/status` — aggregated overview (delegated to
  `sources_aggregator.build_status`). Predates the orchestrator
  refacto, kept verbatim.
- Per-source orchestrator endpoints — wrap `ml/sources/_base/orchestrator`
  and the `source_runs` / `source_images` / `image_assets` /
  `coin_market_quotes` tables defined in `state/schema.sql`.

Long-running runs (`POST /sources/:id/runs`) are dispatched in a
background daemon thread. Polling is done via `GET /sources/:id/runs/:run_id`
which reads straight from `source_runs` — that table is the source of
truth, no in-memory job dict.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict
from typing import Any

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sources._base.adapter import SourceQuery
from sources._base.orchestrator import run_pipeline
from sources._base.run_logger import RunAlreadyRunning
from state import Store

from . import sources_aggregator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])


# ── Adapter dispatch ──────────────────────────────────────────────────────
# Real sources land here as they get implemented. Until then, only `mock`
# can be triggered (CLI/front will get a clear 501 otherwise).

def _load_adapter(source_id: str):
    if source_id == "mock":
        from sources._mock import MockAdapter
        return MockAdapter()
    raise HTTPException(
        status_code=501,
        detail=(
            f"Source '{source_id}' has no orchestrator adapter yet. "
            "Available: mock. Real sources land as their adapters are written."
        ),
    )


def _store() -> Store:
    """The Store is a sibling of the runner-owned one, but pointing at the
    same SQLite file. We re-open lazily so background threads get their own
    thread-local connection (Store handles thread-locality)."""
    from .server import _store as shared_store
    return shared_store


# ── Status (existing) ─────────────────────────────────────────────────────


@router.get("/status")
def sources_status() -> dict:
    return sources_aggregator.build_status()


# ── Trigger a run (background thread) ─────────────────────────────────────


class RunQueryBody(BaseModel):
    """Filters forwarded to `SourceAdapter.discover()`."""

    country: str | None = None
    denomination: str | None = None
    year: int | None = None
    target_eurio_id: str | None = None
    limit: int | None = Field(default=None, ge=1, le=10_000)
    extra: dict[str, Any] = Field(default_factory=dict)


class TriggerResponse(BaseModel):
    run_id: str
    status: str
    source_id: str
    kind: str


@router.post("/{source_id}/runs", response_model=TriggerResponse, status_code=202)
def trigger_run(
    source_id: str,
    body: RunQueryBody | None = None,
    dry_run: bool = Query(default=False),
    force: bool = Query(default=False),
) -> TriggerResponse:
    adapter = _load_adapter(source_id)
    payload = body or RunQueryBody()
    query = SourceQuery(source_id=source_id, **payload.model_dump())
    store = _store()

    # Pre-flight: open the run synchronously so the caller gets a real
    # run_id (and a clean 409 if anti-double-run trips). The actual
    # pipeline executes in a daemon thread.
    conn = store._connection()  # noqa: SLF001
    try:
        existing = conn.execute(
            "SELECT id FROM source_runs WHERE source = ? AND status = 'running' LIMIT 1",
            (source_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if existing and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_already_running",
                "run_id": existing["id"],
                "message": (
                    f"A run for '{source_id}' is already running. "
                    "Pass ?force=true to override."
                ),
            },
        )

    run_id_holder: dict[str, str] = {}
    started = threading.Event()

    def _runner() -> None:
        try:
            rid = run_pipeline(
                adapter, query, store=store, dry_run=dry_run, force=force,
            )
            run_id_holder["run_id"] = rid
        except RunAlreadyRunning as exc:
            logger.warning("[%s] anti-double-run tripped: %s", source_id, exc)
            run_id_holder["error"] = str(exc)
        except Exception:
            logger.exception("[%s] orchestrator crashed", source_id)
            # The run row (if it was opened) is marked 'failed' by the
            # run_logger context manager. Nothing else to do here.
        finally:
            started.set()

    # We need the run_id back synchronously; the cleanest way is to
    # have run_pipeline open the row before the thread returns. Since
    # start_run() runs at the top of run_pipeline(), the row exists
    # within ms — we wait briefly so the response carries the real id.
    thread = threading.Thread(
        target=_runner, name=f"src-run-{source_id}", daemon=True
    )
    thread.start()

    # Block up to 2s waiting for the row to materialize. On timeout we
    # fall back to the most recent 'running' row for this source — the
    # thread has surely opened it by then in any plausible scenario.
    started.wait(timeout=2.0)
    rid = run_id_holder.get("run_id")
    if rid is None:
        row = conn.execute(
            "SELECT id, kind FROM source_runs WHERE source = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=500,
                detail="Run thread did not register a source_runs row in time.",
            )
        rid = row["id"]

    return TriggerResponse(
        run_id=rid,
        status="started",
        source_id=source_id,
        kind="dry" if dry_run else "run",
    )


# ── Single run snapshot (polling target) ──────────────────────────────────


class RunSnapshot(BaseModel):
    id: str
    source: str
    kind: str
    status: str
    current_step: str | None
    started_at: str
    ended_at: str | None
    duration_s: float | None
    n_calls: int
    n_raws_added: int
    n_crops_added: int
    n_quotes_added: int
    n_pending_added: int
    n_auto_resolved: int
    n_review_enqueued: int
    n_errors: int
    filters: dict[str, Any]
    error_summary: str | None
    log_path: str | None


@router.get("/{source_id}/runs/{run_id}", response_model=RunSnapshot)
def get_run(source_id: str, run_id: str) -> RunSnapshot:
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT * FROM source_runs WHERE id = ? AND source = ?",
        (run_id, source_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return _row_to_snapshot(row)


def _row_to_snapshot(row: sqlite3.Row) -> RunSnapshot:
    started = row["started_at"]
    ended = row["ended_at"]
    duration: float | None = None
    if started and ended:
        try:
            from datetime import datetime
            t0 = datetime.fromisoformat(started.replace(" ", "T"))
            t1 = datetime.fromisoformat(ended.replace(" ", "T"))
            duration = (t1 - t0).total_seconds()
        except Exception:  # noqa: BLE001 — duration is informational
            duration = None

    filters: dict[str, Any] = {}
    if row["filters_json"]:
        try:
            filters = json.loads(row["filters_json"])
        except json.JSONDecodeError:
            filters = {"_raw": row["filters_json"]}

    return RunSnapshot(
        id=row["id"],
        source=row["source"],
        kind=row["kind"],
        status=row["status"],
        current_step=row["current_step"],
        started_at=started,
        ended_at=ended,
        duration_s=duration,
        n_calls=row["n_calls"],
        n_raws_added=row["n_raws_added"],
        n_crops_added=row["n_crops_added"],
        n_quotes_added=row["n_quotes_added"],
        n_pending_added=row["n_pending_added"],
        n_auto_resolved=row["n_auto_resolved"],
        n_review_enqueued=row["n_review_enqueued"],
        n_errors=row["n_errors"],
        filters=filters,
        error_summary=row["error_summary"],
        log_path=row["log_path"],
    )


# ── Startup hook: reset orphan 'running' rows ─────────────────────────────


# ── Detail endpoints (read-only, replace front mocks) ─────────────────────


def _aggregator_source(source_id: str) -> dict[str, Any]:
    """Look up the source's metadata block from `build_status()`.

    Fallback: if the aggregator doesn't know the source but the
    orchestrator registry does (case for `mock` and any future source
    where the adapter lands before the aggregator metadata), synthesize
    a minimal block from `SourceSpec` so the detail endpoints stay
    usable. Raises 404 only if neither registry knows the id.
    """
    status = sources_aggregator.build_status()
    for src in status.get("sources", []):
        if src["id"] == source_id:
            return src

    # Fallback to the orchestrator registry.
    from sources._base.sources_registry import SOURCES
    spec = SOURCES.get(source_id)
    if spec is None:
        raise HTTPException(
            status_code=404, detail=f"Source '{source_id}' not declared.",
        )
    return {
        "id": spec.id,
        "label": spec.label,
        "subtitle": spec.notes or f"{spec.kind} · {spec.default_variant_kind}",
        "kind": spec.kind,
        "is_future": spec.is_future,
        "health": "healthy",
        "health_reason": None,
        "temporal": {
            "expected_cadence_days": spec.expected_cadence_days,
            "last_run_at": None,
        },
        "coverage": {
            "enriched": 0,
            "total_target": 0,
            "pct": 0.0,
            "unit": "items",
        },
    }


class SourceDetailHeader(BaseModel):
    id: str
    label: str
    subtitle: str
    health: str
    health_reason: str | None
    expected_cadence_days: int
    last_run_at: str | None
    last_run_summary: dict[str, Any] | None
    coverage_pct: float
    coverage_label: str


@router.get("/{source_id}", response_model=SourceDetailHeader)
def source_detail(source_id: str) -> SourceDetailHeader:
    src = _aggregator_source(source_id)
    conn = _store()._connection()  # noqa: SLF001
    last = conn.execute(
        """
        SELECT status, n_calls, n_raws_added, n_crops_added, n_quotes_added,
               started_at, ended_at
          FROM source_runs
         WHERE source = ? AND status != 'running'
         ORDER BY started_at DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()

    last_summary: dict[str, Any] | None = None
    if last:
        duration = None
        if last["started_at"] and last["ended_at"]:
            try:
                from datetime import datetime
                t0 = datetime.fromisoformat(last["started_at"].replace(" ", "T"))
                t1 = datetime.fromisoformat(last["ended_at"].replace(" ", "T"))
                duration = (t1 - t0).total_seconds()
            except Exception:  # noqa: BLE001
                duration = None
        last_summary = {
            "n_images": last["n_raws_added"] + last["n_crops_added"],
            "n_quotes": last["n_quotes_added"],
            "n_calls": last["n_calls"],
            "duration_s": duration or 0,
            "status": last["status"],
        }

    coverage = src["coverage"]
    return SourceDetailHeader(
        id=src["id"],
        label=src["label"],
        subtitle=src["subtitle"],
        health=src["health"],
        health_reason=src.get("health_reason"),
        expected_cadence_days=src["temporal"]["expected_cadence_days"],
        last_run_at=src["temporal"].get("last_run_at"),
        last_run_summary=last_summary,
        coverage_pct=coverage.get("pct", 0.0),
        coverage_label=(
            f"{coverage.get('enriched', 0):,} / {coverage.get('total_target', 0):,} "
            f"{coverage.get('unit', '')}"
        ).replace(",", " "),
    )


class SourceRunListItem(BaseModel):
    id: str
    started_at: str
    kind: str
    duration_s: float
    n_calls: int
    n_images: int
    n_quotes: int
    n_errors: int
    status: str
    filters: dict[str, Any]
    log_path: str | None


@router.get("/{source_id}/runs", response_model=list[SourceRunListItem])
def list_runs(
    source_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None),
) -> list[SourceRunListItem]:
    conn = _store()._connection()  # noqa: SLF001
    sql = "SELECT * FROM source_runs WHERE source = ?"
    args: list[Any] = [source_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY started_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()

    out: list[SourceRunListItem] = []
    for r in rows:
        snap = _row_to_snapshot(r)
        out.append(SourceRunListItem(
            id=snap.id,
            started_at=snap.started_at,
            kind=snap.kind,
            duration_s=snap.duration_s or 0.0,
            n_calls=snap.n_calls,
            n_images=snap.n_raws_added + snap.n_crops_added,
            n_quotes=snap.n_quotes_added,
            n_errors=snap.n_errors,
            status=snap.status,
            filters=snap.filters,
            log_path=snap.log_path,
        ))
    return out


class SourceImageItem(BaseModel):
    id: str
    thumb_url: str
    full_url: str
    eurio_id: str | None
    variant_kind: str | None
    quality_score: float | None
    training_eligible: bool
    fetched_at: str


class PaginatedImages(BaseModel):
    items: list[SourceImageItem]
    total: int


@router.get("/{source_id}/images", response_model=PaginatedImages)
def list_images(
    source_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=200, alias="pageSize"),
) -> PaginatedImages:
    conn = _store()._connection()  # noqa: SLF001
    total = conn.execute(
        """
        SELECT COUNT(*) AS c
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE s.source = ?
        """,
        (source_id,),
    ).fetchone()["c"]

    offset = (page - 1) * page_size
    rows = conn.execute(
        """
        SELECT a.id, a.eurio_id, a.variant_kind, a.quality_score,
               a.training_eligible, a.fetched_at
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE s.source = ?
         ORDER BY a.fetched_at DESC
         LIMIT ? OFFSET ?
        """,
        (source_id, page_size, offset),
    ).fetchall()

    items = [
        SourceImageItem(
            id=r["id"],
            # File-serving routes will land in 4.C — for now return a
            # data-URI-style placeholder so the front renders gracefully.
            thumb_url=f"/sources/{source_id}/assets/{r['id']}/file",
            full_url=f"/sources/{source_id}/assets/{r['id']}/file",
            eurio_id=r["eurio_id"],
            variant_kind=r["variant_kind"] if r["variant_kind"] != "unknown" else None,
            quality_score=r["quality_score"],
            training_eligible=bool(r["training_eligible"]),
            fetched_at=r["fetched_at"],
        )
        for r in rows
    ]
    return PaginatedImages(items=items, total=total)


class SourceQuoteItem(BaseModel):
    id: str
    eurio_id: str
    condition: str
    p10: float
    p50: float
    p90: float
    n: int
    period: str
    fetched_at: str


class PaginatedQuotes(BaseModel):
    items: list[SourceQuoteItem]
    total: int


@router.get("/{source_id}/quotes", response_model=PaginatedQuotes)
def list_quotes(
    source_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200, alias="pageSize"),
) -> PaginatedQuotes:
    conn = _store()._connection()  # noqa: SLF001
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM coin_market_quotes WHERE source = ?",
        (source_id,),
    ).fetchone()["c"]

    offset = (page - 1) * page_size
    rows = conn.execute(
        """
        SELECT id, eurio_id, condition_normalized, p10, p50, p90, sample_size,
               period_start, fetched_at
          FROM coin_market_quotes
         WHERE source = ?
         ORDER BY fetched_at DESC
         LIMIT ? OFFSET ?
        """,
        (source_id, page_size, offset),
    ).fetchall()

    items = [
        SourceQuoteItem(
            id=r["id"],
            eurio_id=r["eurio_id"],
            condition=r["condition_normalized"] or "unknown",
            p10=r["p10"] or 0.0,
            p50=r["p50"] or 0.0,
            p90=r["p90"] or 0.0,
            n=r["sample_size"],
            period=r["period_start"][:7] if r["period_start"] else "",
            fetched_at=r["fetched_at"],
        )
        for r in rows
    ]
    return PaginatedQuotes(items=items, total=total)


class CoverageBreakdownEntry(BaseModel):
    key: str
    enriched: int
    total: int
    pct: float


class SourceCoverage(BaseModel):
    global_: dict[str, Any] = Field(alias="global")
    breakdown_dimension: str
    breakdown: list[CoverageBreakdownEntry]
    uncovered_eurio_ids: list[str]

    class Config:
        populate_by_name = True


@router.get("/{source_id}/coverage", response_model=SourceCoverage)
def get_coverage(source_id: str) -> SourceCoverage:
    src = _aggregator_source(source_id)
    cov = src["coverage"]
    # V1: breakdown / uncovered ids would need richer joins against the
    # coins table — left empty for now. The header global is enough to
    # power the page; the breakdown widget falls back to "no data".
    return SourceCoverage(
        **{"global": {
            "enriched": cov.get("enriched", 0),
            "total": cov.get("total_target", 0),
            "pct": cov.get("pct", 0.0),
            "unit": cov.get("unit", ""),
        }},
        breakdown_dimension="—",
        breakdown=[],
        uncovered_eurio_ids=[],
    )


# ── File serving (image_assets crops) ─────────────────────────────────────


@router.get("/{source_id}/assets/{asset_id}/file")
def get_asset_file(source_id: str, asset_id: str):
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT a.storage_path
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.id = ? AND s.source = ?
        """,
        (asset_id, source_id),
    ).fetchone()
    if row is None or not row["storage_path"]:
        raise HTTPException(status_code=404, detail="Asset not found.")
    p = Path(row["storage_path"])
    if not p.is_file():
        raise HTTPException(status_code=410, detail="Asset file missing on disk.")
    return FileResponse(p, media_type="image/png")


# ── Startup hook ──────────────────────────────────────────────────────────


def reset_orphan_runs(store: Store) -> int:
    """Flip rows left in `status='running'` from a previous process to
    `'failed'`. Returns the number of rows touched.

    Called by the FastAPI startup hook in `server.py`. Without this,
    if uvicorn is killed mid-run, the next request sees the orphan as
    "still running" and refuses to start a new one (anti-double-run).
    """
    conn = store._connection()  # noqa: SLF001
    cur = conn.execute(
        """
        UPDATE source_runs
           SET status = 'failed',
               ended_at = COALESCE(ended_at, datetime('now')),
               error_summary = COALESCE(error_summary, 'process restart — orphan run')
         WHERE status = 'running'
        """
    )
    return cur.rowcount or 0
