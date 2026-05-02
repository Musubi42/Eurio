"""Canonical on-disk paths for source ingestion artifacts.

Layout under `ml/state/sources/<source>/`:

    raw/<sharded>/<source_ref>.<ext>           # one per source_image
    crops/<sharded>/<source_ref>__c<idx>.png   # one per image_asset

Sharding: first 2 hex chars of sha1(source_ref) — keeps directory
fan-out manageable (256 buckets) without forcing the source to know
about it. Atomic writes via `.tmp` + `os.replace`.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

_STORAGE_ROOT = Path(__file__).resolve().parents[2] / "state" / "sources"


def _shard(source_ref: str) -> str:
    return hashlib.sha1(source_ref.encode("utf-8")).hexdigest()[:2]


def _safe_ref(source_ref: str) -> str:
    """Strip path separators so a malicious source_ref can't escape."""
    return source_ref.replace("/", "_").replace("\\", "_").replace("..", "_")


def storage_root() -> Path:
    return _STORAGE_ROOT


def raw_path(source: str, source_ref: str, ext: str = "jpg") -> Path:
    return _STORAGE_ROOT / source / "raw" / _shard(source_ref) / f"{_safe_ref(source_ref)}.{ext}"


def crop_path(source: str, source_ref: str, crop_index: int = 0) -> Path:
    return (
        _STORAGE_ROOT / source / "crops" / _shard(source_ref)
        / f"{_safe_ref(source_ref)}__c{crop_index}.png"
    )


def write_atomic(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
