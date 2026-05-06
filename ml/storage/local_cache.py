"""Read-through local cache for MinIO objects.

The application calls `local_path(bucket, storage_key)`. If the object is
in the local cache, returns its filesystem path immediately (touching
atime for LRU). Otherwise downloads from MinIO via boto3, then returns.

Two operating modes:

- **Mac admin** : `EURIO_CACHE_MAX_GB=5` (default 0 = unbounded). When set,
  before each download we evict oldest-by-atime files until under the cap.
- **PC training** : the runner overrides `EURIO_CACHE_ROOT` per `run_id`
  and leaves `MAX_GB=0`. The runner sweeps the dir at the end of the run.

No fallback to a legacy filesystem. If MinIO is unreachable or the key is
missing, raises FileNotFoundError. By design (vision §"Pas de fallback").
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from storage import Bucket, _client


def _cache_root() -> Path:
    return Path(os.environ.get(
        "EURIO_CACHE_ROOT",
        Path.home() / ".cache" / "eurio",
    ))


def _max_gb() -> float:
    return float(os.environ.get("EURIO_CACHE_MAX_GB", "0"))


def local_path(bucket: Bucket, storage_key: str) -> Path:
    """Return a local filesystem path for `<bucket>/<storage_key>`.

    Downloads from MinIO on first call, touches atime on subsequent calls.
    Raises FileNotFoundError if the object is missing or MinIO is down.
    """
    target = _cache_root() / bucket / storage_key
    if target.exists():
        # Touch atime for LRU eviction; keep mtime untouched.
        os.utime(target, (time.time(), target.stat().st_mtime))
        return target

    if _max_gb() > 0:
        _evict_if_needed()

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        _client().download_file(bucket, storage_key, str(tmp))
    except Exception as e:
        # Wipe the half-written tmp; surface as FileNotFoundError so callers
        # don't have to catch boto-specific exceptions.
        tmp.unlink(missing_ok=True)
        raise FileNotFoundError(
            f"Cannot fetch {bucket}/{storage_key}: {e}"
        ) from e
    os.replace(tmp, target)
    return target


def _evict_if_needed() -> None:
    """LRU eviction: remove oldest-atime files until under MAX_GB."""
    root = _cache_root()
    if not root.exists():
        return
    files: list[tuple[float, Path, int]] = []
    for f in root.rglob("*"):
        if f.is_file() and not f.name.endswith(".tmp"):
            st = f.stat()
            files.append((st.st_atime, f, st.st_size))
    files.sort(key=lambda t: t[0])  # oldest first
    total = sum(s for _, _, s in files)
    max_bytes = int(_max_gb() * 1024**3)
    while total > max_bytes and files:
        _, victim, sz = files.pop(0)
        try:
            victim.unlink()
            total -= sz
        except FileNotFoundError:
            pass


def cache_stats() -> dict:
    """Quick stats for the `ml:cache-stats` task."""
    root = _cache_root()
    if not root.exists():
        return {"root": str(root), "n_files": 0, "size_bytes": 0,
                "max_gb": _max_gb()}
    n, sz = 0, 0
    for f in root.rglob("*"):
        if f.is_file():
            n += 1
            sz += f.stat().st_size
    return {"root": str(root), "n_files": n, "size_bytes": sz,
            "max_gb": _max_gb()}


def purge_cache() -> None:
    """Wipe the entire cache root. CLI only — not for runtime use."""
    import shutil
    root = _cache_root()
    if root.exists():
        shutil.rmtree(root)
