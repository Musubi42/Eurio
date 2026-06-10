"""Step 3 — Download (write-through MinIO).

Asks the adapter to fetch the raw image bytes (to a local cache path),
then uploads them to MinIO `enrichment-raws`. The DB row's
`source_images.storage_path` ends up holding the S3 key (NOT a local FS
path) and `storage_status='present'`.

Idempotence : skip rows where `storage_status='present'` and
`storage_path` is set — the bytes are already in MinIO.

Errors on a single item don't abort the run — the item is counted in
`n_errors`, the rest of the batch keeps going. A MinIO outage triggers
exponential backoff inside `upload_through` (~17 min total) — beyond
that the item errors out cleanly.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import httpx

from sources._base.adapter import SourceAdapter
from sources._base.dedup import set_discovery_pipeline_state
from sources._base.run_logger import RunHandle
from sources._base.storage import raw_cache_path, raw_key
from shared.storage.local_cache import upload_through

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    n_downloaded: int
    n_skipped: int
    n_errors: int


# Called by: ml/sources/_base/orchestrator.py (step 4/8 — after text_signal)
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
            "SELECT id, source_url, listing_title, storage_path, storage_status "
            "FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None:
            logger.error("[%s] download: missing source_image id=%s", adapter.source_id, sid)
            n_errors += 1
            run.bump(n_errors=1)
            continue

        # NB (C3) : plus de skip sur ``route_decision='rejected_text'``. Le kill
        # dur contradict est supprimé (text_signal n'écrit plus ce flag) — un
        # contradict traverse maintenant download → crop → dino → consensus. Les
        # vieux source_images encore marqués ``rejected_text`` (data legacy) se
        # re-téléchargent donc au prochain run de leur cohorte = le rescue voulu.

        # Idempotence : already uploaded to MinIO (DB authority — trust it,
        # downstream local_path() does cache-or-fetch).
        if row["storage_path"] and row["storage_status"] == "present":
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

        storage_key = raw_key(adapter.source_id, run.run_id, sid)
        cache_dest = raw_cache_path(adapter.source_id, run.run_id, sid)
        cache_dest.parent.mkdir(parents=True, exist_ok=True)

        payload = _load_payload(conn, sid)
        attempted_url = (payload or {}).get("image_url") if payload else None
        from sources._base.adapter import DiscoveredItem
        item = DiscoveredItem(
            source_ref=source_ref,
            source_url=row["source_url"],
            listing_title=row["listing_title"],
            raw_payload=payload,
        )
        try:
            # Adapter writes to local cache (atomic). We then push to MinIO.
            res = adapter.download_raw(item, cache_dest)
        except Exception as exc:  # noqa: BLE001
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

        # Write-through to MinIO. Blocks (~17 min retry) if MinIO transient
        # outage; raises RuntimeError beyond that.
        try:
            upload_through("enrichment-raws", storage_key, cache_dest.read_bytes())
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s] minio upload FAILED source_ref=%s key=%s: %s",
                adapter.source_id, source_ref, storage_key, exc,
            )
            conn.execute(
                """
                UPDATE source_images
                   SET download_status = 'failed',
                       download_error  = ?
                 WHERE id = ?
                """,
                (f"minio upload: {str(exc)[:400]}", sid),
            )
            n_errors += 1
            run.bump(n_errors=1)
            continue

        conn.execute(
            """
            UPDATE source_images
               SET storage_path         = ?,
                   storage_status       = 'present',
                   bytes                = ?,
                   sha256               = ?,
                   width                = COALESCE(?, width),
                   height               = COALESCE(?, height),
                   download_endpoint    = ?,
                   download_status      = 'success',
                   download_http_status = ?,
                   download_error       = NULL
             WHERE id = ?
            """,
            (
                storage_key, res.bytes, res.sha256, res.width, res.height,
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
