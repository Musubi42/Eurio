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
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .supabase_client import SupabaseClient, load_env
from .training_runner import TrainingRunner
from . import augmentation_routes
from . import benchmark_routes
from . import iteration_runner as iteration_runner_module
from . import lab_routes
from review import review_queue_routes
from review import peer_arbitration_routes
from . import sources_routes
from review import coins_review_routes
from . import bench_routes
from . import crop_bench_routes
from . import denom_gold_routes
from . import fragment_audit_routes
from . import crop_recovery_routes
from . import operations_routes
from . import referential_routes
from . import ingest_routes
from . import auth as api_auth

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
CHECKPOINTS_DIR = ML_DIR / "checkpoints"
# Prod model artefacts = the *promoted* state under ml/prod/current/ (phase 4,
# lab-prod-refacto). These endpoints read prod/current, NOT the old floating
# ml/output/ mirror — which has been removed. `prod/current/` is populated by
# `scripts.promote_iteration`; until the first promotion it is absent, so every
# read below guards with `.exists()` and degrades to "no model yet".
PROD_CURRENT = ML_DIR / "prod" / "current"
PROD_TFLITE_DIR = PROD_CURRENT / "tflite"
PROD_EMBEDDINGS_DIR = PROD_CURRENT / "embeddings"
DATASETS_DIR = ML_DIR / "datasets"
STATE_DIR = ML_DIR / "state"
# DB de travail du lab. Défaut local = `state/eurio.db`. Surchargeable via
# `EURIO_DB_PATH` (même variable que `serving.deps`) pour pointer le lab sur la
# réplique fraîche tirée du VPS (`state/eurio.replica.db`, cf. `client.replica`)
# sans toucher au fichier de travail — Modèle B : le canonique vit sur le VPS,
# le compute lit une réplique locale.
CANONICAL_DB = Path(os.environ.get("EURIO_DB_PATH") or (STATE_DIR / "eurio.db"))

# `state` is a sibling package of `api`; sys.path must contain ML_DIR for the
# bare import to resolve when uvicorn is launched from `ml/` (see Taskfile: `api`).
import sys as _sys
if str(ML_DIR) not in _sys.path:
    _sys.path.insert(0, str(ML_DIR))
from store import Store, local_state_store  # noqa: E402
import jobs as _jobs  # noqa: E402  — rail jobs/ générique (refacto-ml ADR D1)

# ─── App ───

app = FastAPI(
    title="Eurio ML API",
    version="0.2.0",
    docs_url="/docs",
    # Auth bearer globale (Modèle B C2) : no-op tant que EURIO_API_AUTH_REQUIRED
    # n'est pas mis (local inchangé) ; requise sur le serveur canonique.
    dependencies=[Depends(api_auth.require_token)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",  # Vite fallback quand 5173 occupé
        "http://localhost:5175",  # Vite fallback secondaire
        "http://localhost:5176",  # Vite fallback tertiaire
        "http://localhost:5177",
        "http://localhost:4173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Garde Direction A (C5) : canonique read-only sur cette machine ──────────
# Sous le flip (`EURIO_DB_READONLY=1` + réplique pull-ée), toute route locale
# qui tente encore une écriture canonique voit son `conn.execute(<write>)` lever
# `sqlite3.OperationalError: attempt to write a readonly database`. Sans garde,
# c'est un 500 opaque. Ce handler le TRADUIT en 503 actionnable : le hot-path
# (décisions review/funnel/lot, reassign) est déjà routé au VPS côté front
# (eurioApi) ; les writers résiduels non encore routés (requalify/lane/correct,
# crops cv2) refusent alors BRUYAMMENT + CLAIREMENT au lieu de corrompre en
# silence (leçon #1). SQLite échoue au 1er DML sans rien committer → aucune
# transaction partielle à nettoyer, la traduction est sûre.
@app.exception_handler(sqlite3.OperationalError)
async def _readonly_write_guard(request, exc):  # noqa: ANN001
    from fastapi.responses import JSONResponse

    msg = str(exc)
    if "readonly database" in msg or "attempt to write" in msg:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Canonique en lecture seule sur cette machine (Direction A / "
                    "flip EURIO_DB_READONLY). Cette écriture doit passer par le "
                    "writer unique VPS (eurio-api). Route non encore reroutée — "
                    f"path={request.url.path}."
                ),
                "code": "canonical_readonly",
            },
        )
    # Autres OperationalError (lock, corruption…) : re-lever tel quel (500).
    raise exc


# ─── Shared state ───

_env: dict[str, str] = {}
_supabase: SupabaseClient | None = None
_store = Store(CANONICAL_DB)
_runner = TrainingRunner(_store)

# Modèle B (C2/C3) : auth bearer + route d'ingestion run-batch sur le store partagé.
api_auth.bind(_store)
ingest_routes.bind(_store)
app.include_router(ingest_routes.router)

# Modèle B (R2) : endpoint réplique (snapshot VACUUM INTO cohérent). Léger →
# monté ici comme sur l'image lean (cf. règle de sync FULL↔LEAN dans server_serve).
from serving import db_routes  # noqa: E402
app.include_router(db_routes.router)

# local-sync (event-log/outbox/worker) retiré C6a (démonté) + C6b (modules
# supprimés) — Direction A remplace le cycle push/pull/hlc par des POST
# directs /ingest/* (crops/faces/dino/run).

# Wire augmentation routes to the shared store (Modèle B : sources d'aperçu
# résolues via MinIO, plus de dépendance Supabase).
augmentation_routes.bind(_store)
app.include_router(augmentation_routes.router)

# Wire benchmark routes (real-photo hold-out — no Supabase dependency).
benchmark_routes.bind(_store)
app.include_router(benchmark_routes.router)

# Wire lab routes — orchestrates training + benchmark as "iterations".
_iteration_runner = iteration_runner_module.bind(_store, _runner)
lab_routes.bind(_store, _iteration_runner)
app.include_router(lab_routes.router)

# /whoami : origine machine (mac/pc) de CE poste de calcul — le front s'en sert
# pour gater les actions lourdes aux itérations créées ici (R3). Public.
from serving import whoami_routes  # noqa: E402
app.include_router(whoami_routes.router)

# Wire /sources/status — quota + temporal + coverage aggregation.
app.include_router(sources_routes.router)

# Wire /review-queue — single-item review flow over the queue populated
# by the orchestrator's `enqueue` step.
app.include_router(review_queue_routes.router)

# Wire /peer-arbitration — arbitrage admin des décisions des amis reviewers
# (staging peer_review_decisions, réconcilié depuis le service review VPS).
app.include_router(peer_arbitration_routes.router)

# Wire /coins/{eurio_id}/assets — enrichment gallery on CoinDetailPage.
from serving import coin_assets_routes  # noqa: E402

coin_assets_routes.bind(_store)
app.include_router(coin_assets_routes.router)

# Wire /coins/* (detail, lookups, prices, i18n, embedding, series, patch) —
# P.8a doctrine SQLite-only, remplace les reads Supabase du frontend.
from serving import coins_routes, sets_routes  # noqa: E402

coins_routes.bind(_store)
app.include_router(coins_routes.router)
sets_routes.bind(_store)
app.include_router(sets_routes.router)

# Wire /coins-review — review queue UI (chunk 3e).
coins_review_routes.bind(lambda: get_supabase())
app.include_router(coins_review_routes.router)

# Wire /bench — studio bench du theme-matcher (local-only, lecture seule).
app.include_router(bench_routes.router)

# Wire /crop-bench — banc de qualité du crop eBay (oracle Otsu, lecture seule).
app.include_router(crop_bench_routes.router)
app.include_router(denom_gold_routes.router)
app.include_router(fragment_audit_routes.router)
app.include_router(crop_recovery_routes.router)

# Wire /operations — dashboard d'opérations J1/J4 (pulse, readiness, diversity, cohorts).
app.include_router(operations_routes.router)

# Wire /referential — gestion du référentiel coin (images canoniques locales + à venir).
app.include_router(referential_routes.router)


@app.on_event("startup")
def _replica_autopull_startup() -> None:
    """Direction A — transparence de sync : rafraîchit la réplique locale
    (``state/eurio.replica.db``) en tâche de fond tant que le serveur tourne
    (sqlite3_rsync incrémental, ~3 s / 2 min, clé dédiée). No-op si le
    transport rsync n'est pas provisionné ou EURIO_REPLICA_AUTOPULL=0.
    Cf. docs/work-in-progress/local-sync/replica-auto-sync.md."""
    try:
        from client.replica import start_autopull_thread

        start_autopull_thread()
    except Exception as exc:  # noqa: BLE001 — confort, jamais bloquant au boot
        import logging
        logging.getLogger(__name__).warning(
            "réplique autopull non démarré: %s", exc
        )


@app.on_event("startup")
def _augmentation_startup() -> None:
    """Sweep stale preview dirs (TTL = 24h) at each API startup."""
    try:
        augmentation_routes.cleanup_expired_previews()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "augmentation preview cleanup failed at startup: %s", exc
        )


@app.on_event("startup")
def _benchmark_startup() -> None:
    """Sweep stale benchmark thumbnails (TTL = 24h) at each API startup."""
    try:
        benchmark_routes.cleanup_expired_thumbnails()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "benchmark thumbnail cleanup failed at startup: %s", exc
        )


@app.on_event("startup")
def _sources_startup() -> None:
    """Reset orphan `source_runs` rows left in `status='running'` from a
    previous process. Without this, the anti-double-run guard would
    refuse new runs forever for any source whose previous run died with
    uvicorn (Ctrl-C, crash, kill -9)."""
    try:
        n = sources_routes.reset_orphan_runs(_store)
        if n:
            import logging
            logging.getLogger(__name__).info(
                "Sources orchestrator: marked %d orphan run(s) as failed at startup", n,
            )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "Sources orphan reset failed at startup: %s", exc
        )


@app.on_event("startup")
def _recrop_startup() -> None:
    """Reaper précis des `cohort_jobs` recrop laissés `running` par un process
    mort (BUG-1 : zombie persisté). Le recrop tourne en subprocess détaché qui
    survit au `--reload`, donc on ne tue QUE les jobs dont le PID n'existe plus
    (cf. `lab_routes.reap_orphan_cohort_jobs`)."""
    try:
        n = lab_routes.reap_orphan_cohort_jobs(local_state_store())
        if n:
            import logging
            logging.getLogger(__name__).info(
                "Cohort jobs: reaped %d orphan recrop job(s) at startup", n,
            )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "Cohort jobs orphan reap failed at startup: %s", exc
        )
    # Même doctrine pour les scans du Jeu d'entraînement (subprocess détaché).
    try:
        n = lab_routes.reap_orphan_training_scans(local_state_store())
        if n:
            import logging
            logging.getLogger(__name__).info(
                "Training scans: reaped %d orphan scan(s) at startup", n,
            )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "Training scans orphan reap failed at startup: %s", exc
        )


@app.on_event("startup")
def _jobs_startup() -> None:
    """Reaper boot du rail `jobs/` générique : clôt en `failed` les jobs détachés
    restés `running` dont le PID est mort (process précédent tué). Les jobs qui ont
    survécu au `--reload` (PID vivant) sont préservés. Cf. `jobs.reaper.reap_orphans`."""
    try:
        n = _jobs.reap_orphans(_store._connection())  # noqa: SLF001
        if n:
            import logging
            logging.getLogger(__name__).info(
                "Jobs rail: reaped %d orphan job(s) at startup", n,
            )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "Jobs rail orphan reap failed at startup: %s", exc
        )


@app.on_event("startup")
def _lab_startup() -> None:
    """Cleanup any Lab iteration left mid-flight by a previous process.

    The runner does NOT auto-retry stuck iterations (auto-retry was
    found to be more dangerous than helpful — it could re-bake mid-flight
    or duplicate a training). Instead :meth:`recover_on_boot` marks
    training-stuck iterations as ``failed`` and benchmarking-stuck ones
    as ``completed`` with a partial benchmark row, so the user can
    re-launch explicitly.
    """
    try:
        cleaned = _iteration_runner.recover_on_boot()
        if cleaned:
            import logging
            logging.getLogger(__name__).info(
                "Lab runner cleaned up %d stuck iteration(s) at startup",
                cleaned,
            )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "Lab runner recovery failed at startup: %s", exc
        )


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


class TrainConfig(BaseModel):
    device: str = "auto"


class AugmentRequest(BaseModel):
    design_ids: list[int]
    target_per_class: int = 50


class StageItem(BaseModel):
    class_id: str
    class_kind: str  # 'eurio_id' | 'design_group_id'
    aug_recipe_id: str | None = None  # id OR name; resolved server-side


class StagePayload(BaseModel):
    items: list[StageItem]


class RunPayload(BaseModel):
    epochs: int | None = None
    batch_size: int | None = None
    m_per_class: int | None = None
    target_augmented: int | None = None
    aug_recipe: str | None = None  # id OR name — overrides per-class staging


class EstimatePayload(BaseModel):
    added_count: int = 0
    removed_count: int = 0


class ConfusionMapComputeRequest(BaseModel):
    eurio_ids: list[str] | None = None
    limit: int | None = None
    encoder_version: str | None = None
    thresholds: str | None = None
    thresholds_mode: str | None = None  # 'percentile' (default) | 'fixed'


# ─── Health ───


@app.get("/health", response_model=HealthResponse)
def health():
    """Cheap liveness probe — no I/O, no Supabase round-trips.

    The admin frontend polls this every 30s on several pages just to know
    whether the API is up. Rich diagnostics (model version, supabase counts,
    queue length, active runs) live behind ``/health/full`` so the polling
    path stays fast and offline-tolerant.
    """
    return HealthResponse(status="ok")


@app.get("/health/full", response_model=HealthResponse)
def health_full():
    """Rich health payload — hits Supabase and the local store.

    Slow on cold caches (~3-5s as of 2026-04). Dashboards/CLIs that want
    deep status should hit this; UI polling code should use ``/health``.
    """
    resp = HealthResponse(status="ok")

    # Current model info (promoted prod model)
    meta_path = PROD_TFLITE_DIR / "model_meta.json"
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
        # Count distinct trained designs (not raw embedding rows)
        embs = sb.query("coin_embeddings", select="eurio_id")
        trained_eurio_ids = {e["eurio_id"] for e in embs}
        if trained_eurio_ids:
            all_coins = sb.query(
                "coins",
                select="eurio_id,cross_refs",
                params={"cross_refs->numista_id": "not.is.null"},
            )
            trained_nids = set()
            for c in all_coins:
                if c["eurio_id"] in trained_eurio_ids:
                    nid = c.get("cross_refs", {}).get("numista_id")
                    if nid:
                        trained_nids.add(nid)
            resp.trained_count = len(trained_nids)
        else:
            resp.trained_count = 0
    except Exception:
        resp.supabase_connected = False

    # Staging + active run
    resp.queue_length = (
        len(_store.list_staging()) + len(_store.list_removal_staging())
    )
    resp.active_count = 1 if _runner.active_run() is not None else 0

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


@app.get("/datasets/{numista_id}/captures/{filename}")
def get_capture_image(numista_id: int, filename: str):
    """Serve a device-side capture (Sprint 2 — needed for aug-vs-real
    side-by-side gallery). Captures come from the cohort capture flow and
    are immutable once synced — same Cache-Control as augmentations."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Chemin invalide")
    expected_parent = (DATASETS_DIR / str(numista_id) / "captures").resolve()
    resolved = (expected_parent / filename).resolve()
    if not str(resolved).startswith(str(expected_parent)):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Image non trouvée")
    return FileResponse(
        resolved,
        media_type="image/jpeg",
        headers={"Cache-Control": "max-age=86400"},
    )


@app.get("/datasets/{numista_id}/augmentations/{iteration_id}/{filename}")
def get_iteration_augmentation_image(
    numista_id: int, iteration_id: str, filename: str
):
    """Serve a per-iteration augmentation snapshot image (Sprint 1 / D-004).

    Cache-Control is aggressive — once an iteration is created with a fixed
    seed, ``sample_NNN.jpg`` for that ``(numista_id, iteration_id)`` is
    immutable until the user explicitly regenerates.
    """
    for piece in (iteration_id, filename):
        if ".." in piece or "/" in piece or "\\" in piece:
            raise HTTPException(status_code=400, detail="Chemin invalide")
    expected_parent = (
        DATASETS_DIR / str(numista_id) / "augmentations" / iteration_id
    ).resolve()
    resolved = (expected_parent / filename).resolve()
    if not str(resolved).startswith(str(expected_parent)):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Image non trouvée")
    return FileResponse(
        resolved,
        media_type="image/jpeg",
        headers={"Cache-Control": "max-age=86400"},
    )


# ─── Training ───


def _run_to_dict(row) -> dict:
    if row is None:
        return None  # type: ignore[return-value]
    return {
        "id": row.id,
        "version": row.version,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "config": row.config,
        "classes_before": [c.to_dict() for c in row.classes_before],
        "classes_after": [c.to_dict() for c in row.classes_after],
        "classes_added": [c.to_dict() for c in row.classes_added],
        "classes_removed": [c.to_dict() for c in row.classes_removed],
        "loss": row.loss,
        "recall_at_1": row.recall_at_1,
        "recall_at_3": row.recall_at_3,
        "epoch_duration_median_sec": row.epoch_duration_median_sec,
        "error": row.error,
        "aug_recipe_id": row.aug_recipe_id,
    }


def _run_summary(row) -> dict:
    d = _run_to_dict(row)
    d["n_added"] = len(row.classes_added)
    d["n_removed"] = len(row.classes_removed)
    d["n_after"] = len(row.classes_after)
    return d


@app.get("/training/config")
def training_config() -> dict:
    return {"device": _runner.device}


@app.post("/training/config")
def set_training_config(config: TrainConfig) -> dict:
    _runner.device = config.device
    return {"device": _runner.device}


@app.get("/training/stage")
def training_stage_list() -> dict:
    staged = _store.list_staging_with_recipe()
    return {
        "staged": [
            {**ref.to_dict(), "aug_recipe_id": recipe_id}
            for ref, recipe_id in staged
        ],
        "removal": [c.to_dict() for c in _store.list_removal_staging()],
    }


@app.post("/training/stage")
def training_stage(payload: StagePayload) -> dict:
    from store import ClassRef

    refs = [ClassRef(i.class_id, i.class_kind) for i in payload.items]
    recipe_ids: list[str | None] = []
    for item in payload.items:
        if item.aug_recipe_id is None:
            recipe_ids.append(None)
            continue
        recipe = _store.get_recipe(item.aug_recipe_id)
        if recipe is None:
            raise HTTPException(
                status_code=400,
                detail=f"aug_recipe_id {item.aug_recipe_id!r} introuvable",
            )
        recipe_ids.append(recipe.id)

    _store.stage_classes(refs, aug_recipe_ids=recipe_ids)
    staged = _store.list_staging_with_recipe()
    return {
        "staged": [
            {**ref.to_dict(), "aug_recipe_id": rid}
            for ref, rid in staged
        ]
    }


@app.delete("/training/stage/{class_id}")
def training_unstage(class_id: str) -> dict:
    removed = _store.unstage_class(class_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Class non staged")
    return {"removed": class_id}


@app.post("/training/removal")
def training_stage_removal(payload: StagePayload) -> dict:
    from store import ClassRef

    refs = [ClassRef(i.class_id, i.class_kind) for i in payload.items]
    _store.stage_removal(refs)
    return {"removal": [c.to_dict() for c in _store.list_removal_staging()]}


@app.delete("/training/removal/{class_id}")
def training_unstage_removal(class_id: str) -> dict:
    removed = _store.unstage_removal(class_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Class non staged for removal")
    return {"removed": class_id}


@app.post("/training/run")
def training_run(payload: RunPayload | None = None) -> dict:
    if _runner.active_run() is not None:
        raise HTTPException(status_code=409, detail="Un run est déjà actif")

    added_with_recipe = _store.clear_staging_with_recipe()
    added = [ref for ref, _ in added_with_recipe]
    staged_recipe_ids = [rid for _, rid in added_with_recipe]
    removed = _store.clear_removal_staging()
    # Empty staging+removal is allowed when a current model exists — interpreted
    # as a re-train on the same classes. classes_after resolves to classes_before
    # in the runner, which is exactly what we want when iterating on training
    # config (recipes, transforms, hyper-params) without changing the class set.
    if not added and not removed and not _runner.current_classes():
        raise HTTPException(
            status_code=400,
            detail="Rien à entraîner — staging et removal vides, et aucun modèle existant",
        )

    config: dict = {}
    aug_recipe_override: str | None = None
    if payload:
        for key in ("epochs", "batch_size", "m_per_class", "target_augmented"):
            val = getattr(payload, key)
            if val is not None:
                config[key] = val
        aug_recipe_override = payload.aug_recipe

    # Resolve effective aug_recipe for this run:
    #   - explicit payload.aug_recipe wins over per-class staging
    #   - else, if all staged items share the same non-null recipe, use it
    #   - else (heterogeneous or all-null), no recipe is attached
    effective_recipe_id: str | None = None
    if aug_recipe_override:
        recipe = _store.get_recipe(aug_recipe_override)
        if recipe is None:
            # Restore staging before raising.
            _store.stage_classes(added, aug_recipe_ids=staged_recipe_ids)
            _store.stage_removal(removed)
            raise HTTPException(
                status_code=400,
                detail=f"aug_recipe {aug_recipe_override!r} introuvable",
            )
        effective_recipe_id = recipe.id
    else:
        non_null = {rid for rid in staged_recipe_ids if rid is not None}
        if len(non_null) == 1:
            effective_recipe_id = next(iter(non_null))

    if effective_recipe_id is not None:
        config["aug_recipe"] = effective_recipe_id

    try:
        row = _runner.start_run(added=added, removed=removed, config=config)
    except RuntimeError as exc:
        # Restore staging if the runner rejected the run.
        _store.stage_classes(added, aug_recipe_ids=staged_recipe_ids)
        _store.stage_removal(removed)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if effective_recipe_id is not None:
        _store.update_run_aug_recipe(row.id, effective_recipe_id)
        row = _store.get_run(row.id) or row
    return _run_to_dict(row)


@app.get("/training/runs")
def training_runs_list(limit: int = 50, offset: int = 0) -> dict:
    runs = _runner.list_runs(limit=limit, offset=offset)
    return {
        "items": [_run_summary(r) for r in runs],
        "total": _runner.count_runs(),
    }


@app.get("/training/runs/active")
def training_run_active() -> dict | None:
    row = _runner.active_run()
    if row is None:
        return None
    payload = _run_to_dict(row)
    payload["steps"] = [
        {
            "step_index": s.step_index,
            "name": s.name,
            "status": s.status,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
            "detail": s.detail,
        }
        for s in _runner.list_steps(row.id)
    ]
    snap = _runner.active_snapshot()
    payload["epoch"] = snap["epoch"] if snap else 0
    payload["epochs_total"] = snap["epochs_total"] if snap else row.config.get("epochs", 0)
    return payload


@app.get("/training/runs/{run_id}")
def training_run_detail(run_id: str) -> dict:
    row = _runner.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run non trouvé")
    payload = _run_to_dict(row)
    payload["steps"] = [
        {
            "step_index": s.step_index,
            "name": s.name,
            "status": s.status,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
            "detail": s.detail,
        }
        for s in _runner.list_steps(run_id)
    ]
    payload["epochs"] = [
        {
            "epoch": e.epoch,
            "train_loss": e.train_loss,
            "recall_at_1": e.recall_at_1,
            "recall_at_3": e.recall_at_3,
            "lr": e.lr,
            "duration_sec": e.duration_sec,
        }
        for e in _runner.list_epochs(run_id)
    ]
    payload["per_class_metrics"] = [
        {
            "class_id": c.class_id,
            "class_kind": c.class_kind,
            "recall_at_1": c.recall_at_1,
            "n_train_images": c.n_train_images,
            "n_val_images": c.n_val_images,
        }
        for c in _runner.list_run_classes(run_id)
    ]
    return payload


@app.get("/training/runs/{run_id}/logs")
def training_run_logs(run_id: str, tail: int = 200) -> dict:
    row = _runner.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run non trouvé")
    lines = _runner.load_logs(run_id)
    if tail > 0:
        lines = lines[-tail:]
    return {
        "run_id": run_id,
        "status": row.status,
        "lines": lines,
    }


@app.get("/training/classes")
def training_classes() -> dict:
    # Current classes known to the prepared dataset (manifest) — what the
    # deployed model actually knows.
    current = _runner.current_classes()
    runs_by_class: dict[str, dict] = {}
    # Hydrate per-class summary via the latest run metrics.
    # Walk the last ~20 runs once, keep the most recent metric per class.
    recent_runs = _runner.list_runs(limit=20)
    for r in recent_runs:
        for metric in _runner.list_run_classes(r.id):
            existing = runs_by_class.get(metric.class_id)
            if existing is None or r.version > existing["last_trained_version"]:
                runs_by_class[metric.class_id] = {
                    "last_trained_version": r.version,
                    "recall_at_1": metric.recall_at_1,
                    "n_train_images": metric.n_train_images,
                    "n_val_images": metric.n_val_images,
                }

    items = []
    for c in current:
        summary = runs_by_class.get(c.class_id, {})
        items.append(
            {
                "class_id": c.class_id,
                "class_kind": c.class_kind,
                "last_trained_version": summary.get("last_trained_version"),
                "recall_at_1": summary.get("recall_at_1"),
                "n_train_images": summary.get("n_train_images"),
                "n_val_images": summary.get("n_val_images"),
            }
        )
    return {"items": items, "total": len(items)}


@app.get("/training/classes/{class_id}")
def training_class_detail(class_id: str) -> dict:
    history = _runner.list_runs_for_class(class_id)
    if not history:
        # Might be a class never trained; return empty history.
        return {"class_id": class_id, "runs": []}
    class_kind = history[0][1].class_kind
    return {
        "class_id": class_id,
        "class_kind": class_kind,
        "runs": [
            {
                "run_id": run.id,
                "version": run.version,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "recall_at_1": metric.recall_at_1,
                "n_train_images": metric.n_train_images,
                "n_val_images": metric.n_val_images,
            }
            for run, metric in history
        ],
    }


@app.post("/training/estimate")
def training_estimate(payload: EstimatePayload) -> dict:
    recent = _runner.list_runs(limit=10)
    durations = [
        r.epoch_duration_median_sec
        for r in recent
        if r.epoch_duration_median_sec is not None
    ]
    current_classes = len(_runner.current_classes())
    new_classes = current_classes + payload.added_count - payload.removed_count
    default_epochs = 40
    overhead = 1.2

    if durations:
        median_epoch = sum(durations) / len(durations)
        scaling = new_classes / max(current_classes, 1)
        estimated = median_epoch * default_epochs * scaling * overhead
        basis = "historical"
    else:
        estimated = 30.0 * default_epochs * overhead  # ~24 min fallback
        basis = "default"

    return {
        "estimated_sec": round(estimated, 1),
        "basis": basis,
        "current_classes": current_classes,
        "new_classes": new_classes,
    }


# ─── Export TFLite ───

# ─── Jobs détachés (garde anti-double-run robuste au `--reload`) ──────────────
# BUG-1 (documenté server.py:246-276, corrigé dans lab_routes/cohort) : un job
# lancé par `threading.Thread(subprocess.run)` + flag mémoire `running` perd sa
# garde à chaque `--reload` (le flag repasse False) → double compute possible
# écrasant checkpoints/prod. Correctif : Popen `start_new_session=True` (le
# process détaché survit au reload) + PID persisté dans un sidecar ; la garde
# lit la vivacité du PID, pas un flag mémoire volatil.
_JOBS_DIR = ML_DIR / "cache" / "jobs"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _job_running(pid_file: Path) -> bool:
    """Vrai ssi un sidecar PID existe ET son process est vivant. Nettoie un
    sidecar périmé (process mort) au passage — pas de zombie qui bloque à jamais."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return False
    if _pid_alive(pid):
        return True
    pid_file.unlink(missing_ok=True)
    return False


def _spawn_detached_job(pid_file: Path, cmd: list[str], log_path: Path, on_done=None) -> int:
    """Popen détaché (nouvelle session → survit au `--reload` du worker uvicorn),
    PID persisté avant retour. Un thread attend la fin, retire le sidecar puis
    appelle ``on_done(returncode, log_path)``. Retourne le PID."""
    import subprocess
    import threading

    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "w")  # noqa: SIM115 — fermé dans le thread waiter
    proc = subprocess.Popen(
        cmd, cwd=str(ML_DIR), stdout=log_fh, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))

    def _wait() -> None:
        try:
            rc = proc.wait()
        finally:
            log_fh.close()
            pid_file.unlink(missing_ok=True)
        if on_done is not None:
            on_done(rc, log_path)

    threading.Thread(target=_wait, daemon=True).start()
    return proc.pid


_EXPORT_PID_FILE = _JOBS_DIR / "export_tflite.pid"
_export_status: dict = {"running": False, "error": None, "last_export": None}


@app.get("/export/status")
def export_status() -> dict:
    """Get TFLite export status and delta info."""
    # Current TFLite info
    tflite_path = PROD_TFLITE_DIR / "eurio_embedder_v1.tflite"
    meta_path = PROD_TFLITE_DIR / "model_meta.json"
    emb_path = PROD_EMBEDDINGS_DIR / "embeddings_v1.json"

    tflite_info = None
    if tflite_path.exists():
        from datetime import datetime
        tflite_info = {
            "size_mb": round(tflite_path.stat().st_size / (1024 * 1024), 1),
            "compiled_at": datetime.fromtimestamp(tflite_path.stat().st_mtime).isoformat(),
        }

    # Count classes in current embeddings (what was compiled into TFLite)
    compiled_classes = 0
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        compiled_classes = len(meta.get("classes", []))

    # Count classes in current embeddings file (what's available now)
    available_classes = 0
    if emb_path.exists():
        emb = json.loads(emb_path.read_text())
        available_classes = len(emb.get("coins", {}))

    # Count trained in Supabase
    trained_in_supabase = 0
    try:
        sb = get_supabase()
        trained_in_supabase = sb.count("coin_embeddings")
    except Exception:
        pass

    return {
        "running": _job_running(_EXPORT_PID_FILE),
        "error": _export_status["error"],
        "tflite": tflite_info,
        "compiled_classes": compiled_classes,
        "available_classes": available_classes,
        "trained_in_supabase": trained_in_supabase,
        "delta": available_classes - compiled_classes,
    }


@app.post("/export/tflite")
def trigger_export() -> dict:
    """Trigger TFLite export in a detached background job (guard anti-double-run
    robuste au `--reload` : PID persisté + vivacité, cf. `_spawn_detached_job`)."""
    if _job_running(_EXPORT_PID_FILE):
        raise HTTPException(status_code=409, detail="Export déjà en cours")

    _export_status["error"] = None
    log_path = _JOBS_DIR / "export_tflite.log"

    def _on_done(rc: int, log: Path) -> None:
        if rc != 0:
            tail = log.read_text()[-4000:] if log.exists() else ""
            _export_status["error"] = tail.strip() or "Export failed"
        else:
            _export_status["error"] = None
            _export_status["last_export"] = datetime.utcnow().isoformat()

    pid = _spawn_detached_job(
        _EXPORT_PID_FILE,
        [VENV_PYTHON, str(ML_DIR / "export_tflite.py")],
        log_path,
        on_done=_on_done,
    )
    return {"started": True, "pid": pid}


@app.post("/export/validate")
def validate_export() -> dict:
    """Run TFLite validation against PyTorch model on test images."""
    import subprocess

    result = subprocess.run(
        [VENV_PYTHON, str(ML_DIR / "validate_export.py"), "--num-images", "20"],
        cwd=str(ML_DIR),
        capture_output=True,
        text=True,
        timeout=120,
    )

    lines = (result.stdout or "").strip().split("\n")
    passed = "pass" in (result.stdout or "").lower()

    return {
        "passed": passed,
        "exit_code": result.returncode,
        "output": lines,
        "error": result.stderr if result.returncode != 0 else None,
    }


@app.get("/export/model-sync")
def model_sync_status() -> dict:
    """Check sync status between local model and Supabase Storage."""
    local_model = CHECKPOINTS_DIR / "best_model.pth"
    local_meta = PROD_TFLITE_DIR / "model_meta.json"
    local_emb = PROD_EMBEDDINGS_DIR / "embeddings_v1.json"

    local_info = {}
    if local_model.exists():
        local_info["model"] = {
            "size_mb": round(local_model.stat().st_size / (1024 * 1024), 1),
            "modified_at": datetime.fromtimestamp(local_model.stat().st_mtime).isoformat(),
        }
    if local_meta.exists():
        meta = json.loads(local_meta.read_text())
        local_info["meta"] = {
            "classes": meta.get("classes", []),
            "num_classes": meta.get("num_classes", 0),
            "mode": meta.get("mode"),
        }
    if local_emb.exists():
        emb = json.loads(local_emb.read_text())
        local_info["embeddings"] = {
            "num_classes": len(emb.get("coins", {})),
            "dim": emb.get("embedding_dim", 256),
        }

    # Check what's in Supabase Storage
    remote_info = {}
    try:
        sb = get_supabase()
        remote_info["available"] = True
    except Exception:
        remote_info["available"] = False

    return {"local": local_info, "remote": remote_info}


@app.post("/export/upload-model")
def upload_model_to_supabase() -> dict:
    """Upload best_model.pth + promoted prod model_meta/embeddings to Supabase Storage.

    Model artefacts are read from ``ml/prod/current/`` (phase 4). The class-table
    push to Supabase is also done by ``scripts.promote_iteration``; this endpoint
    mirrors the model files into the ``ml-models`` storage bucket for backup.
    """
    import httpx

    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    service_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_key:
        raise HTTPException(status_code=503, detail="Supabase non configuré")

    bucket = "ml-models"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }

    files_to_upload = [
        (CHECKPOINTS_DIR / "best_model.pth", "best_model.pth"),
        (PROD_TFLITE_DIR / "model_meta.json", "model_meta.json"),
        (PROD_EMBEDDINGS_DIR / "embeddings_v1.json", "embeddings_v1.json"),
        (PROD_EMBEDDINGS_DIR / "coin_embeddings.json", "coin_embeddings.json"),
    ]

    uploaded = []
    errors = []

    with httpx.Client(headers=headers, timeout=120) as client:
        # Ensure bucket exists
        client.post(
            f"{supabase_url}/storage/v1/bucket",
            json={"id": bucket, "name": bucket, "public": False},
        )

        for local_path, remote_name in files_to_upload:
            if not local_path.exists():
                continue
            content_type = "application/octet-stream"
            if remote_name.endswith(".json"):
                content_type = "application/json"

            resp = client.post(
                f"{supabase_url}/storage/v1/object/{bucket}/{remote_name}",
                content=local_path.read_bytes(),
                headers={
                    **headers,
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
            )
            if resp.status_code < 400:
                size_kb = round(local_path.stat().st_size / 1024, 1)
                uploaded.append({"name": remote_name, "size_kb": size_kb})
            else:
                errors.append({"name": remote_name, "error": resp.text})

    return {
        "uploaded": uploaded,
        "errors": errors,
        "total_uploaded": len(uploaded),
    }


@app.post("/export/deploy")
def deploy_to_android() -> dict:
    """Copy promoted prod TFLite + embeddings + meta to Android assets.

    Reads ``ml/prod/current/`` (phase 4). Equivalent to the canonical CLI
    ``python -m scripts.promote_prod_assets`` — prefer that for scripted
    deploys; this endpoint exists for the admin one-click flow.
    """
    import shutil

    assets = ML_DIR.parent / "app-android" / "src" / "main" / "assets"
    models_dir = assets / "models"
    data_dir = assets / "data"

    deployed = []
    for src, dst_dir, name in [
        (PROD_TFLITE_DIR / "eurio_embedder_v1.tflite", models_dir, "TFLite model"),
        (PROD_EMBEDDINGS_DIR / "coin_embeddings.json", data_dir, "Embeddings"),
        (PROD_TFLITE_DIR / "model_meta.json", data_dir, "Metadata"),
    ]:
        if src.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst_dir / src.name))
            deployed.append(name)

    return {"deployed": deployed, "count": len(deployed)}


# ─── Augment ───


@app.post("/augment")
def augment_designs(req: AugmentRequest) -> dict:
    """Generate augmented images for specified designs (synchronous)."""
    import sys

    sys.path.insert(0, str(ML_DIR))
    from training.augment_synthetic import augment_coin

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


# ─── Confusion Map ───

_DEFAULT_CONFUSION_ENCODER = "dinov2-vits14"
_CONFUSION_STATUS_FILE = ML_DIR / "cache" / "confusion_map_status.json"
_CONFUSION_PID_FILE = _JOBS_DIR / "confusion_map.pid"

_confusion_status: dict = {
    "error": None,
    "job_id": None,
    "last_computed_at": None,
    "progress": {"current": 0, "total": 0, "stage": "idle"},
}


def _confusion_db_connect():
    """Connexion read-only à la eurio.db locale (F02/C2 : coin_confusion_map est
    rapatriée de Supabase). ``CANONICAL_DB`` honore déjà ``EURIO_DB_PATH`` /
    réplique. Retourne None si le fichier n'existe pas (dev sans DB)."""
    if not CANONICAL_DB.exists():
        return None
    conn = sqlite3.connect(f"file:{CANONICAL_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _confusion_last_computed_at(encoder_version: str | None = None) -> str | None:
    conn = _confusion_db_connect()
    if conn is None:
        return None
    try:
        if encoder_version:
            row = conn.execute(
                "SELECT MAX(computed_at) AS m FROM coin_confusion_map "
                "WHERE encoder_version = ?",
                (encoder_version,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(computed_at) AS m FROM coin_confusion_map"
            ).fetchone()
        return row["m"] if row else None
    except Exception:  # noqa: BLE001 — table absente (dev) → pas de date
        return None
    finally:
        conn.close()


def _confusion_enrich(conn, eurio_ids: list[str]) -> dict[str, dict]:
    """(country, year, theme, face_value, image_url) pour une liste de coins,
    depuis eurio.db (coins + coin_canonical_images obverse)."""
    unique = sorted({e for e in eurio_ids if e})
    if not unique:
        return {}
    ph = ",".join("?" * len(unique))
    rows = conn.execute(
        f"SELECT eurio_id, country, year, theme, face_value FROM coins "
        f"WHERE eurio_id IN ({ph})",
        unique,
    ).fetchall()
    out: dict[str, dict] = {}
    for c in rows:
        img = conn.execute(
            "SELECT url FROM coin_canonical_images WHERE eurio_id = ? "
            "ORDER BY CASE role WHEN 'obverse' THEN 0 ELSE 1 END LIMIT 1",
            (c["eurio_id"],),
        ).fetchone()
        out[c["eurio_id"]] = {
            "country": c["country"],
            "year": c["year"],
            "theme": c["theme"],
            "face_value": c["face_value"],
            "image_url": img["url"] if img else None,
        }
    return out


def _refresh_confusion_progress() -> None:
    """Merge on-disk progress from the worker script into the in-memory status."""
    if not _CONFUSION_STATUS_FILE.exists():
        return
    try:
        data = json.loads(_CONFUSION_STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return
    stage = data.get("stage")
    if stage:
        _confusion_status["progress"] = {
            "current": int(data.get("current", 0)),
            "total": int(data.get("total", 0)),
            "stage": stage,
        }


@app.post("/confusion-map/compute")
def confusion_map_compute(req: ConfusionMapComputeRequest | None = None) -> dict:
    """Trigger DINOv2 confusion cartography in a detached background job.

    F02/C2 : le worker écrit désormais ``coin_confusion_map`` dans eurio.db (push
    canonique Direction A, ou local en Model A). Garde anti-double-run robuste au
    `--reload` via PID persisté (cf. `_spawn_detached_job`)."""
    import uuid

    if _job_running(_CONFUSION_PID_FILE):
        raise HTTPException(status_code=409, detail="Cartographie déjà en cours")

    payload = req or ConfusionMapComputeRequest()
    encoder_version = payload.encoder_version or _DEFAULT_CONFUSION_ENCODER
    job_id = uuid.uuid4().hex[:12]

    cmd: list[str] = [
        VENV_PYTHON,
        str(ML_DIR / "training" / "eval" / "confusion_map.py"),
        "--encoder-version",
        encoder_version,
        "--status-file",
        str(_CONFUSION_STATUS_FILE),
    ]
    if payload.eurio_ids:
        cmd.extend(["--eurio-ids", ",".join(payload.eurio_ids)])
    if payload.limit is not None:
        cmd.extend(["--limit", str(payload.limit)])
    if payload.thresholds:
        cmd.extend(["--thresholds", payload.thresholds])
    if payload.thresholds_mode:
        cmd.extend(["--thresholds-mode", payload.thresholds_mode])

    _confusion_status["error"] = None
    _confusion_status["job_id"] = job_id
    _confusion_status["progress"] = {"current": 0, "total": 0, "stage": "starting"}

    def _on_done(rc: int, log: Path) -> None:
        if rc != 0:
            tail = log.read_text()[-4000:] if log.exists() else ""
            _confusion_status["error"] = tail.strip() or "Compute failed"
        else:
            _confusion_status["error"] = None
            _confusion_status["last_computed_at"] = datetime.utcnow().isoformat()

    _spawn_detached_job(
        _CONFUSION_PID_FILE, cmd, _JOBS_DIR / "confusion_map.log", on_done=_on_done,
    )
    return {"started": True, "job_id": job_id}


@app.get("/confusion-map/status")
def confusion_map_status() -> dict:
    """Return current cartography job status + progress."""
    _refresh_confusion_progress()

    last_computed_at = (
        _confusion_status["last_computed_at"] or _confusion_last_computed_at()
    )

    return {
        "running": _job_running(_CONFUSION_PID_FILE),
        "error": _confusion_status["error"],
        "job_id": _confusion_status["job_id"],
        "progress": _confusion_status["progress"],
        "last_computed_at": last_computed_at,
    }


@app.get("/confusion-map/stats")
def confusion_map_stats(encoder_version: str = _DEFAULT_CONFUSION_ENCODER) -> dict:
    """Return zone counts + similarity histogram for the current encoder version.

    F02/C2 : lu depuis eurio.db (``coin_confusion_map`` rapatriée de Supabase)."""
    by_zone: dict[str, int] = {"green": 0, "orange": 0, "red": 0}
    bin_count = 20
    histogram = [0] * bin_count
    total = 0
    last_computed_at: str | None = None

    conn = _confusion_db_connect()
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT zone, nearest_similarity, computed_at FROM coin_confusion_map "
                "WHERE encoder_version = ?",
                (encoder_version,),
            ).fetchall()
        except Exception:  # noqa: BLE001 — table absente (dev) → stats vides
            rows = []
        finally:
            conn.close()
        total = len(rows)
        for r in rows:
            if r["zone"] in by_zone:
                by_zone[r["zone"]] += 1
            sim = min(max(float(r["nearest_similarity"] or 0.0), 0.0), 1.0)
            histogram[min(int(sim * bin_count), bin_count - 1)] += 1
            cat = r["computed_at"]
            if cat and (last_computed_at is None or cat > last_computed_at):
                last_computed_at = cat

    return {
        "total": total,
        "by_zone": by_zone,
        "last_computed_at": last_computed_at,
        "encoder_version": encoder_version,
        "histogram_bins": [
            {"bin_start": round(i / bin_count, 2), "count": histogram[i]}
            for i in range(bin_count)
        ],
    }


@app.get("/confusion-map/pairs")
def confusion_map_pairs(
    limit: int = 100,
    zone: str | None = None,
    encoder_version: str = _DEFAULT_CONFUSION_ENCODER,
) -> list[dict]:
    """Top-N unique confused pairs (deduped by sorted eurio_id tuple). eurio.db."""
    if limit <= 0 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit doit être entre 1 et 1000")
    if zone is not None and zone not in ("green", "orange", "red"):
        raise HTTPException(status_code=400, detail="zone invalide")

    conn = _confusion_db_connect()
    if conn is None:
        return []
    try:
        sql = (
            "SELECT eurio_id, nearest_eurio_id, nearest_similarity, zone "
            "FROM coin_confusion_map "
            "WHERE encoder_version = ? AND nearest_eurio_id IS NOT NULL"
        )
        params: list = [encoder_version]
        if zone is not None:
            sql += " AND zone = ?"
            params.append(zone)
        sql += " ORDER BY nearest_similarity DESC"
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:  # noqa: BLE001 — table absente (dev)
            return []

        seen: set[tuple[str, str]] = set()
        pairs: list[dict] = []
        for r in rows:
            a, b = r["eurio_id"], r["nearest_eurio_id"]
            if not a or not b:
                continue
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append({
                "eurio_id_a": key[0],
                "eurio_id_b": key[1],
                "similarity": r["nearest_similarity"],
                "zone": r["zone"],
            })
            if len(pairs) >= limit:
                break

        ids = [i for p in pairs for i in (p["eurio_id_a"], p["eurio_id_b"])]
        enriched = _confusion_enrich(conn, ids)
        for p in pairs:
            p["coin_a"] = enriched.get(p["eurio_id_a"])
            p["coin_b"] = enriched.get(p["eurio_id_b"])
        return pairs
    finally:
        conn.close()


@app.get("/confusion-map/coin/{eurio_id}")
def confusion_map_coin(
    eurio_id: str, encoder_version: str = _DEFAULT_CONFUSION_ENCODER
) -> dict:
    """Return cartography details for a single coin, with enriched neighbors. eurio.db."""
    conn = _confusion_db_connect()
    row = None
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT zone, nearest_similarity, nearest_eurio_id, top_k_neighbors, "
                "computed_at FROM coin_confusion_map "
                "WHERE eurio_id = ? AND encoder_version = ?",
                (eurio_id, encoder_version),
            ).fetchone()
        except Exception:  # noqa: BLE001 — table absente (dev)
            row = None
    if row is None:
        if conn is not None:
            conn.close()
        raise HTTPException(
            status_code=404, detail="Pas de cartographie pour cette pièce"
        )
    try:
        try:
            neighbors = json.loads(row["top_k_neighbors"] or "[]")
        except json.JSONDecodeError:
            neighbors = []
        neighbor_ids = [n.get("eurio_id") for n in neighbors if n.get("eurio_id")]
        enriched = _confusion_enrich(conn, neighbor_ids)
        return {
            "eurio_id": eurio_id,
            "encoder_version": encoder_version,
            "zone": row["zone"],
            "nearest_eurio_id": row["nearest_eurio_id"],
            "nearest_similarity": row["nearest_similarity"],
            "computed_at": row["computed_at"],
            "top_k_neighbors": [
                {
                    "eurio_id": n.get("eurio_id"),
                    "similarity": n.get("similarity"),
                    "coin": enriched.get(n.get("eurio_id")),
                }
                for n in neighbors
            ],
        }
    finally:
        conn.close()


# ─── Numista Review ───

REVIEW_QUEUE_PATH = DATASETS_DIR / "numista_review_queue.json"
MANUAL_RESOLUTIONS_PATH = DATASETS_DIR / "numista_manual_resolutions.json"


class NumistaResolvePayload(BaseModel):
    numista_id: int
    eurio_id: str | None  # None = skip (no matching entry)


@app.get("/numista-review/queue")
def numista_review_queue() -> list[dict]:
    """Return the ambiguous review queue with current resolution status overlaid."""
    if not REVIEW_QUEUE_PATH.exists():
        return []
    queue = json.loads(REVIEW_QUEUE_PATH.read_text())
    resolutions: dict[str, dict] = {}
    if MANUAL_RESOLUTIONS_PATH.exists():
        resolutions = json.loads(MANUAL_RESOLUTIONS_PATH.read_text())
    for item in queue:
        item["resolution"] = resolutions.get(str(item["numista_id"]))
    return queue


@app.post("/numista-review/resolve")
def numista_review_resolve(payload: NumistaResolvePayload) -> dict:
    """Save a manual resolution (eurio_id=None means 'skip — no match')."""
    resolutions: dict[str, dict] = {}
    if MANUAL_RESOLUTIONS_PATH.exists():
        resolutions = json.loads(MANUAL_RESOLUTIONS_PATH.read_text())
    resolution = {
        "eurio_id": payload.eurio_id,
        "resolved_at": datetime.utcnow().isoformat(),
    }
    resolutions[str(payload.numista_id)] = resolution
    MANUAL_RESOLUTIONS_PATH.write_text(
        json.dumps(resolutions, indent=2, ensure_ascii=False)
    )
    return resolution


@app.get("/numista-review/stats")
def numista_review_stats() -> dict:
    """Return pending/resolved/skipped counts (used for the nav badge)."""
    if not REVIEW_QUEUE_PATH.exists():
        return {"total": 0, "resolved": 0, "pending": 0, "skipped": 0}
    queue = json.loads(REVIEW_QUEUE_PATH.read_text())
    resolutions: dict[str, dict] = {}
    if MANUAL_RESOLUTIONS_PATH.exists():
        resolutions = json.loads(MANUAL_RESOLUTIONS_PATH.read_text())
    total = len(queue)
    resolved = sum(
        1 for item in queue
        if resolutions.get(str(item["numista_id"]), {}).get("eurio_id") is not None
    )
    skipped = sum(
        1 for item in queue
        if str(item["numista_id"]) in resolutions
        and resolutions[str(item["numista_id"])]["eurio_id"] is None
    )
    pending = total - resolved - skipped
    return {"total": total, "resolved": resolved, "pending": pending, "skipped": skipped}


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
