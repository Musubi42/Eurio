"""FastAPI router for `/review-queue`.

Surfaces the queue managed by `ml/sources/_base/steps/enqueue.py`. The
admin front (`admin/packages/web/src/features/review/`) consumes this
router single-item-style: list 20 → pick one → decide / skip / reject
→ go back to list. No multi-select per D-16.

Decisions write back to `image_assets` (resolution_status, eurio_id,
face, variant_kind) AND to `review_queue` (decided_*, status='done').
The two writes happen in a single transaction so the queue and the
asset never disagree.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from state import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/review-queue", tags=["review-queue"])

_VALID_FACES = ("obverse", "reverse", "unknown")
_SKIP_PRIORITY_BUMP = 50


def _store() -> Store:
    from .server import _store as shared_store
    return shared_store


# ── List ──────────────────────────────────────────────────────────────────


class ReviewBbox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ReviewCandidate(BaseModel):
    eurio_id: str
    score: float
    label: str
    country: str
    denomination: str
    year: int | None = None
    canonical_thumb_url: str = ""


class ReviewItem(BaseModel):
    id: str
    crop_url: str
    bbox: ReviewBbox | None
    source: str
    source_ref: str
    listing_title: str | None
    listing_url: str | None
    listing_price: float | None
    candidates: list[ReviewCandidate]
    face_detected: str | None
    priority: int
    is_multi_coin_lot: bool
    quality_score: float
    enqueued_at: str


def _row_to_item(row: sqlite3.Row) -> ReviewItem:
    bbox: ReviewBbox | None = None
    if row["bbox_json"]:
        try:
            d = json.loads(row["bbox_json"])
            bbox = ReviewBbox(x=d.get("x", 0), y=d.get("y", 0),
                              w=d.get("w", 0), h=d.get("h", 0))
        except (json.JSONDecodeError, TypeError):
            bbox = None

    candidates: list[ReviewCandidate] = []
    if row["candidate_eurio_ids_json"]:
        try:
            raw = json.loads(row["candidate_eurio_ids_json"])
            for c in raw if isinstance(raw, list) else []:
                if not isinstance(c, dict) or "eurio_id" not in c:
                    continue
                candidates.append(ReviewCandidate(
                    eurio_id=c["eurio_id"],
                    score=float(c.get("score", 0)),
                    label=c.get("label", c["eurio_id"]),
                    country=c.get("country", ""),
                    denomination=c.get("denomination", ""),
                    year=c.get("year"),
                    canonical_thumb_url=c.get("canonical_thumb_url", ""),
                ))
        except json.JSONDecodeError:
            pass

    return ReviewItem(
        id=row["id"],
        crop_url=f"/sources/{row['source']}/assets/{row['image_asset_id']}/file",
        bbox=bbox,
        source=row["source"],
        source_ref=row["source_ref"],
        listing_title=row["listing_title"],
        listing_url=row["source_url"],
        listing_price=row["listing_price"],
        candidates=candidates,
        face_detected=row["face"],
        priority=row["priority"],
        is_multi_coin_lot=False,  # detection landing later
        quality_score=row["quality_score"] or 0.0,
        enqueued_at=row["enqueued_at"],
    )


@router.get("", response_model=list[ReviewItem])
def list_queue(
    status: str = Query(default="open"),
    limit: int = Query(default=20, ge=1, le=200),
    order: str = Query(default="priority"),
) -> list[ReviewItem]:
    if order not in ("priority", "enqueued_at"):
        raise HTTPException(status_code=422, detail="order must be 'priority' or 'enqueued_at'")
    order_clause = "rq.priority ASC, rq.enqueued_at ASC" \
        if order == "priority" else "rq.enqueued_at ASC"

    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        f"""
        SELECT rq.id, rq.image_asset_id, rq.priority, rq.enqueued_at,
               rq.candidate_eurio_ids_json AS rq_candidates,
               a.bbox_json, a.candidate_eurio_ids_json, a.face, a.quality_score,
               s.source, s.source_ref, s.listing_title, s.source_url,
               s.listing_price
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
         WHERE rq.status = ?
         ORDER BY {order_clause}
         LIMIT ?
        """,
        (status, limit),
    ).fetchall()
    return [_row_to_item(r) for r in rows]


@router.get("/stats")
def queue_stats() -> dict[str, Any]:
    """Counts for the queue header strip. Cheap (single query)."""
    conn = _store()._connection()  # noqa: SLF001
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    n_pending = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'open'"
    ).fetchone()["c"]
    n_done_today = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (today,),
    ).fetchone()["c"]
    n_done_week = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (week_start,),
    ).fetchone()["c"]
    # Median seconds: rough proxy — diff between decided_at and enqueued_at
    # over the last 100 done items. Cheap, no real percentile needed yet.
    deltas: list[float] = []
    for r in conn.execute(
        """
        SELECT enqueued_at, decided_at FROM review_queue
         WHERE status = 'done' AND decided_at IS NOT NULL
         ORDER BY decided_at DESC LIMIT 100
        """
    ).fetchall():
        try:
            t0 = datetime.fromisoformat(r["enqueued_at"].replace(" ", "T"))
            t1 = datetime.fromisoformat(r["decided_at"].replace(" ", "T"))
            deltas.append((t1 - t0).total_seconds())
        except Exception:  # noqa: BLE001
            continue
    deltas.sort()
    median = deltas[len(deltas) // 2] if deltas else 0.0

    return {
        "n_pending": n_pending,
        "n_done_today": n_done_today,
        "n_done_this_week": n_done_week,
        "median_seconds_per_decision": round(median, 1),
    }


@router.get("/{review_id}", response_model=ReviewItem)
def get_review(review_id: str) -> ReviewItem:
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT rq.id, rq.image_asset_id, rq.priority, rq.enqueued_at,
               rq.candidate_eurio_ids_json AS rq_candidates,
               a.bbox_json, a.candidate_eurio_ids_json, a.face, a.quality_score,
               s.source, s.source_ref, s.listing_title, s.source_url,
               s.listing_price
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return _row_to_item(row)


# ── Mutations ─────────────────────────────────────────────────────────────


class DecidePayload(BaseModel):
    eurio_id: str = Field(min_length=1)
    face: str
    variant_kind: str | None = None
    notes: str | None = None


@router.post("/{review_id}/decide", status_code=200)
def decide_review(review_id: str, payload: DecidePayload) -> dict[str, str]:
    if payload.face not in _VALID_FACES:
        raise HTTPException(
            status_code=422, detail=f"face must be one of {_VALID_FACES}",
        )

    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot decide twice.",
        )

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    asset_id = rq["image_asset_id"]

    # Two-step transaction: image_assets + review_queue.
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET eurio_id = ?,
                   face = ?,
                   variant_kind = COALESCE(?, variant_kind),
                   resolution_status = 'manual',
                   resolution_confidence = 1.0,
                   resolved_at = ?
             WHERE id = ?
            """,
            (payload.eurio_id, payload.face, payload.variant_kind, now_iso, asset_id),
        )
        conn.execute(
            """
            UPDATE review_queue
               SET status = 'done',
                   decided_eurio_id = ?,
                   decided_face = ?,
                   decided_variant_kind = ?,
                   decision_notes = ?,
                   decided_at = ?,
                   decided_by = 'admin'
             WHERE id = ?
            """,
            (payload.eurio_id, payload.face, payload.variant_kind,
             payload.notes, now_iso, review_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("[review] decided id=%s eurio_id=%s face=%s",
                review_id, payload.eurio_id, payload.face)
    return {"status": "done", "id": review_id}


@router.post("/{review_id}/reject", status_code=200)
def reject_review(review_id: str) -> dict[str, str]:
    """Mark the IMAGE as unusable (not the review row's status). The row
    is closed with `decision_notes='rejected'` and the underlying
    `image_assets` row gets `resolution_status='rejected'`."""
    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot reject twice.",
        )

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET resolution_status = 'rejected', resolved_at = ?
             WHERE id = ?
            """,
            (now_iso, rq["image_asset_id"]),
        )
        conn.execute(
            """
            UPDATE review_queue
               SET status = 'done',
                   decision_notes = 'rejected',
                   decided_at = ?,
                   decided_by = 'admin'
             WHERE id = ?
            """,
            (now_iso, review_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("[review] rejected id=%s", review_id)
    return {"status": "rejected", "id": review_id}


@router.post("/{review_id}/skip", status_code=200)
def skip_review(review_id: str) -> dict[str, Any]:
    """Defer this item: bump `priority` so it lands further down the
    queue, but keep `status='open'`. No write to `image_assets`."""
    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, status, priority FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review is {rq['status']} — only open items can be skipped.",
        )
    new_priority = rq["priority"] + _SKIP_PRIORITY_BUMP
    conn.execute(
        "UPDATE review_queue SET priority = ? WHERE id = ?",
        (new_priority, review_id),
    )
    logger.info("[review] skipped id=%s new_priority=%d", review_id, new_priority)
    return {"status": "skipped", "id": review_id, "new_priority": new_priority}
