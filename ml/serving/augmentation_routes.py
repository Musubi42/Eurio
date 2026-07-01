"""FastAPI routes for the augmentation subsystem (PRD Bloc 1).

Mounted from ``server.py``. Consumes the Store for recipe/run persistence
and the ``augmentations`` package for the pipeline itself.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field

from training.augmentations import (
    AugmentationPipeline,
    OVERLAY_CATEGORIES,
    RecipeValidationError,
    ZONE_RECIPES,
    list_layer_schemas,
    validate_recipe,
)
from training.augmentations.overlays import OVERLAYS_DIR
from store import AugmentationRunRow, Store

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).parent.parent
PREVIEW_ROOT = ML_DIR / "output" / "augmentation_previews"
PREVIEW_TTL_SECONDS = 24 * 3600
PREVIEW_COUNT_CAP = 64

router = APIRouter(prefix="/augmentation", tags=["augmentation"])

_store: Store | None = None


def bind(store: Store) -> None:
    """Called once by server.py at module import; wires the shared Store.

    Modèle B : plus de dépendance Supabase — les images source de l'aperçu
    sont résolues via MinIO (couche storage locale), comme le bake.
    """
    global _store
    _store = store


def _get_store() -> Store:
    if _store is None:
        raise RuntimeError("augmentation_routes.bind() not called")
    return _store


# ─── Payload models ─────────────────────────────────────────────────────────


class PreviewPayload(BaseModel):
    recipe: dict
    eurio_id: str | None = None
    design_group_id: str | None = None
    count: int = 16
    seed: int | None = None


# NB : le **CRUD** des recettes (list/get/create/update/delete) vit désormais
# dans le router LÉGER ``serving.recipe_routes`` (métadonnée pure, servie par le
# writer canonique eurio-api). Ce module ne garde que le rendu lourd
# (``/preview`` + ``/schema`` + ``/overlays``), qui a besoin du pipeline cv2.


# ─── Helpers ────────────────────────────────────────────────────────────────


def _raise_recipe_error(exc: RecipeValidationError) -> None:
    payload: dict = {"error": str(exc)}
    if exc.layer:
        payload["layer"] = exc.layer
    if exc.param:
        payload["param"] = exc.param
    raise HTTPException(status_code=400, detail=payload)


def _source_path_for_eurio(eurio_id: str, store: Store) -> Path | None:
    """Chemin LOCAL de l'image source d'aperçu pour un coin (Modèle B).

    Réutilise ``real_training_sources`` — la source de vérité PARTAGÉE avec le
    bake : avers canonique Numista en priorité, sinon premier crop eBay réel,
    sinon réf officielle BCE / EUR-Lex. Tous les chemins sont déjà résolus en
    local via MinIO (read-through ``local_path``). ``paths[0]`` respecte donc
    l'ordre de priorité du bake (obverse → eBay → réf). Retourne ``None`` si le
    coin n'a aucune source réelle.
    """
    from serving import coin_lookup
    from training.iteration_augmentations import real_training_sources

    nid = coin_lookup.numista_id_for(eurio_id)
    sources = real_training_sources(eurio_id, nid, store)
    return sources.paths[0] if sources.paths else None


def _resolve_source_path(
    *, eurio_id: str | None, design_group_id: str | None, store: Store
) -> Path:
    """Résout un chemin LOCAL d'image obverse réelle (Modèle B, sans Supabase).

    - ``eurio_id`` : source réelle du coin via ``real_training_sources`` (MinIO).
    - ``design_group_id`` : on choisit un membre représentatif du groupe — le
      premier (par année puis eurio_id) qui possède une source réelle, comme le
      faisait le resolver d'aperçu et comme le bake étend les classes à leurs
      membres.
    """
    if not eurio_id and not design_group_id:
        raise HTTPException(
            status_code=400,
            detail="Provide either eurio_id or design_group_id",
        )

    if eurio_id:
        path = _source_path_for_eurio(eurio_id, store)
        if path is None:
            raise HTTPException(
                status_code=404,
                detail=f"Coin {eurio_id} sans source réelle "
                "(avers Numista, crop eBay ni réf BCE/EUR-Lex)",
            )
        return path

    # Chemin design_group_id : membre représentatif (premier avec une source).
    conn = store._connection()  # noqa: SLF001
    members = conn.execute(
        "SELECT eurio_id, year FROM coins WHERE design_group_id = ? "
        "ORDER BY COALESCE(year, 9999), eurio_id",
        (design_group_id,),
    ).fetchall()
    if not members:
        raise HTTPException(
            status_code=404,
            detail=f"design_group {design_group_id} sans membres",
        )
    for row in members:
        path = _source_path_for_eurio(row[0], store)
        if path is not None:
            return path
    raise HTTPException(
        status_code=404,
        detail=f"design_group {design_group_id} sans source réelle",
    )


def _sanitize_run_id(run_id: str) -> None:
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="run_id invalide")


# ─── Cleanup ────────────────────────────────────────────────────────────────


def cleanup_expired_previews() -> int:
    """Delete preview run_dirs older than TTL + their SQLite rows.

    Called once at FastAPI startup. Safe to call at any time — idempotent.
    """
    removed = 0
    store = _get_store()
    for run in store.prune_aug_runs_older_than(seconds=PREVIEW_TTL_SECONDS):
        d = Path(run.output_dir)
        if not d.is_absolute():
            d = ML_DIR / run.output_dir
        if d.exists() and d.is_dir():
            try:
                shutil.rmtree(d)
            except OSError as exc:
                logger.warning("Failed to rm preview dir %s: %s", d, exc)
                continue
        removed += 1

    # Also sweep orphan dirs on disk with no SQLite row (belt & suspenders).
    if PREVIEW_ROOT.exists():
        cutoff = time.time() - PREVIEW_TTL_SECONDS
        for entry in PREVIEW_ROOT.iterdir():
            if not entry.is_dir():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue
    return removed


# ─── Routes ─────────────────────────────────────────────────────────────────


@router.get("/schema")
def get_schema() -> dict:
    """Introspection payload for the Studio — source of truth for sliders."""
    return {
        "layers": list_layer_schemas(),
        "zones": ["green", "orange", "red"],
        "default_recipe": ZONE_RECIPES["orange"],
        "limits": {
            "preview_count_max": PREVIEW_COUNT_CAP,
            "preview_ttl_seconds": PREVIEW_TTL_SECONDS,
        },
    }


@router.get("/overlays")
def list_overlays() -> dict:
    """List overlay textures available per category (relative to OVERLAYS_DIR)."""
    out: dict[str, list[str]] = {}
    for cat in OVERLAY_CATEGORIES:
        cat_dir = OVERLAYS_DIR / cat
        if not cat_dir.exists():
            out[cat] = []
            continue
        paths: list[str] = []
        for pattern in ("*.png", "*.jpg", "*.jpeg"):
            paths.extend(str(p.relative_to(OVERLAYS_DIR)) for p in cat_dir.glob(pattern))
        out[cat] = sorted(paths)
    return out


@router.post("/preview")
def post_preview(payload: PreviewPayload) -> dict:
    store = _get_store()

    if payload.count <= 0:
        raise HTTPException(status_code=400, detail="count must be > 0")
    if payload.count > PREVIEW_COUNT_CAP:
        raise HTTPException(
            status_code=400,
            detail=f"count > {PREVIEW_COUNT_CAP} (cap API)",
        )

    try:
        validate_recipe(payload.recipe)
    except RecipeValidationError as exc:
        _raise_recipe_error(exc)

    source_path = _resolve_source_path(
        eurio_id=payload.eurio_id,
        design_group_id=payload.design_group_id,
        store=store,
    )

    run_id = uuid.uuid4().hex[:12]
    run_dir = PREVIEW_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    store.create_aug_run(
        AugmentationRunRow(
            id=run_id,
            recipe_id=None,
            eurio_id=payload.eurio_id,
            design_group_id=payload.design_group_id,
            count=payload.count,
            seed=payload.seed,
            output_dir=str(run_dir.relative_to(ML_DIR)),
            status="running",
        )
    )

    start = time.time()
    try:
        base_img = Image.open(source_path).convert("RGB")
        pipeline = AugmentationPipeline(payload.recipe, seed=payload.seed)
        variations = pipeline.generate(base_img, count=payload.count)
        for idx, img in enumerate(variations):
            img.save(run_dir / f"{idx:02d}.png", "PNG")
    except HTTPException:
        store.update_aug_run(run_id, status="failed", error="source_unavailable")
        raise
    except Exception as exc:  # noqa: BLE001
        store.update_aug_run(run_id, status="failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    duration_ms = int((time.time() - start) * 1000)
    store.update_aug_run(run_id, status="completed", duration_ms=duration_ms)

    return {
        "run_id": run_id,
        "images": [
            {
                "index": i,
                "url": f"/augmentation/preview/images/{run_id}/{i}",
            }
            for i in range(payload.count)
        ],
        "duration_ms": duration_ms,
        "seed": payload.seed,
    }


@router.get("/preview/images/{run_id}/{index}")
def get_preview_image(run_id: str, index: int):
    _sanitize_run_id(run_id)
    run_dir = PREVIEW_ROOT / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Preview run introuvable")
    path = run_dir / f"{index:02d}.png"
    resolved = path.resolve()
    if not str(resolved).startswith(str(run_dir.resolve())):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Image non trouvée")
    return FileResponse(resolved, media_type="image/png")
