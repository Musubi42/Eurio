"""Tests for ml.storage.cascade and the 404 hook in local_cache.

Spec: docs/harmonisation-images/chunk-9-cascade-sync.md.

We isolate from a real MinIO and a real training.db. The DB is a tmp
SQLite with the minimal schema needed (image_assets, source_images +
storage_status column).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 404-hook tests construct a botocore ClientError directly. Skip the whole
# module on environments without botocore (e.g. the bare venv without the
# Nix devShell) rather than fail every test in the file at collection time.
pytest.importorskip("botocore")

import storage
from storage import cascade


# ─── tmp DB fixture ─────────────────────────────────────────────────────────


_MIN_SCHEMA = """
CREATE TABLE source_images (
  id            TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  storage_path  TEXT,
  storage_status TEXT NOT NULL DEFAULT 'present'
    CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'))
);

CREATE TABLE image_assets (
  id              TEXT PRIMARY KEY,
  source_image_id TEXT NOT NULL,
  storage_path    TEXT NOT NULL,
  storage_status  TEXT NOT NULL DEFAULT 'present'
    CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'))
);
"""


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "training.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_MIN_SCHEMA)
    conn.executemany(
        "INSERT INTO source_images (id, source, storage_path) VALUES (?, ?, ?)",
        [
            ("si-1", "ebay", "ebay/run-x/si-1.jpg"),
            ("si-2", "numista", "numista/68395/raw.jpg"),
        ],
    )
    conn.executemany(
        "INSERT INTO image_assets (id, source_image_id, storage_path) VALUES (?, ?, ?)",
        [
            ("a-1", "si-1", "ebay/run-x/a-1.png"),
            ("a-2", "si-1", "ebay/run-x/a-2.png"),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("EURIO_TRAINING_DB", str(db))
    yield db


# ─── mark_missing_in_storage ────────────────────────────────────────────────


def test_mark_missing_updates_matching_row(tmp_db):
    n = cascade.mark_missing_in_storage("enrichment-crops", "ebay/run-x/a-1.png")
    assert n == 1

    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT storage_status FROM image_assets WHERE id = 'a-1'"
    ).fetchone()
    assert row[0] == "missing_in_storage"


def test_mark_missing_is_idempotent(tmp_db):
    cascade.mark_missing_in_storage("enrichment-crops", "ebay/run-x/a-1.png")
    n = cascade.mark_missing_in_storage("enrichment-crops", "ebay/run-x/a-1.png")
    # Second call updates 0 rows because the WHERE clause filters on
    # storage_status='present'.
    assert n == 0


def test_mark_missing_no_matching_row_returns_zero(tmp_db):
    assert cascade.mark_missing_in_storage("enrichment-crops", "does/not/exist.png") == 0


def test_mark_missing_swallows_db_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("EURIO_TRAINING_DB", str(tmp_path / "absent.db"))
    # No DB file → should return 0 and not raise.
    assert cascade.mark_missing_in_storage("enrichment-crops", "anything") == 0


# ─── delete_asset_cascade ───────────────────────────────────────────────────


def test_delete_asset_cascade_marks_row_and_deletes_minio(tmp_db, monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(storage, "_s3_client", fake_client)

    cascade.delete_asset_cascade(
        "enrichment-crops",
        "ebay/run-x/a-2.png",
        table="image_assets",
        row_id="a-2",
    )

    fake_client.delete_object.assert_called_once_with(
        Bucket="enrichment-crops", Key="ebay/run-x/a-2.png"
    )

    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT storage_status FROM image_assets WHERE id = 'a-2'"
    ).fetchone()
    assert row[0] == "removed_via_admin"


def test_delete_asset_cascade_continues_when_minio_fails(tmp_db, monkeypatch):
    fake_client = MagicMock()
    fake_client.delete_object.side_effect = RuntimeError("network down")
    monkeypatch.setattr(storage, "_s3_client", fake_client)

    # Should NOT raise — the row marking proceeds anyway.
    cascade.delete_asset_cascade(
        "enrichment-crops",
        "ebay/run-x/a-1.png",
        table="image_assets",
        row_id="a-1",
    )

    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT storage_status FROM image_assets WHERE id = 'a-1'"
    ).fetchone()
    assert row[0] == "removed_via_admin"


def test_delete_asset_cascade_rejects_invalid_reason(tmp_db, monkeypatch):
    monkeypatch.setattr(storage, "_s3_client", MagicMock())
    with pytest.raises(ValueError, match="reason must be"):
        cascade.delete_asset_cascade(
            "enrichment-crops", "k", table="image_assets",
            row_id="a-1", reason="garbage",
        )


def test_delete_asset_cascade_rejects_invalid_table(tmp_db, monkeypatch):
    monkeypatch.setattr(storage, "_s3_client", MagicMock())
    with pytest.raises(ValueError, match="table must be"):
        cascade.delete_asset_cascade(
            "enrichment-crops", "k", table="totally_wrong",
            row_id="a-1",
        )


def test_delete_asset_cascade_purges_cache_copy(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EURIO_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setattr(storage, "_s3_client", MagicMock())

    cached = tmp_path / "cache" / "enrichment-crops" / "ebay" / "run-x" / "a-1.png"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"stale")

    cascade.delete_asset_cascade(
        "enrichment-crops", "ebay/run-x/a-1.png",
        table="image_assets", row_id="a-1",
    )
    assert not cached.exists()


# ─── local_cache 404 hook ───────────────────────────────────────────────────


def test_local_path_404_marks_row_missing(tmp_db, tmp_path, monkeypatch):
    """When MinIO returns 404, the matching DB row is auto-marked."""
    from botocore.exceptions import ClientError

    monkeypatch.setenv("EURIO_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setattr(storage, "_s3_client", None)  # force re-init

    fake = MagicMock()
    fake.download_file.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
        "GetObject",
    )
    monkeypatch.setattr(storage, "_s3_client", fake)

    from storage import local_cache

    with pytest.raises(FileNotFoundError):
        local_cache.local_path("enrichment-crops", "ebay/run-x/a-1.png")

    # The row should be marked.
    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT storage_status FROM image_assets WHERE id = 'a-1'"
    ).fetchone()
    assert row[0] == "missing_in_storage"


def test_local_path_transient_error_does_not_mark(tmp_db, tmp_path, monkeypatch):
    """A network glitch (not a 404) must not flip the row to missing."""
    monkeypatch.setenv("EURIO_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setattr(storage, "_s3_client", None)

    fake = MagicMock()
    fake.download_file.side_effect = RuntimeError("connection reset")
    monkeypatch.setattr(storage, "_s3_client", fake)

    from storage import local_cache

    with pytest.raises(FileNotFoundError):
        local_cache.local_path("enrichment-crops", "ebay/run-x/a-1.png")

    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute(
        "SELECT storage_status FROM image_assets WHERE id = 'a-1'"
    ).fetchone()
    assert row[0] == "present"  # unchanged
