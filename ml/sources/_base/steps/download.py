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

import httpx

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


# Called by: ml/sources/_base/orchestrator.py (step 4/8 — after text_signal, skips rows with route_decision='rejected_text')
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
            "SELECT id, source_url, listing_title, storage_path, route_decision "
            "FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None:
            logger.error("[%s] download: missing source_image id=%s", adapter.source_id, sid)
            n_errors += 1
            run.bump(n_errors=1)
            continue

        # Chunk 6.c — text_signal step a déjà rejeté ce listing (verdict
        # contradict). On saute le download : économie de quota CDN +
        # détection de crops sur des listings clairement mauvais.
        if row["route_decision"] == "rejected_text":
            n_skipped += 1
            continue

        existing = row["storage_path"]
        if existing and Path(existing).is_file():
            n_skipped += 1
            conn.execute(
                """
                UPDATE source_images
                   SET download_status = COALESCE(download_status, 'skipped')
                 WHERE id = ?
                """,
                (sid,),
            )
            continue

        dest = raw_path(adapter.source_id, source_ref)
        payload = _load_payload(conn, sid)
        attempted_url = (payload or {}).get("image_url") if payload else None
        # Re-hydrate the minimal DiscoveredItem the adapter needs for
        # download; we only carry through what's strictly required.
        from sources._base.adapter import DiscoveredItem
        item = DiscoveredItem(
            source_ref=source_ref,
            source_url=row["source_url"],
            listing_title=row["listing_title"],
            raw_payload=payload,
        )
        try:
            res = adapter.download_raw(item, dest)
        except Exception as exc:  # noqa: BLE001 — bubbled to source_runs.error_summary via counter
            logger.error(
                "[%s] download FAILED source_ref=%s: %s",
                adapter.source_id, source_ref, exc,
            )
            http_status: int | None = None
            if isinstance(exc, httpx.HTTPStatusError):
                http_status = exc.response.status_code
            conn.execute(
                """
                UPDATE source_images
                   SET download_endpoint    = ?,
                       download_status      = 'failed',
                       download_http_status = ?,
                       download_error       = ?
                 WHERE id = ?
                """,
                (attempted_url, http_status, str(exc)[:500], sid),
            )
            n_errors += 1
            run.bump(n_errors=1)
            continue

        conn.execute(
            """
            UPDATE source_images
               SET storage_path = ?, bytes = ?, sha256 = ?,
                   width = COALESCE(?, width), height = COALESCE(?, height),
                   download_endpoint    = ?,
                   download_status      = 'success',
                   download_http_status = ?,
                   download_error       = NULL
             WHERE id = ?
            """,
            (
                str(res.storage_path), res.bytes, res.sha256, res.width, res.height,
                res.endpoint_url or attempted_url,
                res.http_status,
                sid,
            ),
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
