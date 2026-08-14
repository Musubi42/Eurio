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

from . import Bucket, _client


def _cache_root() -> Path:
    return Path(os.environ.get(
        "EURIO_CACHE_ROOT",
        Path.home() / ".cache" / "eurio",
    ))


def _max_gb() -> float:
    return float(os.environ.get("EURIO_CACHE_MAX_GB", "0"))


# ─── Deux casiers sous une seule racine ──────────────────────────────────────
#
# `EURIO_CACHE_ROOT` reste LA variable à déplacer (serveur de calcul, conteneur,
# Windows…) : tout vit dessous. Mais images et artefacts de build n'ont ni la
# même taille, ni la même valeur, ni la même conséquence en cas de suppression :
#
#   <root>/<bucket>/…     images — re-téléchargeables, volumineuses, plafond
#                         EURIO_CACHE_MAX_GB
#   <root>/artifacts/…    modèles épinglés par un manifeste — petits, requis
#                         par le build, plafond EURIO_ARTIFACTS_MAX_GB
#
# L'éviction des images NE DOIT PAS toucher `artifacts/` : un modèle évincé
# casse un build hors ligne, et l'échec ressemble à un bug plutôt qu'à un cache
# vide. D'où le cloisonnement explicite ci-dessous.

_ARTIFACTS_DIRNAME = "artifacts"


def _artifacts_root() -> Path:
    return _cache_root() / _ARTIFACTS_DIRNAME


def _artifacts_max_gb() -> float:
    return float(os.environ.get("EURIO_ARTIFACTS_MAX_GB", "5"))


# Backoff schedule for transient download failures (in seconds, AFTER the
# first attempt). MinIO behind the VPS proxy returns sporadic 403s under
# bursts of distinct-key reads — empirically ~100% recover on an immediate
# retry. Short delays: total worst-case ~7.7s per object, rarely hit.
_DOWNLOAD_RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0, 4.0)


def local_path(bucket: Bucket, storage_key: str) -> Path:
    """Return a local filesystem path for `<bucket>/<storage_key>`.

    Downloads from MinIO on first call, touches atime on subsequent calls.
    Raises FileNotFoundError if the object is missing or MinIO is down.

    Transient download failures (network errors, 5xx, and the sporadic 403
    MinIO emits under read bursts) are retried with bounded backoff
    (`_DOWNLOAD_RETRY_DELAYS`). A genuine "key not found" is NOT transient and
    is surfaced immediately.

    Cascade: when MinIO confirms the object no longer exists (404), every
    DB row pointing at this key is marked `storage_status='missing_in_storage'`
    via `cascade.mark_missing_in_storage()`. Transient errors do NOT trigger
    the mark — only an explicit "key not found" response does.
    """
    target = _cache_root() / bucket / storage_key
    if target.exists():
        # Touch atime for LRU eviction; keep mtime byte-identical (use the
        # nanosecond-precision API so we don't lose precision via float).
        st = target.stat()
        os.utime(target, ns=(time.time_ns(), st.st_mtime_ns))
        return target

    if _max_gb() > 0:
        _evict_if_needed()

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    last_exc: BaseException | None = None
    for delay in (0.0, *_DOWNLOAD_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _client().download_file(bucket, storage_key, str(tmp))
            os.replace(tmp, target)
            return target
        except Exception as e:  # noqa: BLE001
            # Wipe the half-written tmp; surface as FileNotFoundError so callers
            # don't have to catch boto-specific exceptions.
            tmp.unlink(missing_ok=True)
            if _is_not_found(e):
                # MinIO confirms the object is gone — not transient, propagate
                # to DB + cache and bail out without retrying.
                from . import cascade  # lazy import (avoids circular)
                cascade.mark_missing_in_storage(bucket, storage_key)
                raise FileNotFoundError(
                    f"Cannot fetch {bucket}/{storage_key}: {e}"
                ) from e
            last_exc = e
    raise FileNotFoundError(
        f"Cannot fetch {bucket}/{storage_key} after "
        f"{len(_DOWNLOAD_RETRY_DELAYS) + 1} attempts: {last_exc}"
    ) from last_exc


def _is_not_found(exc: BaseException) -> bool:
    """True iff the exception is a MinIO/S3 "key not found" response.

    Network errors, transient 5xx, auth failures, etc. all return False —
    they are not signals to mark the row as missing.
    """
    # botocore.exceptions.ClientError carries the error code in .response.
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey", "NotFound"):
            return True
    # boto3.s3.transfer wraps download errors; the .__cause__ holds the
    # underlying ClientError. Recurse one level.
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return _is_not_found(cause)
    return False


def cache_path_for(bucket: Bucket, storage_key: str) -> Path:
    """Local cache path for a (bucket, key) — does NOT download.

    Useful when you're about to write through (upload_through) and want
    to know where the file will live locally first.
    """
    return _cache_root() / bucket / storage_key


def upload_through(
    bucket: Bucket,
    storage_key: str,
    data: bytes,
    *,
    block_on_disconnect: bool = True,
    max_attempts: int = 8,
) -> Path:
    """Write bytes to local cache AND upload to MinIO.

    After return : the bytes are guaranteed present in BOTH places (cache +
    MinIO). Downstream callers can use `local_path(bucket, storage_key)`
    immediately and get a cache hit (no re-download from MinIO).

    On MinIO failure with `block_on_disconnect=True` (default), retries
    with exponential backoff up to ~17 min total. On exhaustion, raises
    RuntimeError. With `block_on_disconnect=False`, raises immediately.

    The cache write is atomic (.tmp + os.replace). If the MinIO upload
    fails, the cache file is left in place — re-running the same call is
    idempotent (skips the redundant cache write, retries the upload).
    """
    import time
    target = cache_path_for(bucket, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    # Exponential backoff schedule. Total ~17 min — enough to ride out a
    # VPS reboot but not infinite.
    delays = [2, 5, 15, 30, 60, 120, 300, 600]
    attempts = min(max_attempts, len(delays))
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            _client().put_object(Bucket=bucket, Key=storage_key, Body=data)
            return target
        except ImportError as e:
            # boto3/botocore manquant dans l'env — pas une panne MinIO, pas
            # de retry utile. Fail-fast pour qu'on installe la dépendance.
            raise RuntimeError(
                f"MinIO upload unavailable: {e}. Install boto3 in the "
                f"current Python environment (Nix devShell or pip install)."
            ) from e
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if not block_on_disconnect or i == attempts - 1:
                break
            delay = delays[i]
            import logging
            logging.getLogger(__name__).warning(
                "MinIO put_object retry %d/%d in %ds for %s/%s: %s",
                i + 1, attempts, delay, bucket, storage_key, e,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"MinIO upload failed after {attempts} attempts for "
        f"{bucket}/{storage_key}: {last_exc}"
    ) from last_exc


def _lru_evict(root: Path, max_gb: float) -> int:
    """LRU eviction under `root`: remove oldest-atime files until under max_gb.

    Returns the number of files removed. A max_gb of 0 disables eviction.
    """
    if max_gb <= 0 or not root.exists():
        return 0
    files: list[tuple[float, Path, int]] = []
    for f in root.rglob("*"):
        if f.is_file() and not f.name.endswith(".tmp"):
            st = f.stat()
            files.append((st.st_atime, f, st.st_size))
    files.sort(key=lambda t: t[0])  # oldest first
    total = sum(s for _, _, s in files)
    max_bytes = int(max_gb * 1024**3)
    removed = 0
    while total > max_bytes and files:
        _, victim, sz = files.pop(0)
        try:
            victim.unlink()
            total -= sz
            removed += 1
        except FileNotFoundError:
            pass
    return removed


def _evict_if_needed() -> None:
    """LRU eviction des IMAGES, plafond EURIO_CACHE_MAX_GB.

    Ne touche jamais `<root>/artifacts/` : les modèles ont leur propre plafond
    (`_evict_artifacts_if_needed`). Un modèle évincé casserait un build.
    """
    root = _cache_root()
    if not root.exists():
        return
    max_bytes = int(_max_gb() * 1024**3)
    if max_bytes <= 0:
        return
    artifacts = _artifacts_root()
    files: list[tuple[float, Path, int]] = []
    for f in root.rglob("*"):
        if not f.is_file() or f.name.endswith(".tmp"):
            continue
        if artifacts in f.parents:
            continue  # casier artefacts — plafond séparé
        st = f.stat()
        files.append((st.st_atime, f, st.st_size))
    files.sort(key=lambda t: t[0])  # oldest first
    total = sum(s for _, _, s in files)
    while total > max_bytes and files:
        _, victim, sz = files.pop(0)
        try:
            victim.unlink()
            total -= sz
        except FileNotFoundError:
            pass


def _evict_artifacts_if_needed() -> None:
    """LRU eviction des ARTEFACTS, plafond EURIO_ARTIFACTS_MAX_GB (défaut 5)."""
    _lru_evict(_artifacts_root(), _artifacts_max_gb())


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


# ─── Artefacts de build ──────────────────────────────────────────────────────

ARTIFACTS_BUCKET: Bucket = "model-artifacts"


def sha256_of(path: Path) -> str:
    """sha256 hexdigest d'un fichier, lu par blocs (les modèles font ~10 Mo)."""
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_path(storage_key: str, *, sha256: str) -> Path:
    """Chemin local d'un artefact de build, téléchargé si besoin et VÉRIFIÉ.

    Contrairement à `local_path()`, le contenu est validé contre le `sha256`
    attendu (celui du manifeste `shared/model-assets.json`) :

    - fichier présent et sha conforme  → retour immédiat, atime touché ;
    - fichier présent mais sha faux    → supprimé et re-téléchargé (cache
      corrompu, ou clé réécrite en amont — ce qui ne devrait pas arriver
      puisque la version est portée par la clé) ;
    - après téléchargement, sha faux   → ValueError. On ne place JAMAIS un
      artefact non conforme dans les assets : un modèle silencieusement faux
      est pire qu'un build cassé.

    Vit sous `<EURIO_CACHE_ROOT>/artifacts/`, plafond séparé
    `EURIO_ARTIFACTS_MAX_GB` — l'éviction des images ne peut pas l'emporter.
    """
    target = _artifacts_root() / storage_key
    if target.exists():
        if sha256_of(target) == sha256:
            st = target.stat()
            os.utime(target, ns=(time.time_ns(), st.st_mtime_ns))
            return target
        target.unlink()  # cache corrompu — on retélécharge

    _evict_artifacts_if_needed()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    last_exc: BaseException | None = None
    for delay in (0.0, *_DOWNLOAD_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _client().download_file(ARTIFACTS_BUCKET, storage_key, str(tmp))
            got = sha256_of(tmp)
            if got != sha256:
                tmp.unlink(missing_ok=True)
                raise ValueError(
                    f"sha256 mismatch pour {ARTIFACTS_BUCKET}/{storage_key} : "
                    f"attendu {sha256}, obtenu {got}. "
                    f"Le manifeste et le bucket sont désynchronisés."
                )
            os.replace(tmp, target)
            return target
        except ValueError:
            raise  # mismatch : ne pas retenter, c'est déterministe
        except Exception as e:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            if _is_not_found(e):
                raise FileNotFoundError(
                    f"Artefact absent du bucket : {ARTIFACTS_BUCKET}/{storage_key}. "
                    f"Publie-le avec `go-task ml:assets:publish`."
                ) from e
            last_exc = e
    raise FileNotFoundError(
        f"Cannot fetch {ARTIFACTS_BUCKET}/{storage_key} after "
        f"{len(_DOWNLOAD_RETRY_DELAYS) + 1} attempts: {last_exc}"
    ) from last_exc


def artifacts_stats() -> dict:
    """Stats du casier artefacts (plafond distinct des images)."""
    root = _artifacts_root()
    n, sz = 0, 0
    if root.exists():
        for f in root.rglob("*"):
            if f.is_file():
                n += 1
                sz += f.stat().st_size
    return {"root": str(root), "n_files": n, "size_bytes": sz,
            "max_gb": _artifacts_max_gb()}
