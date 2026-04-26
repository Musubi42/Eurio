"""FastAPI routes for the real-photo benchmark subsystem (PRD Bloc 3).

Mounted from ``server.py``. Consumes the Store for `benchmark_runs` CRUD and
spawns `evaluate_real_photos.py` as a subprocess for each `POST /run`, so the
heavy PyTorch imports stay outside the API process.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from state import Store

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
REAL_PHOTOS_ROOT = (ML_DIR / "data" / "real_photos").resolve()
REPORTS_DIR = ML_DIR / "reports"
THUMBNAIL_ROOT = ML_DIR / "output" / "benchmark_thumbnails"
THUMBNAIL_TTL_SECONDS = 24 * 3600
THUMBNAIL_SIZE = (256, 256)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])

_store: Store | None = None
_active_runs: dict[str, dict] = {}
_active_lock = threading.Lock()


def bind(store: Store) -> None:
    """Called once by server.py at module import; wires the shared Store."""
    global _store
    _store = store


def _get_store() -> Store:
    if _store is None:
        raise RuntimeError("benchmark_routes.bind() not called")
    return _store


# ─── Payload models ─────────────────────────────────────────────────────────


class RunPayload(BaseModel):
    model_path: str
    eurio_ids: list[str] | None = None
    zones: list[str] | None = None
    recipe_id: str | None = None
    run_id: str | None = None
    top_confusions: int = 20


# ─── Helpers ────────────────────────────────────────────────────────────────


def _sanitize_run_id(run_id: str) -> None:
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="run_id invalide")


def _validate_zones(zones: list[str] | None) -> None:
    if zones is None:
        return
    for z in zones:
        if z not in ("green", "orange", "red"):
            raise HTTPException(status_code=400, detail=f"zone invalide: {z!r}")


def _safe_real_photo_path(relative: str) -> Path:
    """Resolve a path inside REAL_PHOTOS_ROOT — refuses anything that escapes."""
    if relative.startswith("/") or ".." in relative.split("/"):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    target = (REAL_PHOTOS_ROOT / relative).resolve()
    try:
        target.relative_to(REAL_PHOTOS_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Chemin hors hold-out") from None
    return target


def _thumbnail_path(rel_path: str) -> Path:
    digest = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:24]
    return THUMBNAIL_ROOT / f"{digest}.jpg"


def _ensure_thumbnail(rel_path: str) -> Path:
    src = _safe_real_photo_path(rel_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Photo introuvable")
    dst = _thumbnail_path(rel_path)
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    THUMBNAIL_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
            im.save(dst, "JPEG", quality=80)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Thumbnail error: {exc}") from exc
    return dst


def _load_manifest() -> dict | None:
    path = REAL_PHOTOS_ROOT / "_manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def cleanup_expired_thumbnails() -> int:
    """Evict thumbnails older than TTL. Called at server startup."""
    if not THUMBNAIL_ROOT.exists():
        return 0
    cutoff = time.time() - THUMBNAIL_TTL_SECONDS
    removed = 0
    for entry in THUMBNAIL_ROOT.iterdir():
        if entry.is_file() and entry.stat().st_mtime < cutoff:
            try:
                entry.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def _row_to_summary(row) -> dict:
    d = row.to_dict()
    d.pop("confusion", None)
    d.pop("top_confusions", None)
    d.pop("per_coin", None)
    d["num_zones"] = len(row.zones)
    return d


# ─── Run command runner ────────────────────────────────────────────────────


def _launch_run(payload: RunPayload, run_id: str) -> None:
    """Spawn evaluate_real_photos.py as a subprocess, capture stdout/stderr,
    and surface any non-zero exit as a `failed` status on the SQLite row.
    """
    cmd: list[str] = [
        VENV_PYTHON,
        str(ML_DIR / "evaluate_real_photos.py"),
        "--model",
        payload.model_path,
        "--run-id",
        run_id,
        "--top-confusions",
        str(payload.top_confusions),
    ]
    if payload.eurio_ids:
        cmd.extend(["--eurio-ids", ",".join(payload.eurio_ids)])
    if payload.zones:
        cmd.extend(["--zones", ",".join(payload.zones)])
    if payload.recipe_id:
        cmd.extend(["--recipe-id", payload.recipe_id])

    store = _get_store()

    def _run() -> None:
        with _active_lock:
            _active_runs[run_id] = {"started_at": time.time()}
        try:
            result = subprocess.run(
                cmd,
                cwd=str(ML_DIR),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # The script may or may not have created the row; ensure it
                # is marked as failed regardless.
                error = (result.stderr.strip() or result.stdout.strip()
                         or f"exit {result.returncode}")
                existing = store.get_benchmark_run(run_id)
                if existing is None:
                    # The script died before inserting — ignore, nothing to
                    # update.
                    logger.error("Benchmark %s failed before SQLite insert: %s", run_id, error)
                else:
                    store.update_benchmark_run(
                        run_id,
                        status="failed",
                        error=error,
                        finished_at=_iso_now(),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Benchmark runner crashed for %s", run_id)
            existing = store.get_benchmark_run(run_id)
            if existing is not None:
                store.update_benchmark_run(
                    run_id,
                    status="failed",
                    error=str(exc),
                    finished_at=_iso_now(),
                )
        finally:
            with _active_lock:
                _active_runs.pop(run_id, None)

    threading.Thread(target=_run, daemon=True).start()


def _iso_now() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


# ─── Routes ─────────────────────────────────────────────────────────────────


@router.get("/library")
def library_summary() -> dict:
    """Aggregate view of ml/data/real_photos/ via `_manifest.json`."""
    manifest = _load_manifest()
    if not manifest:
        return {
            "available": False,
            "num_coins": 0,
            "num_photos": 0,
            "by_zone": {"green": 0, "orange": 0, "red": 0, "unknown": 0},
            "coins": [],
        }
    summary = manifest.get("summary", {})
    return {
        "available": True,
        "num_coins": summary.get("num_coins", 0),
        "num_photos": summary.get("num_photos", 0),
        "by_zone": summary.get("by_zone", {}),
        "coins": [
            {
                "eurio_id": c["eurio_id"],
                "zone": c.get("zone"),
                "num_photos": c.get("num_photos", 0),
                "num_sessions": c.get("num_sessions", 0),
                "warnings": c.get("warnings", []),
            }
            for c in manifest.get("coins", [])
        ],
    }


@router.get("/photos/{eurio_id}")
def photos_for_coin(eurio_id: str) -> dict:
    """List photos available for a single coin, with thumbnail URLs."""
    _sanitize_run_id(eurio_id)  # reuse simple validator — no / allowed
    coin_dir = _safe_real_photo_path(eurio_id)
    if not coin_dir.exists() or not coin_dir.is_dir():
        raise HTTPException(status_code=404, detail="Pas de photos pour cette pièce")

    manifest = _load_manifest()
    zone: str | None = None
    if manifest:
        for c in manifest.get("coins", []):
            if c["eurio_id"] == eurio_id:
                zone = c.get("zone")
                break

    out: list[dict] = []
    for entry in sorted(coin_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        rel = f"{eurio_id}/{entry.name}"
        out.append(
            {
                "filename": entry.name,
                "path": rel,
                "size_bytes": entry.stat().st_size,
                "thumbnail_url": f"/benchmark/photos/thumbnail/{rel}",
            }
        )

    return {"eurio_id": eurio_id, "zone": zone, "photos": out}


@router.get("/photos/thumbnail/{path:path}")
def photo_thumbnail(path: str):
    """Serve a cached thumbnail for a real-photo library file."""
    thumb = _ensure_thumbnail(path)
    return FileResponse(thumb, media_type="image/jpeg")


@router.post("/run")
def post_run(payload: RunPayload) -> dict:
    """Kick off a benchmark run in the background.

    Non-blocking: returns the run_id; poll `GET /benchmark/runs/{id}` for
    completion.
    """
    if not payload.model_path:
        raise HTTPException(status_code=400, detail="model_path requis")
    model_abs = Path(payload.model_path)
    if not model_abs.is_absolute():
        model_abs = ML_DIR / payload.model_path
    if not model_abs.exists():
        raise HTTPException(
            status_code=404, detail=f"Modèle introuvable: {payload.model_path}"
        )
    _validate_zones(payload.zones)
    if payload.top_confusions <= 0 or payload.top_confusions > 100:
        raise HTTPException(
            status_code=400, detail="top_confusions doit être entre 1 et 100"
        )

    run_id = payload.run_id or uuid.uuid4().hex[:12]
    _sanitize_run_id(run_id)
    if _get_store().get_benchmark_run(run_id) is not None:
        raise HTTPException(status_code=409, detail="run_id déjà utilisé")

    _launch_run(payload, run_id)
    return {"run_id": run_id, "status": "running"}


@router.get("/runs")
def list_runs(
    model_name: str | None = None,
    recipe_id: str | None = None,
    zone: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    if zone is not None and zone not in ("green", "orange", "red"):
        raise HTTPException(status_code=400, detail=f"zone invalide: {zone!r}")
    if limit <= 0 or limit > 500:
        raise HTTPException(status_code=400, detail="limit doit être entre 1 et 500")
    store = _get_store()
    rows = store.list_benchmark_runs(
        model_name=model_name,
        recipe_id=recipe_id,
        zone=zone,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_row_to_summary(r) for r in rows],
        "total": store.count_benchmark_runs(),
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    _sanitize_run_id(run_id)
    row = _get_store().get_benchmark_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return row.to_dict()


@router.get("/runs/{run_id}/report")
def get_run_report(run_id: str) -> Any:
    _sanitize_run_id(run_id)
    row = _get_store().get_benchmark_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    if not row.report_path:
        raise HTTPException(status_code=404, detail="Rapport non disponible")
    path = Path(row.report_path)
    if not path.is_absolute():
        path = ML_DIR.parent / row.report_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier rapport manquant")
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Rapport corrompu: {exc}") from exc


@router.delete("/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    _sanitize_run_id(run_id)
    deleted = _get_store().delete_benchmark_run(run_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    if deleted.report_path:
        path = Path(deleted.report_path)
        if not path.is_absolute():
            path = ML_DIR.parent / deleted.report_path
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Failed to delete report %s: %s", path, exc)
    return {"deleted": True, "id": run_id}
