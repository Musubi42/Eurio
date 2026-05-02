"""Step 5 — Resolve.

V1 policy (kickoff §"2.D"): no auto-name. Every freshly-cropped asset
that isn't already resolved by `auto_phash` (step 4) is marked
`needs_review` so a human can decide. The auto-name path will be
re-introduced in a later chunk once we have real listing data to
calibrate a precision threshold against.

Also advances `discovery_log.pipeline_state` to 'resolved' for items
that have at least one image_asset reaching a terminal status
('auto_phash' or 'needs_review' both count as "resolved enough to
move on").
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from sources._base.dedup import set_discovery_pipeline_state
from sources._base.run_logger import RunHandle

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = ("auto_name", "auto_phash", "manual", "needs_review", "rejected")


@dataclass
class ResolveResult:
    n_marked_review: int
    n_skipped_already_resolved: int


def run_resolve(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    source_id: str,
    source_image_ids: dict[str, str],
) -> ResolveResult:
    n_marked = 0
    n_skipped = 0

    for source_ref, sid in source_image_ids.items():
        rows = conn.execute(
            "SELECT id, resolution_status FROM image_assets WHERE source_image_id = ?",
            (sid,),
        ).fetchall()
        for r in rows:
            if r["resolution_status"] in ("auto_phash", "auto_name", "manual", "rejected"):
                n_skipped += 1
                continue
            conn.execute(
                "UPDATE image_assets SET resolution_status='needs_review' WHERE id=?",
                (r["id"],),
            )
            n_marked += 1

        if rows:
            set_discovery_pipeline_state(
                conn, source=source_id, source_ref=source_ref, state="resolved"
            )

    logger.info(
        "[%s] resolve → %d marked needs_review / %d already-resolved",
        source_id, n_marked, n_skipped,
    )
    return ResolveResult(n_marked_review=n_marked, n_skipped_already_resolved=n_skipped)
