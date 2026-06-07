"""Cascade sync helpers — keep MinIO ↔ DB ↔ local cache consistent.

Spec: docs/harmonisation-images/chunk-9-cascade-sync.md.

Two surfaces:

- `mark_missing_in_storage(bucket, storage_key)` — called by
  `local_cache.local_path()` when MinIO returns 404. Updates the DB row
  (storage_status='missing_in_storage'). Best-effort, never throws.

- `delete_asset_cascade(bucket, storage_key, table, row_id, *, reason)`
  — called from the admin path. DELETE from MinIO + purge cache copy +
  UPDATE row (storage_status=reason). Idempotent.

The shared `_db_path()` resolves the SQLite location (defaults to
`ml/state/eurio.db`, override via `EURIO_DB`).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from . import Bucket, _client

_log = logging.getLogger(__name__)

# Tables that carry a `storage_path` + `storage_status` columns.
_TABLES = ("image_assets", "source_images")

# Allowed values for storage_status (mirrors the CHECK constraint).
STATUS_PRESENT = "present"
STATUS_MISSING = "missing_in_storage"
STATUS_REMOVED = "removed_via_admin"


def _db_path() -> Path:
    """Locate the eurio.db. Override via EURIO_DB env var."""
    env = os.environ.get("EURIO_DB")
    if env:
        return Path(env)
    # ml/storage/cascade.py → parents[1] = ml/, then state/eurio.db
    return Path(__file__).resolve().parents[1] / "state" / "eurio.db"


def _connect(timeout: float = 5.0) -> sqlite3.Connection:
    db = _db_path()
    if not db.exists():
        raise FileNotFoundError(f"eurio.db not found at {db}")
    conn = sqlite3.connect(str(db), timeout=timeout)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Reactive: hook called by local_cache on 404 ────────────────────────────


def mark_missing_in_storage(bucket: Bucket, storage_key: str) -> int:
    """Mark every DB row pointing at this S3 key as `missing_in_storage`.

    Best-effort: failures are logged but never raised. The caller's
    FileNotFoundError remains the user-visible signal. The next periodic
    `cascade_sync audit` repairs anything missed.

    Returns the number of rows updated (0 if DB unavailable, 1+ on success).
    """
    try:
        conn = _connect(timeout=2.0)
    except Exception:  # noqa: BLE001
        _log.warning("mark_missing_in_storage: cannot open DB", exc_info=True)
        return 0

    try:
        n = 0
        with conn:
            for table in _TABLES:
                cur = conn.execute(
                    f"""UPDATE {table}
                          SET storage_status = ?
                        WHERE storage_path = ?
                          AND storage_status = ?""",
                    (STATUS_MISSING, storage_key, STATUS_PRESENT),
                )
                n += cur.rowcount
        if n > 0:
            _log.warning(
                "Marked %d row(s) missing_in_storage for %s/%s",
                n, bucket, storage_key,
            )
        return n
    except Exception:  # noqa: BLE001
        _log.warning(
            "mark_missing_in_storage failed for %s/%s",
            bucket, storage_key, exc_info=True,
        )
        return 0
    finally:
        conn.close()


# ─── Admin-driven deletion: cascade from DB intent ──────────────────────────


def delete_asset_cascade(
    bucket: Bucket,
    storage_key: str,
    table: str,
    row_id: str,
    *,
    reason: str = STATUS_REMOVED,
) -> None:
    """DELETE the MinIO object + purge cache + mark the DB row.

    Idempotent end-to-end:
    - MinIO `delete_object` returns 204 even if the key is already absent.
    - `cached.unlink(missing_ok=True)` no-ops when nothing's cached.
    - The UPDATE is keyed on row id, so calling twice just re-stamps.

    `reason` must be one of `STATUS_REMOVED` (admin intent) or
    `STATUS_MISSING` (drift discovered out-of-band). Anything else is
    rejected to keep the CHECK constraint satisfied.
    """
    if reason not in (STATUS_REMOVED, STATUS_MISSING):
        raise ValueError(
            f"reason must be {STATUS_REMOVED!r} or {STATUS_MISSING!r}, got {reason!r}"
        )
    if table not in _TABLES:
        raise ValueError(f"table must be one of {_TABLES}, got {table!r}")

    # 1. MinIO delete (don't block on failure — periodic sync catches orphans).
    try:
        _client().delete_object(Bucket=bucket, Key=storage_key)
    except Exception:  # noqa: BLE001
        _log.warning(
            "MinIO delete failed for %s/%s — DB will be marked anyway",
            bucket, storage_key, exc_info=True,
        )

    # 2. Purge cache copy (lazy import to avoid circular).
    from . import local_cache  # noqa: PLC0415

    cached = local_cache._cache_root() / bucket / storage_key  # noqa: SLF001
    cached.unlink(missing_ok=True)

    # 3. Mark the row.
    conn = _connect()
    try:
        with conn:
            conn.execute(
                f"UPDATE {table} SET storage_status = ? WHERE id = ?",
                (reason, row_id),
            )
    finally:
        conn.close()
