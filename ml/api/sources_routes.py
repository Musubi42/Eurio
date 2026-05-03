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

def _load_adapter(source_id: str, *, store: "Store" | None = None):
    if source_id == "mock":
        from sources._mock import MockAdapter
        return MockAdapter()
    if source_id == "ebay":
        import os
        from market.ebay_client import EbayClient, get_app_token
        from sources.ebay import EbayAdapter

        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=503,
                detail="EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set in env (.envrc).",
            )
        token = get_app_token(client_id, client_secret)
        client = EbayClient(token)
        s = store or _store()
        conn = s._connection()  # noqa: SLF001
        return EbayAdapter(client=client, conn=conn)
    raise HTTPException(
        status_code=501,
        detail=(
            f"Source '{source_id}' has no orchestrator adapter yet. "
            "Available: mock, ebay. Real sources land as their adapters are written."
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
    target_eurio_ids: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=10_000)
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_source_query(self, source_id: str) -> SourceQuery:
        d = self.model_dump()
        if d.get("target_eurio_ids") is not None:
            d["target_eurio_ids"] = tuple(d["target_eurio_ids"])
        return SourceQuery(source_id=source_id, **d)


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
    payload = body or RunQueryBody()
    store = _store()
    adapter = _load_adapter(source_id, store=store)
    if dry_run and hasattr(adapter, "dry_run"):
        adapter.dry_run = True
    query = payload.to_source_query(source_id)

    # Pre-flight quota check (D-27) — eBay only, skip if dry_run.
    if source_id == "ebay" and not dry_run:
        n = len(query.target_eurio_ids or ([query.target_eurio_id] if query.target_eurio_id else []))
        if n > 0:
            preflight = check_ebay_quota(store, n_eurio_ids=n)
            if not preflight["ok"]:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "quota_insufficient",
                        "estimate": preflight["estimate"],
                        "remaining": preflight["remaining"],
                        "max_safe_batch": preflight["max_safe_batch"],
                        "message": (
                            f"Estimated {preflight['estimate']} calls × 1.3 safety > "
                            f"{preflight['remaining']} remaining today. "
                            f"Reduce batch to ≤{preflight['max_safe_batch']} or wait."
                        ),
                    },
                )

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


# ── Run breakdown (per-eurio_id drill-down) ───────────────────────────────
#
# Cf. docs/sources-refacto/run-breakdown-kickoff.md.
#
# Pure aggregation over existing FK (source_images.run_id, image_assets.run_id,
# coin_market_quotes.run_id, review_queue joined via image_asset_id). No
# schema change. ONE flat list `per_eurio`, ordered: was_targeted=True first
# (preserving user-provided order), then discovered eurios alphabetical.
#
# Counter semantics — designed to leave NO ambiguity, no double-count.
# Each crop belongs to exactly ONE listing with ONE target_eurio_id, so we
# split stats into two strictly disjoint axes per eurio_id E:
#
#   - Search axis (joined via si.target_eurio_id = E): "what came back when
#     we searched for E?" Crops in those listings are partitioned by
#     resolution status — n_searched_auto + n_searched_review_single +
#     n_searched_review_lot + n_searched_pending + n_searched_rejected
#     equals n_crops_searched (the partition is exhaustive).
#
#   - Attribution axis (joined via ia.eurio_id = E AND si.target_eurio_id
#     != E or NULL): "crops attributed to E from listings searched for
#     something else" — typical lot routing case. Disjoint from search axis
#     by construction.
#
# Total crops "ever attributed to E this run" = n_searched_auto + n_attributed_from_other.
# Total crops "in searches for E"             = n_crops_searched.


_AUTO_STATUSES = ("auto_name", "auto_phash", "manual")
_PENDING_STATUSES = ("pending_match", "pending_crop", "needs_review")


class RunBreakdownEntry(BaseModel):
    eurio_id: str
    was_targeted: bool

    # ── Search axis (si.target_eurio_id = E) ──────────────────────────
    n_listings: int                # source_images cherchés pour E
    n_crops_searched: int          # crops dans ces listings

    # Partition exhaustive de n_crops_searched par statut :
    n_searched_auto: int           # status IN auto_name|auto_phash|manual
    n_searched_review_single: int  # rq.kind='single' AND rq.status='open'
    n_searched_review_lot: int     # rq.kind='lot'    AND rq.status='open'
    n_searched_pending: int        # status IN pending_match|pending_crop|needs_review
                                   # ET pas d'entrée review_queue open
    n_searched_rejected: int       # status = 'rejected'

    # ── Attribution axis (ia.eurio_id = E AND si.target_eurio_id != E) ──
    n_attributed_from_other: int   # crops résolus à E depuis un listing
                                   # cherché pour autre chose (cas lot)
    via_lot: bool                  # au moins un de ces crops vient d'un
                                   # listing is_lot_suspected ou multi-crop

    # ── Output ────────────────────────────────────────────────────────
    n_quotes: int                  # coin_market_quotes.eurio_id = E


class RunBreakdown(BaseModel):
    run_id: str
    source_id: str
    started_at: str
    status: str
    filters: dict[str, Any]
    per_eurio: list[RunBreakdownEntry]


def _search_axis_stats(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> dict[str, int]:
    """Stats joined on si.target_eurio_id = eurio_id."""
    n_listings = conn.execute(
        "SELECT COUNT(*) AS n FROM source_images "
        "WHERE run_id = ? AND target_eurio_id = ?",
        (run_id, eurio_id),
    ).fetchone()["n"]

    crops = conn.execute(
        """
        SELECT ia.id, ia.resolution_status
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ? AND si.target_eurio_id = ?
        """,
        (run_id, eurio_id),
    ).fetchall()

    n_auto = 0
    n_pending = 0
    n_rejected = 0
    review_assets: list[str] = []
    for c in crops:
        st = c["resolution_status"]
        if st in _AUTO_STATUSES:
            n_auto += 1
        elif st == "rejected":
            n_rejected += 1
        else:
            # pending_*, needs_review — review_queue may or may not have a row
            review_assets.append(c["id"])
            if st in _PENDING_STATUSES:
                n_pending += 1

    n_rev_single = 0
    n_rev_lot = 0
    if review_assets:
        placeholders = ",".join("?" * len(review_assets))
        rows = conn.execute(
            f"SELECT kind, COUNT(*) AS n FROM review_queue "
            f"WHERE status = 'open' AND image_asset_id IN ({placeholders}) "
            f"GROUP BY kind",
            review_assets,
        ).fetchall()
        for r in rows:
            if r["kind"] == "single":
                n_rev_single = r["n"]
            elif r["kind"] == "lot":
                n_rev_lot = r["n"]
        # Anything in review_queue moves out of "pending" bucket — review
        # is the active state. Pending = needs the resolver/reviewer but
        # not yet enqueued.
        n_pending = max(0, n_pending - (n_rev_single + n_rev_lot))

    return {
        "n_listings": n_listings,
        "n_crops_searched": len(crops),
        "n_searched_auto": n_auto,
        "n_searched_review_single": n_rev_single,
        "n_searched_review_lot": n_rev_lot,
        "n_searched_pending": n_pending,
        "n_searched_rejected": n_rejected,
    }


def _attribution_axis_stats(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> int:
    """Crops resolved to `eurio_id` from listings searched for OTHER eurios."""
    n = conn.execute(
        """
        SELECT COUNT(*) AS n
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ?
           AND ia.eurio_id = ?
           AND (si.target_eurio_id IS NULL OR si.target_eurio_id != ?)
        """,
        (run_id, eurio_id, eurio_id),
    ).fetchone()["n"]
    return int(n or 0)


def _has_lot_context(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> bool:
    """True if any source_image touched by `eurio_id` (via search axis OR
    attribution axis) is is_lot_suspected OR multi-crop.

    Search axis  : si.target_eurio_id = E
    Attribution  : ia.eurio_id = E (ia.run_id = run, ia inside si)
    """
    row = conn.execute(
        """
        SELECT 1
          FROM source_images si
         WHERE si.run_id = ?
           AND (
             si.target_eurio_id = ?
             OR EXISTS (
               SELECT 1 FROM image_assets ia
                WHERE ia.source_image_id = si.id
                  AND ia.run_id = ?
                  AND ia.eurio_id = ?
             )
           )
           AND (
             si.is_lot_suspected = 1
             OR (
               SELECT COUNT(*) FROM image_assets ia2
                WHERE ia2.source_image_id = si.id
             ) > 1
           )
         LIMIT 1
        """,
        (run_id, eurio_id, run_id, eurio_id),
    ).fetchone()
    return row is not None


def _quotes_for(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM coin_market_quotes "
        "WHERE run_id = ? AND eurio_id = ?",
        (run_id, eurio_id),
    ).fetchone()["n"]


def compute_run_breakdown(
    conn: sqlite3.Connection, *, run_id: str, source_id: str,
) -> RunBreakdown:
    """Build the per-eurio_id breakdown for a single run.

    Raises HTTPException(404) if the run doesn't exist.
    """
    row = conn.execute(
        "SELECT * FROM source_runs WHERE id = ? AND source = ?",
        (run_id, source_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    filters: dict[str, Any] = {}
    if row["filters_json"]:
        try:
            filters = json.loads(row["filters_json"])
        except json.JSONDecodeError:
            filters = {"_raw": row["filters_json"]}

    raw_targets = filters.get("target_eurio_ids") or []
    if not isinstance(raw_targets, list):
        raw_targets = []
    targeted_set: set[str] = set()
    targeted_ordered: list[str] = []
    for eid in raw_targets:
        if isinstance(eid, str) and eid not in targeted_set:
            targeted_set.add(eid)
            targeted_ordered.append(eid)

    # Discovered eurios = resolved this run AND not in targets.
    resolved_rows = conn.execute(
        """
        SELECT DISTINCT eurio_id
          FROM image_assets
         WHERE run_id = ? AND eurio_id IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    discovered_ordered = sorted(
        r["eurio_id"] for r in resolved_rows
        if r["eurio_id"] not in targeted_set
    )

    def _build_entry(eid: str, *, was_targeted: bool) -> RunBreakdownEntry:
        search_stats = _search_axis_stats(conn, run_id=run_id, eurio_id=eid)
        attr_count = _attribution_axis_stats(
            conn, run_id=run_id, eurio_id=eid,
        )
        via_lot = _has_lot_context(conn, run_id=run_id, eurio_id=eid)
        n_quotes = _quotes_for(conn, run_id=run_id, eurio_id=eid)
        return RunBreakdownEntry(
            eurio_id=eid,
            was_targeted=was_targeted,
            n_attributed_from_other=attr_count,
            via_lot=via_lot,
            n_quotes=n_quotes,
            **search_stats,
        )

    per_eurio = [
        _build_entry(eid, was_targeted=True) for eid in targeted_ordered
    ] + [
        _build_entry(eid, was_targeted=False) for eid in discovered_ordered
    ]

    return RunBreakdown(
        run_id=row["id"],
        source_id=row["source"],
        started_at=row["started_at"],
        status=row["status"],
        filters=filters,
        per_eurio=per_eurio,
    )


@router.get(
    "/{source_id}/runs/{run_id}/breakdown",
    response_model=RunBreakdown,
)
def get_run_breakdown(source_id: str, run_id: str) -> RunBreakdown:
    conn = _store()._connection()  # noqa: SLF001
    return compute_run_breakdown(conn, run_id=run_id, source_id=source_id)


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


# ── eBay-specific: quota status + freshness queue (D-19/D-20/D-27) ───────


EBAY_DAILY_QUOTA = 5000
ESTIMATE_BOOTSTRAP = 7         # calls/eurio_id avant 3 runs réussis
ESTIMATE_SAFETY_FACTOR = 1.3   # marge appliquée au pre-flight


def _today_period() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ebay_calls_today(store: Store) -> int:
    """Total calls eBay sur la période 'daily' du jour courant."""
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT COALESCE(SUM(calls), 0) AS n
          FROM api_call_log
         WHERE source = 'ebay' AND window = 'daily' AND period = ?
        """,
        (_today_period(),),
    ).fetchone()
    return int(row["n"] or 0)


def estimate_calls_per_eurio_id(store: Store) -> float:
    """Moyenne mobile sur les 5 derniers runs eBay terminés.

    Fallback à `ESTIMATE_BOOTSTRAP` (= 7) si moins de 3 runs ont
    abouti (success ou partial). On compte `n_calls / max(targets, 1)`
    par run, où `targets` = len(filters_json.target_eurio_ids) ou 1.
    """
    conn = store._connection()  # noqa: SLF001
    rows = conn.execute(
        """
        SELECT n_calls, filters_json
          FROM source_runs
         WHERE source = 'ebay'
           AND status IN ('success', 'partial')
           AND n_calls > 0
         ORDER BY started_at DESC
         LIMIT 5
        """
    ).fetchall()
    if len(rows) < 3:
        return float(ESTIMATE_BOOTSTRAP)

    ratios: list[float] = []
    for r in rows:
        targets = 1
        if r["filters_json"]:
            try:
                f = json.loads(r["filters_json"])
                if f.get("target_eurio_ids"):
                    targets = max(len(f["target_eurio_ids"]), 1)
                elif f.get("target_eurio_id"):
                    targets = 1
            except json.JSONDecodeError:
                pass
        ratios.append(r["n_calls"] / targets)
    return sum(ratios) / len(ratios)


def check_ebay_quota(store: Store, *, n_eurio_ids: int) -> dict[str, Any]:
    """Pre-flight quota check (D-27).

    Returns a dict with `ok`, `estimate`, `remaining`, `max_safe_batch`.
    """
    avg = estimate_calls_per_eurio_id(store)
    estimate = int(round(avg * n_eurio_ids))
    remaining = max(EBAY_DAILY_QUOTA - ebay_calls_today(store), 0)
    safe_threshold = estimate * ESTIMATE_SAFETY_FACTOR
    ok = remaining >= safe_threshold
    max_safe = int(remaining / (avg * ESTIMATE_SAFETY_FACTOR)) if avg > 0 else 0
    return {
        "ok": ok,
        "estimate": estimate,
        "remaining": remaining,
        "limit": EBAY_DAILY_QUOTA,
        "avg_calls_per_eurio_id": round(avg, 2),
        "max_safe_batch": max_safe,
    }


class EbayQuotaStatus(BaseModel):
    calls_today: int
    limit: int
    remaining: int
    exhausted: bool
    period: str
    avg_calls_per_eurio_id: float


@router.get("/ebay/quota-status", response_model=EbayQuotaStatus)
def ebay_quota_status() -> EbayQuotaStatus:
    store = _store()
    calls = ebay_calls_today(store)
    return EbayQuotaStatus(
        calls_today=calls,
        limit=EBAY_DAILY_QUOTA,
        remaining=max(EBAY_DAILY_QUOTA - calls, 0),
        exhausted=calls >= EBAY_DAILY_QUOTA,
        period=_today_period(),
        avg_calls_per_eurio_id=round(estimate_calls_per_eurio_id(store), 2),
    )


class FreshnessItem(BaseModel):
    eurio_id: str
    country: str
    year: int
    last_enriched_at: str | None
    n_images: int
    n_crops: int
    status: str   # 'never' | 'stale' | 'fresh'


class FreshnessBuckets(BaseModel):
    never: int
    stale_90d: int
    fresh: int
    total: int


class EbayFreshnessResponse(BaseModel):
    items: list[FreshnessItem]
    buckets: FreshnessBuckets


def _classify_freshness(last_enriched_at: str | None, stale_days: int = 90) -> str:
    if last_enriched_at is None:
        return "never"
    from datetime import datetime, timedelta, timezone
    try:
        dt = datetime.fromisoformat(last_enriched_at.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return "never"
    if datetime.now(timezone.utc) - dt > timedelta(days=stale_days):
        return "stale"
    return "fresh"


@router.get("/ebay/freshness", response_model=EbayFreshnessResponse)
def ebay_freshness(
    limit: int = Query(default=50, ge=1, le=500),
) -> EbayFreshnessResponse:
    """Freshness queue : eurio_ids commémo 2€ non-EU triés par `last_enriched_at ASC NULLS FIRST`.

    Lit la vue SQL `v_ebay_freshness` (D-20). Buckets calculés sur
    l'ensemble (pas le slice `limit`).
    """
    conn = _store()._connection()  # noqa: SLF001

    all_rows = conn.execute(
        """
        SELECT eurio_id, country, year, last_enriched_at, n_images, n_crops
          FROM v_ebay_freshness
         ORDER BY last_enriched_at ASC NULLS FIRST, eurio_id
        """
    ).fetchall()

    buckets = {"never": 0, "stale": 0, "fresh": 0}
    classified: list[tuple[Any, str]] = []
    for r in all_rows:
        status = _classify_freshness(r["last_enriched_at"])
        buckets[status] += 1
        classified.append((r, status))

    items = [
        FreshnessItem(
            eurio_id=r["eurio_id"],
            country=r["country"],
            year=r["year"],
            last_enriched_at=r["last_enriched_at"],
            n_images=r["n_images"] or 0,
            n_crops=r["n_crops"] or 0,
            status=status,
        )
        for r, status in classified[:limit]
    ]
    return EbayFreshnessResponse(
        items=items,
        buckets=FreshnessBuckets(
            never=buckets["never"],
            stale_90d=buckets["stale"],
            fresh=buckets["fresh"],
            total=len(all_rows),
        ),
    )


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
