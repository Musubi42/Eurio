"""FastAPI router for the `/operations` dashboard.

Spec: `docs/operations/dashboard-j1.md`. Endpoint surface kept narrow —
admin frontend polls infrequently (page-open + manual refresh, no live
push). All data comes from `eurio.db` (SQLite, source of truth).

Endpoints
---------
- `GET /operations/pulse`              → Section 1, 7d eBay activity
- `GET /operations/training-readiness` → Section 2, per-class canon+wild counts
- `GET /operations/wild-diversity`     → Section 3, marketplace contribution
- `GET /operations/cohorts`            → Section 4, cohort status (no captures)
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from store import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operations", tags=["operations"])

# Acted threshold (cf. docs/roadmap.md J4, docs/operations/dashboard-j1.md).
TRAINING_THRESHOLD = 30
TIER_RED_MAX = 5  # < 5 = red


def _store() -> Store:
    # Lean-image safe : import depuis server_serve (no training deps) ;
    # fallback sur server.py pour les workstations full (workstation FastAPI).
    try:
        from .server_serve import _store as shared_store
    except ImportError:
        from .server import _store as shared_store
    return shared_store


def _conn() -> sqlite3.Connection:
    return _store()._connection()  # noqa: SLF001


# ── Section 1 — Pulse eBay ────────────────────────────────────────────────


class PulseDay(BaseModel):
    day: str
    marketplace: str
    searches: int
    raw: int
    kept: int


class PulseMarketplaceTotal(BaseModel):
    marketplace: str
    searches: int
    raw: int
    kept: int
    recall_pct: float


class PulseLastRun(BaseModel):
    run_id: str | None
    started_at: str | None
    ended_at: str | None
    status: str | None


class PulseResponse(BaseModel):
    window_days: int
    days: list[PulseDay]
    by_marketplace: list[PulseMarketplaceTotal]
    last_run: PulseLastRun


@router.get("/pulse", response_model=PulseResponse)
def pulse(window_days: int = Query(7, ge=1, le=30)) -> PulseResponse:
    """Aggregate eBay discovery activity over the last `window_days` days."""
    conn = _conn()
    try:
        rows = conn.execute(
            f"""
            SELECT date(created_at) AS day,
                   COALESCE(marketplace, 'UNKNOWN') AS mkt,
                   COUNT(*) AS searches,
                   COALESCE(SUM(n_raw_results), 0) AS raw,
                   COALESCE(SUM(n_kept_results), 0) AS kept
            FROM discovery_searches
            WHERE source = 'ebay'
              AND created_at >= datetime('now', '-{int(window_days)} days')
            GROUP BY day, mkt
            ORDER BY day, mkt
            """
        ).fetchall()
        totals = conn.execute(
            f"""
            SELECT COALESCE(marketplace, 'UNKNOWN') AS mkt,
                   COUNT(*) AS searches,
                   COALESCE(SUM(n_raw_results), 0) AS raw,
                   COALESCE(SUM(n_kept_results), 0) AS kept
            FROM discovery_searches
            WHERE source = 'ebay'
              AND created_at >= datetime('now', '-{int(window_days)} days')
            GROUP BY mkt
            ORDER BY kept DESC
            """
        ).fetchall()
        last = conn.execute(
            """
            SELECT id, started_at, ended_at, status
            FROM source_runs
            WHERE source = 'ebay'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    days = [
        PulseDay(day=r[0], marketplace=r[1], searches=r[2], raw=r[3], kept=r[4])
        for r in rows
    ]
    by_mkt = [
        PulseMarketplaceTotal(
            marketplace=r[0],
            searches=r[1],
            raw=r[2],
            kept=r[3],
            recall_pct=(r[3] / r[2] * 100.0) if r[2] else 0.0,
        )
        for r in totals
    ]
    last_run = PulseLastRun(
        run_id=last[0] if last else None,
        started_at=last[1] if last else None,
        ended_at=last[2] if last else None,
        status=last[3] if last else None,
    )
    return PulseResponse(
        window_days=window_days, days=days, by_marketplace=by_mkt, last_run=last_run
    )


# ── Section 2 — Training readiness ────────────────────────────────────────


class ClassReadiness(BaseModel):
    class_id: str
    eurio_ids: list[str]
    label: str | None
    country: str | None
    year: int | None
    n_canon: int
    n_wild: int
    n_total: int
    tier: str  # 'red' | 'warn' | 'green'


class ReadinessSummary(BaseModel):
    threshold: int
    tier_red_max: int
    n_classes: int
    n_green: int
    n_warn: int
    n_red: int
    histogram: list[dict[str, Any]]


class ReadinessResponse(BaseModel):
    summary: ReadinessSummary
    classes: list[ClassReadiness]


def _tier(n: int) -> str:
    if n >= TRAINING_THRESHOLD:
        return "green"
    if n < TIER_RED_MAX:
        return "red"
    return "warn"


@router.get("/training-readiness", response_model=ReadinessResponse)
def training_readiness(
    tier: str | None = Query(None, pattern="^(red|warn|green)$"),
    country: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
) -> ReadinessResponse:
    """Per-class canon+wild count, tier'd against the 30-sources threshold."""
    conn = _conn()
    try:
        rows = conn.execute(
            """
            WITH class_map AS (
              SELECT eurio_id,
                     COALESCE(design_group_id, eurio_id) AS class_id,
                     country, year, theme
              FROM coins
              WHERE face_value = 2.0 AND is_commemorative = 1
            ),
            canon AS (
              SELECT m.class_id, COUNT(*) AS n_canon
              FROM coin_canonical_images c
              JOIN class_map m ON m.eurio_id = c.eurio_id
              GROUP BY m.class_id
            ),
            wild AS (
              SELECT m.class_id, COUNT(*) AS n_wild
              FROM source_images s
              JOIN class_map m ON m.eurio_id = s.target_eurio_id
              WHERE s.storage_status = 'present'
              GROUP BY m.class_id
            ),
            classes AS (
              SELECT class_id,
                     MIN(country) AS country,
                     MIN(year)    AS year,
                     MIN(theme)   AS theme,
                     GROUP_CONCAT(eurio_id) AS eurio_ids
              FROM class_map
              GROUP BY class_id
            )
            SELECT cl.class_id,
                   cl.eurio_ids,
                   cl.theme,
                   cl.country,
                   cl.year,
                   COALESCE(canon.n_canon, 0) AS n_canon,
                   COALESCE(wild.n_wild, 0)   AS n_wild
            FROM classes cl
            LEFT JOIN canon USING (class_id)
            LEFT JOIN wild  USING (class_id)
            ORDER BY (COALESCE(canon.n_canon, 0) + COALESCE(wild.n_wild, 0)) ASC,
                     cl.class_id ASC
            """
        ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    classes: list[ClassReadiness] = []
    n_red = n_warn = n_green = 0
    for r in rows:
        n_canon = int(r[5] or 0)
        n_wild = int(r[6] or 0)
        n_total = n_canon + n_wild
        t = _tier(n_total)
        if t == "red":
            n_red += 1
        elif t == "warn":
            n_warn += 1
        else:
            n_green += 1
        classes.append(
            ClassReadiness(
                class_id=r[0],
                eurio_ids=(r[1] or "").split(",") if r[1] else [],
                label=r[2],
                country=r[3],
                year=r[4],
                n_canon=n_canon,
                n_wild=n_wild,
                n_total=n_total,
                tier=t,
            )
        )

    filtered = classes
    if tier:
        filtered = [c for c in filtered if c.tier == tier]
    if country:
        filtered = [c for c in filtered if c.country == country]
    filtered = filtered[:limit]

    # Coarse histogram: 0, 1-4, 5-9, 10-19, 20-29, 30-49, 50-99, 100+
    bins = [(0, 0), (1, 4), (5, 9), (10, 19), (20, 29), (30, 49), (50, 99), (100, 10**9)]
    histogram = []
    for lo, hi in bins:
        n = sum(1 for c in classes if lo <= c.n_total <= hi)
        label = f"{lo}" if lo == hi else (f"{lo}+" if hi == 10**9 else f"{lo}-{hi}")
        histogram.append({"bucket": label, "count": n, "lo": lo, "hi": hi if hi < 10**9 else None})

    summary = ReadinessSummary(
        threshold=TRAINING_THRESHOLD,
        tier_red_max=TIER_RED_MAX,
        n_classes=len(classes),
        n_green=n_green,
        n_warn=n_warn,
        n_red=n_red,
        histogram=histogram,
    )
    return ReadinessResponse(summary=summary, classes=filtered)


# ── Section 3 — Wild diversity ────────────────────────────────────────────


class DiversityBucket(BaseModel):
    n_marketplaces: int
    n_classes: int


class DiversityResponse(BaseModel):
    buckets: list[DiversityBucket]
    top_marketplaces_7d: list[dict[str, Any]]
    suspicious_singletons: int  # n_marketplaces=1 but n_wild>=30


@router.get("/wild-diversity", response_model=DiversityResponse)
def wild_diversity() -> DiversityResponse:
    conn = _conn()
    try:
        rows = conn.execute(
            """
            WITH class_map AS (
              SELECT eurio_id, COALESCE(design_group_id, eurio_id) AS class_id
              FROM coins WHERE face_value = 2.0 AND is_commemorative = 1
            ),
            per_class AS (
              SELECT m.class_id,
                     COUNT(DISTINCT s.marketplace) AS n_mkt,
                     COUNT(*) AS n_wild
              FROM source_images s
              JOIN class_map m ON m.eurio_id = s.target_eurio_id
              WHERE s.marketplace IS NOT NULL AND s.storage_status = 'present'
              GROUP BY m.class_id
            )
            SELECT class_id, n_mkt, n_wild FROM per_class
            """
        ).fetchall()
        total_classes_row = conn.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(design_group_id, eurio_id))
            FROM coins WHERE face_value = 2.0 AND is_commemorative = 1
            """
        ).fetchone()
        top = conn.execute(
            """
            SELECT COALESCE(marketplace, 'UNKNOWN') AS mkt, COUNT(*) AS kept
            FROM source_images
            WHERE marketplace IS NOT NULL
              AND fetched_at >= datetime('now', '-7 days')
              AND storage_status = 'present'
            GROUP BY mkt
            ORDER BY kept DESC
            LIMIT 10
            """
        ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    bucket_counts: dict[int, int] = {}
    suspicious = 0
    seen_classes = set()
    for class_id, n_mkt, n_wild in rows:
        seen_classes.add(class_id)
        bucket_counts[n_mkt] = bucket_counts.get(n_mkt, 0) + 1
        if n_mkt == 1 and n_wild >= TRAINING_THRESHOLD:
            suspicious += 1

    total_classes = int(total_classes_row[0] or 0)
    zero_classes = total_classes - len(seen_classes)
    buckets = [DiversityBucket(n_marketplaces=0, n_classes=zero_classes)]
    for n_mkt in sorted(bucket_counts):
        buckets.append(DiversityBucket(n_marketplaces=n_mkt, n_classes=bucket_counts[n_mkt]))

    return DiversityResponse(
        buckets=buckets,
        top_marketplaces_7d=[{"marketplace": r[0], "kept": r[1]} for r in top],
        suspicious_singletons=suspicious,
    )


# ── Section 4 — Cohort status ─────────────────────────────────────────────


class CohortRow(BaseModel):
    id: str
    name: str
    status: str
    zone: str | None
    n_members: int
    frozen_at: str | None
    created_at: str


class CohortResponse(BaseModel):
    n_draft: int
    n_frozen: int
    cohorts: list[CohortRow]


@router.get("/cohorts", response_model=CohortResponse)
def cohorts() -> CohortResponse:
    """Cohort status from eurio.db. Capture counts live on the PC filesystem
    (`ml/datasets/<numista_id>/captures/`) — not exposed in MVP per spec.
    """
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT c.id, c.name, c.status, c.zone, c.frozen_at, c.created_at,
                   COALESCE((SELECT COUNT(*) FROM cohort_members m WHERE m.cohort_id = c.id), 0) AS n_members
            FROM experiment_cohorts c
            ORDER BY (c.status = 'frozen') DESC, c.created_at DESC
            """
        ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    cohort_rows = [
        CohortRow(
            id=r[0], name=r[1], status=r[2], zone=r[3],
            frozen_at=r[4], created_at=r[5], n_members=int(r[6] or 0),
        )
        for r in rows
    ]
    return CohortResponse(
        n_draft=sum(1 for c in cohort_rows if c.status == "draft"),
        n_frozen=sum(1 for c in cohort_rows if c.status == "frozen"),
        cohorts=cohort_rows,
    )
