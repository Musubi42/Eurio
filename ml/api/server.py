"""Eurio ML API — FastAPI server for training pipeline management.

Runs locally on the developer's Mac. Connects to Supabase for coin data
and embedding storage. The admin Vue frontend talks to this API for
training operations.

Usage:
    cd ml && uvicorn api.server:app --port 8042 --reload
    # or via go-task:
    go-task ml:api
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .supabase_client import SupabaseClient, load_env
from .training_runner import TrainingRunner

ML_DIR = Path(__file__).parent.parent
CHECKPOINTS_DIR = ML_DIR / "checkpoints"
OUTPUT_DIR = ML_DIR / "output"
DATASETS_DIR = ML_DIR / "datasets"

# ─── App ───

app = FastAPI(
    title="Eurio ML API",
    version="0.2.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Shared state ───

_env: dict[str, str] = {}
_supabase: SupabaseClient | None = None
_runner = TrainingRunner()


def get_supabase() -> SupabaseClient:
    global _supabase, _env
    if _supabase is None:
        _env = load_env()
        url = _env.get("SUPABASE_URL", "")
        key = _env.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise HTTPException(
                status_code=503,
                detail="SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY non configurés",
            )
        _supabase = SupabaseClient(url, key)
    return _supabase


# ─── Models ───


class HealthResponse(BaseModel):
    status: str
    model_version: str | None = None
    last_trained_at: str | None = None
    supabase_connected: bool = False
    designs_count: int = 0
    trained_count: int = 0
    queue_length: int = 0
    active_count: int = 0


class TrainRequest(BaseModel):
    design_ids: list[int]
    epochs: int = 40
    batch_size: int = 64
    m_per_class: int = 4
    target_augmented: int = 50


class TrainConfig(BaseModel):
    max_concurrent: int = 1
    device: str = "mps"


class AugmentRequest(BaseModel):
    design_ids: list[int]
    target_per_class: int = 50


# ─── Health ───


@app.get("/health", response_model=HealthResponse)
def health():
    """Health check — the admin frontend polls this to know if API is up."""
    resp = HealthResponse(status="ok")

    # Current model info
    meta_path = OUTPUT_DIR / "model_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        resp.model_version = f"v1-{meta.get('mode', '?')}"

    log_path = CHECKPOINTS_DIR / "training_log.json"
    if log_path.exists():
        resp.last_trained_at = datetime.fromtimestamp(
            log_path.stat().st_mtime
        ).isoformat()

    # Supabase connectivity
    try:
        sb = get_supabase()
        resp.supabase_connected = True
        resp.designs_count = sb.count(
            "coins",
            params={"cross_refs->numista_id": "not.is.null"},
        )
        resp.trained_count = sb.count("coin_embeddings")
    except Exception:
        resp.supabase_connected = False

    # Queue info
    resp.queue_length = len(_runner.queue)
    resp.active_count = len(_runner.active)

    return resp


# ─── Designs ───


@app.get("/designs")
def list_designs() -> list[dict]:
    """List all designs (grouped by numista_id) with training status."""
    sb = get_supabase()

    coins = sb.query(
        "coins",
        select="eurio_id,country,face_value,theme,images,cross_refs",
        params={"cross_refs->numista_id": "not.is.null"},
    )

    embeddings = sb.query("coin_embeddings", select="eurio_id,model_version")
    trained_ids = {e["eurio_id"] for e in embeddings}

    design_map: dict[int, dict] = {}

    for coin in coins:
        nid = coin.get("cross_refs", {}).get("numista_id")
        if not nid:
            continue

        if nid not in design_map:
            image_url = _extract_image_url(coin)
            coin_dir = DATASETS_DIR / str(nid)
            has_sources = (
                coin_dir.exists()
                and any(
                    f.suffix.lower() in (".jpg", ".jpeg", ".png")
                    for f in coin_dir.iterdir()
                    if f.is_file()
                )
            ) if coin_dir.exists() else False

            aug_dir = coin_dir / "augmented" if coin_dir.exists() else None
            aug_count = (
                len(list(aug_dir.glob("aug_*.jpg")))
                if aug_dir and aug_dir.exists()
                else 0
            )

            design_map[nid] = {
                "numista_id": nid,
                "name": coin.get("theme") or f"Design {nid}",
                "country": coin["country"],
                "face_values": [coin["face_value"]],
                "image_url": image_url,
                "eurio_ids": [coin["eurio_id"]],
                "trained": coin["eurio_id"] in trained_ids,
                "model_version": None,
                "has_source_images": has_sources,
                "augmented_count": aug_count,
            }
        else:
            d = design_map[nid]
            d["eurio_ids"].append(coin["eurio_id"])
            if coin["face_value"] not in d["face_values"]:
                d["face_values"].append(coin["face_value"])
            if not d["image_url"]:
                d["image_url"] = _extract_image_url(coin)
            if coin["eurio_id"] in trained_ids:
                d["trained"] = True

    for emb in embeddings:
        for d in design_map.values():
            if emb["eurio_id"] in d["eurio_ids"]:
                d["model_version"] = emb["model_version"]

    return sorted(design_map.values(), key=lambda d: (d["country"], d["numista_id"]))


@app.get("/designs/{numista_id}")
def get_design(numista_id: int) -> dict:
    """Get detailed info for a single design."""
    sb = get_supabase()

    coins = sb.query(
        "coins",
        select="eurio_id,country,year,face_value,theme,images,cross_refs,series_id",
        params={"cross_refs->numista_id": f"eq.{numista_id}"},
    )

    if not coins:
        raise HTTPException(status_code=404, detail="Design non trouvé")

    embeddings = sb.query(
        "coin_embeddings",
        select="eurio_id,model_version,created_at",
    )
    trained_map = {e["eurio_id"]: e for e in embeddings}

    first = coins[0]
    image_url = _extract_image_url(first)

    coin_dir = DATASETS_DIR / str(numista_id)
    source_images = []
    if coin_dir.exists():
        source_images = [
            f.name
            for f in sorted(coin_dir.iterdir())
            if f.suffix.lower() in (".jpg", ".jpeg", ".png") and f.is_file()
        ]

    aug_dir = coin_dir / "augmented" if coin_dir.exists() else None
    aug_count = (
        len(list(aug_dir.glob("aug_*.jpg")))
        if aug_dir and aug_dir.exists()
        else 0
    )

    eurio_ids = [c["eurio_id"] for c in coins]
    is_trained = any(eid in trained_map for eid in eurio_ids)

    training_info = None
    if is_trained:
        for eid in eurio_ids:
            if eid in trained_map:
                training_info = trained_map[eid]
                break

    training_history = []
    log_path = CHECKPOINTS_DIR / "training_log.json"
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text())
            if logs:
                last = logs[-1]
                training_history.append({
                    "model_version": training_info["model_version"] if training_info else "v1",
                    "trained_at": training_info["created_at"] if training_info else None,
                    "final_epoch": last.get("epoch"),
                    "recall_at_1": last.get("recall@1"),
                    "recall_at_3": last.get("recall@3"),
                    "loss": last.get("train_loss"),
                })
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "numista_id": numista_id,
        "name": first.get("theme") or f"Design {numista_id}",
        "country": first["country"],
        "face_values": sorted(set(c["face_value"] for c in coins)),
        "image_url": image_url,
        "coins": [
            {
                "eurio_id": c["eurio_id"],
                "year": c["year"],
                "face_value": c["face_value"],
                "trained": c["eurio_id"] in trained_map,
            }
            for c in sorted(coins, key=lambda c: c["year"])
        ],
        "trained": is_trained,
        "model_version": training_info["model_version"] if training_info else None,
        "last_trained_at": training_info["created_at"] if training_info else None,
        "source_images": source_images,
        "augmented_count": aug_count,
        "training_history": training_history,
    }


# ─── Images ───


@app.get("/images/{numista_id}/source")
def get_source_image(numista_id: int):
    """Serve the source obverse image for a design."""
    coin_dir = DATASETS_DIR / str(numista_id)
    if not coin_dir.exists():
        raise HTTPException(status_code=404, detail="Image source non trouvée")
    # Prefer obverse.jpg, then first available image
    for name in ("obverse.jpg", "obverse.png", "obverse.jpeg"):
        path = coin_dir / name
        if path.exists():
            return FileResponse(path, media_type="image/jpeg")
    # Fallback to first image file (not augmented)
    for f in sorted(coin_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png") and not f.stem.startswith("aug_"):
            return FileResponse(f, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Image source non trouvée")


@app.get("/images/{numista_id}/augmented")
def list_augmented_images(numista_id: int) -> dict:
    """List augmented images available for a design."""
    aug_dir = DATASETS_DIR / str(numista_id) / "augmented"
    if not aug_dir.exists():
        return {"images": [], "count": 0}

    files = sorted(aug_dir.glob("aug_*.jpg"))
    images = [
        {
            "filename": f.name,
            "url": f"/images/{numista_id}/augmented/{f.name}",
        }
        for f in files
    ]
    return {"images": images, "count": len(images)}


@app.get("/images/{numista_id}/augmented/{filename}")
def get_augmented_image(numista_id: int, filename: str):
    """Serve an augmented image file."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")

    path = DATASETS_DIR / str(numista_id) / "augmented" / filename
    resolved = path.resolve()
    expected_parent = (DATASETS_DIR / str(numista_id) / "augmented").resolve()
    if not str(resolved).startswith(str(expected_parent)):
        raise HTTPException(status_code=400, detail="Chemin invalide")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Image non trouvée")

    return FileResponse(resolved, media_type="image/jpeg")


# ─── Training ───


@app.post("/train")
def start_training(req: TrainRequest) -> dict:
    """Enqueue designs for training. Creates one job per design_id."""
    # Resolve design names from Supabase
    names: dict[int, str] = {}
    countries: dict[int, str] = {}
    try:
        sb = get_supabase()
        coins = sb.query(
            "coins",
            select="theme,country,cross_refs",
            params={"cross_refs->numista_id": "not.is.null"},
        )
        for coin in coins:
            nid = coin.get("cross_refs", {}).get("numista_id")
            if nid and nid in req.design_ids:
                if nid not in names:
                    names[nid] = coin.get("theme") or f"Design {nid}"
                    countries[nid] = coin.get("country", "")
    except Exception:
        pass

    runs = _runner.enqueue(
        design_ids=req.design_ids,
        design_names=names,
        design_countries=countries,
        epochs=req.epochs,
        batch_size=req.batch_size,
        m_per_class=req.m_per_class,
        target_augmented=req.target_augmented,
    )
    return {"queued": [r.to_dict() for r in runs]}


@app.get("/train/status")
def training_status() -> dict:
    """Get full training state: active runs, queue, and history."""
    return {
        "active": [r.to_dict() for r in _runner.active],
        "queue": [r.to_dict() for r in _runner.queue],
        "history": [r.to_dict() for r in _runner.history],
    }


@app.get("/train/config")
def get_config() -> dict:
    """Get training configuration."""
    return {
        "max_concurrent": _runner.max_concurrent,
        "device": _runner.device,
    }


@app.post("/train/config")
def update_config(config: TrainConfig) -> dict:
    """Update training configuration."""
    _runner.max_concurrent = config.max_concurrent
    _runner.device = config.device
    return {
        "max_concurrent": _runner.max_concurrent,
        "device": _runner.device,
    }


@app.get("/train/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """Get a specific training run."""
    run = _runner.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run non trouvé")
    return run.to_dict()


@app.get("/train/runs/{run_id}/logs")
def get_run_logs(run_id: str, tail: int = 50) -> dict:
    """Get the last N log lines from a training run."""
    run = _runner.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run non trouvé")
    return {
        "run_id": run_id,
        "status": run.status.value,
        "lines": run.log_lines[-tail:],
    }


@app.delete("/train/queue/{run_id}")
def remove_from_queue(run_id: str) -> dict:
    """Remove a job from the queue."""
    success = _runner.remove_from_queue(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job non trouvé dans la queue")
    return {"removed": run_id}


# ─── Augment ───


@app.post("/augment")
def augment_designs(req: AugmentRequest) -> dict:
    """Generate augmented images for specified designs (synchronous)."""
    import sys

    sys.path.insert(0, str(ML_DIR))
    from augment_synthetic import augment_coin

    results: dict[int, int] = {}
    for nid in req.design_ids:
        coin_dir = DATASETS_DIR / str(nid)
        if not coin_dir.exists():
            results[nid] = 0
            continue
        count = augment_coin(coin_dir, target_count=req.target_per_class)
        results[nid] = count

    return {
        "augmented": results,
        "total_generated": sum(results.values()),
    }


# ─── Helpers ───


def _extract_image_url(coin: dict) -> str | None:
    """Extract obverse image URL from coin images field."""
    imgs = coin.get("images")
    if not imgs:
        return None
    if isinstance(imgs, dict):
        return imgs.get("obverse")
    if isinstance(imgs, list) and imgs:
        obv = next((i for i in imgs if i.get("role") == "obverse"), None)
        return obv["url"] if obv else imgs[0].get("url")
    return None
