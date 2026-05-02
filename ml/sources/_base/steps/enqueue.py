"""Step 6 — Enqueue review.

Inserts one `review_queue` row per `image_assets` flagged
`needs_review`. The `UNIQUE (image_asset_id)` on `review_queue` makes
the upsert idempotent: re-running the pipeline on the same data
inserts zero new rows.

Priority (review-queue.md §"Priorisation"):
    100 base
    -30 if the source_image had a target_eurio_id (the fetch was
        targeted, the human just needs to confirm)

The other modifiers (commemorative, rare, multi-coin, quality_score)
need joins / signals we don't compute yet — they'll plug in when
those signals exist.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass

from sources._base.run_logger import RunHandle

logger = logging.getLogger(__name__)

_BASE_PRIORITY = 100
_BONUS_TARGETED = 30


@dataclass
class EnqueueResult:
    n_enqueued: int
    n_skipped_already_queued: int


def _compute_priority(*, target_eurio_id: str | None) -> int:
    p = _BASE_PRIORITY
    if target_eurio_id:
        p -= _BONUS_TARGETED
    return p


def run_enqueue(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    source_id: str,
    source_image_ids: dict[str, str],
) -> EnqueueResult:
    n_enqueued = 0
    n_skipped = 0

    for sid in source_image_ids.values():
        rows = conn.execute(
            """
            SELECT a.id AS asset_id,
                   a.candidate_eurio_ids_json,
                   s.target_eurio_id
              FROM image_assets a
              JOIN source_images s ON s.id = a.source_image_id
             WHERE a.source_image_id = ?
               AND a.resolution_status = 'needs_review'
            """,
            (sid,),
        ).fetchall()
        for r in rows:
            already = conn.execute(
                "SELECT 1 FROM review_queue WHERE image_asset_id = ?",
                (r["asset_id"],),
            ).fetchone()
            if already:
                n_skipped += 1
                continue

            priority = _compute_priority(target_eurio_id=r["target_eurio_id"])
            candidates = r["candidate_eurio_ids_json"]
            conn.execute(
                """
                INSERT INTO review_queue (
                  id, image_asset_id, priority, candidate_eurio_ids_json
                ) VALUES (?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, r["asset_id"], priority, candidates),
            )
            n_enqueued += 1

    run.bump(n_review_enqueued=n_enqueued)
    logger.info(
        "[%s] enqueue → %d new / %d already-queued",
        source_id, n_enqueued, n_skipped,
    )
    return EnqueueResult(n_enqueued=n_enqueued, n_skipped_already_queued=n_skipped)
