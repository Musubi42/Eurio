"""FastAPI routes for the augmentation subsystem (PRD Bloc 1).

Mounted from ``server.py``. Consumes the Store for recipe/run persistence
and the ``augmentations`` package for the pipeline itself.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field

from augmentations import (
    AugmentationPipeline,
    OVERLAY_CATEGORIES,
    RecipeValidationError,
    ZONE_RECIPES,
    list_layer_schemas,
    validate_recipe,
)
from augmentations.overlays import OVERLAYS_DIR
from state import AugmentationRecipeRow, AugmentationRunRow, Store

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).parent.parent
PREVIEW_ROOT = ML_DIR / "output" / "augmentation_previews"
PREVIEW_TTL_SECONDS = 24 * 3600
PREVIEW_COUNT_CAP = 64
IMAGE_CACHE_DIR = ML_DIR / "cache" / "augmentation_sources"

router = APIRouter(prefix="/augmentation", tags=["augmentation"])

_store: Store | None = None
_supabase_fetcher: Any = None


def bind(store: Store, supabase_fetcher: Any) -> None:
    """Called once by server.py at module import; wires the shared Store
    + a callable that returns a SupabaseClient on demand.
    """
    global _store, _supabase_fetcher
    _store = store
    _supabase_fetcher = supabase_fetcher


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


class RecipePayload(BaseModel):
    name: str
    zone: str | None = None
    config: dict
    based_on_recipe_id: str | None = None


class RecipeUpdatePayload(BaseModel):
    name: str | None = None
    zone: str | None = None
    config: dict | None = None


# ─── Helpers ────────────────────────────────────────────────────────────────


_NAME_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate_recipe_name(name: str) -> None:
    if not name or len(name) > 80:
        raise HTTPException(
            status_code=400, detail="name vide ou > 80 caractères"
        )
    if not _NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="name must be lowercase kebab-case (a-z, 0-9, -)",
        )


def _validate_zone(zone: str | None) -> None:
    if zone is not None and zone not in ("green", "orange", "red"):
        raise HTTPException(status_code=400, detail=f"zone invalide: {zone!r}")


def _raise_recipe_error(exc: RecipeValidationError) -> None:
    payload: dict = {"error": str(exc)}
    if exc.layer:
        payload["layer"] = exc.layer
    if exc.param:
        payload["param"] = exc.param
    raise HTTPException(status_code=400, detail=payload)


def _cache_path_for_url(url: str) -> Path:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    suffix = Path(url.split("?", 1)[0]).suffix.lower() or ".img"
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".img"
    return IMAGE_CACHE_DIR / f"{digest}{suffix}"


def _download_image(url: str) -> Path:
    path = _cache_path_for_url(url)
    if path.exists() and path.stat().st_size > 0:
        return path
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def _extract_obverse_url(images: object) -> str | None:
    if not images:
        return None
    if isinstance(images, dict):
        return images.get("obverse") or images.get("obverse_url")
    if isinstance(images, list):
        obv = next((i for i in images if i.get("role") == "obverse"), None)
        if obv:
            return obv.get("url")
    return None


def _resolve_source_url(
    *, eurio_id: str | None, design_group_id: str | None
) -> str:
    if not eurio_id and not design_group_id:
        raise HTTPException(
            status_code=400,
            detail="Provide either eurio_id or design_group_id",
        )
    if _supabase_fetcher is None:
        raise HTTPException(status_code=503, detail="Supabase non disponible")
    sb = _supabase_fetcher()
    if eurio_id:
        rows = sb.query(
            "coins",
            select="eurio_id,images",
            params={"eurio_id": f"eq.{eurio_id}"},
        )
        if not rows:
            raise HTTPException(
                status_code=404, detail=f"Coin eurio_id={eurio_id} introuvable"
            )
        url = _extract_obverse_url(rows[0].get("images"))
        if not url:
            raise HTTPException(
                status_code=404,
                detail=f"Coin {eurio_id} sans image obverse",
            )
        return url

    # design_group_id path
    groups = sb.query(
        "design_groups",
        select="id,shared_obverse_url",
        params={"id": f"eq.{design_group_id}"},
    )
    if groups and groups[0].get("shared_obverse_url"):
        return groups[0]["shared_obverse_url"]
    members = sb.query(
        "coins",
        select="eurio_id,year,images",
        params={"design_group_id": f"eq.{design_group_id}"},
    )
    if not members:
        raise HTTPException(
            status_code=404,
            detail=f"design_group {design_group_id} sans membres",
        )
    for m in sorted(members, key=lambda c: (c.get("year") or 9999, c["eurio_id"])):
        u = _extract_obverse_url(m.get("images"))
        if u:
            return u
    raise HTTPException(
        status_code=404,
        detail=f"design_group {design_group_id} sans image obverse",
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

    source_url = _resolve_source_url(
        eurio_id=payload.eurio_id,
        design_group_id=payload.design_group_id,
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
        source_path = _download_image(source_url)
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


# ─── Recipes CRUD ───────────────────────────────────────────────────────────


@router.get("/recipes")
def list_recipes(zone: str | None = None) -> list[dict]:
    _validate_zone(zone)
    return [r.to_dict() for r in _get_store().list_recipes(zone=zone)]


@router.get("/recipes/{id_or_name}")
def get_recipe(id_or_name: str) -> dict:
    recipe = _get_store().get_recipe(id_or_name)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recette introuvable")
    return recipe.to_dict()


@router.post("/recipes")
def create_recipe(payload: RecipePayload) -> dict:
    store = _get_store()
    _validate_recipe_name(payload.name)
    _validate_zone(payload.zone)

    try:
        validate_recipe(payload.config)
    except RecipeValidationError as exc:
        _raise_recipe_error(exc)

    if store.get_recipe(payload.name) is not None:
        raise HTTPException(
            status_code=409, detail=f"Recette {payload.name!r} existe déjà"
        )
    if payload.based_on_recipe_id and store.get_recipe(payload.based_on_recipe_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"based_on_recipe_id {payload.based_on_recipe_id!r} introuvable",
        )

    recipe_id = uuid.uuid4().hex[:12]
    row = AugmentationRecipeRow(
        id=recipe_id,
        name=payload.name,
        zone=payload.zone,
        config=payload.config,
        based_on_recipe_id=payload.based_on_recipe_id,
    )
    store.create_recipe(row)
    created = store.get_recipe(recipe_id)
    return created.to_dict() if created else row.to_dict()


@router.put("/recipes/{recipe_id}")
def update_recipe(recipe_id: str, payload: RecipeUpdatePayload) -> dict:
    store = _get_store()
    existing = store.get_recipe(recipe_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Recette introuvable")

    if payload.name is not None and payload.name != existing.name:
        _validate_recipe_name(payload.name)
        clash = store.get_recipe(payload.name)
        if clash and clash.id != recipe_id:
            raise HTTPException(
                status_code=409, detail=f"name {payload.name!r} déjà pris"
            )

    if payload.zone is not None:
        _validate_zone(payload.zone)

    if payload.config is not None:
        try:
            validate_recipe(payload.config)
        except RecipeValidationError as exc:
            _raise_recipe_error(exc)

    store.update_recipe(
        recipe_id,
        name=payload.name,
        zone=payload.zone,
        config=payload.config,
    )
    updated = store.get_recipe(recipe_id)
    return updated.to_dict() if updated else {}


@router.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: str) -> dict:
    deleted = _get_store().delete_recipe(recipe_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recette introuvable")
    return {"deleted": True, "id": recipe_id}
