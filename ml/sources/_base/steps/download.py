"""Step 3 — Download.

Asks the adapter to write the raw file to its canonical path. Skips
when the row already has a `storage_path` and the file is on disk
(dedup layer 3). Errors on a single item don't abort the run — the
item is counted in `n_errors`, the rest of the batch keeps going.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sources._base.adapter import SourceAdapter
from sources._base.dedup import set_discovery_pipeline_state
from sources._base.run_logger import RunHandle
from sources._base.storage import raw_path

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    n_downloaded: int
    n_skipped: int
    n_errors: int


def run_download(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    adapter: SourceAdapter,
    source_image_ids: dict[str, str],   # source_ref -> source_images.id
) -> DownloadResult:
    n_downloaded = 0
    n_skipped = 0
    n_errors = 0

    for source_ref, sid in source_image_ids.items():
        row = conn.execute(
            "SELECT id, source_url, listing_title, storage_path "
            "FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None:
            logger.error("[%s] download: missing source_image id=%s", adapter.source_id, sid)
            n_errors += 1
            run.bump(n_errors=1)
            continue

        existing = row["storage_path"]
        if existing and Path(existing).is_file():
            n_skipped += 1
            continue

        dest = raw_path(adapter.source_id, source_ref)
        # Re-hydrate the minimal DiscoveredItem the adapter needs for
        # download; we only carry through what's strictly required.
        from sources._base.adapter import DiscoveredItem
        item = DiscoveredItem(
            source_ref=source_ref,
            source_url=row["source_url"],
            listing_title=row["listing_title"],
            raw_payload=_load_payload(conn, sid),
        )
        try:
            res = adapter.download_raw(item, dest)
        except Exception as exc:  # noqa: BLE001 — bubbled to source_runs.error_summary via counter
            logger.error(
                "[%s] download FAILED source_ref=%s: %s",
                adapter.source_id, source_ref, exc,
            )
            n_errors += 1
            run.bump(n_errors=1)
            continue

        conn.execute(
            """
            UPDATE source_images
               SET storage_path = ?, bytes = ?, sha256 = ?,
                   width = COALESCE(?, width), height = COALESCE(?, height)
             WHERE id = ?
            """,
            (str(res.storage_path), res.bytes, res.sha256, res.width, res.height, sid),
        )
        set_discovery_pipeline_state(
            conn, source=adapter.source_id, source_ref=source_ref, state="downloaded"
        )
        n_downloaded += 1

    logger.info(
        "[%s] download → %d new / %d skipped / %d errors",
        adapter.source_id, n_downloaded, n_skipped, n_errors,
    )
    return DownloadResult(n_downloaded=n_downloaded, n_skipped=n_skipped, n_errors=n_errors)


def _load_payload(conn: sqlite3.Connection, sid: str) -> dict | None:
    import json
    row = conn.execute(
        "SELECT raw_payload_json FROM source_images WHERE id = ?", (sid,)
    ).fetchone()
    if row is None or row["raw_payload_json"] is None:
        return None
    return json.loads(row["raw_payload_json"])
