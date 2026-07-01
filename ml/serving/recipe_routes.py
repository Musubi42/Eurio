"""Light CRUD for augmentation recipes — canonical metadata (Model B).

A recipe is **pure metadata** (name, zone, JSON config): no pixels, no cv2/torch.
So it belongs on the *canonical* writer (``eurio-api`` on the VPS, single writer),
not on the heavy local ML API (``:8042``, whose DB is a throwaway replica). This
router therefore imports **only** the Store + the pure validator
(``shared.augmentation_recipe``) and is mounted **unconditionally** on the lean
image (``server_serve``) — a recipe created here lands in the canonical DB and is
recoverable from any compute machine (Mac ↔ PC) after ``ml:db:pull-replica``.

The *rendering* side (``POST /augmentation/preview`` + schema/overlays) stays in
``augmentation_routes`` on ``:8042`` — that one does need the heavy pipeline.

Mounted from ``server_serve.py`` (and any full app) via ``bind(store)``.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.augmentation_recipe import RecipeValidationError, validate_recipe
from store import AugmentationRecipeRow, Store

router = APIRouter(prefix="/recipes", tags=["recipes"])

_store: Store | None = None


def bind(store: Store) -> None:
    """Wire the shared Store. Called once by the mounting app at import."""
    global _store
    _store = store


def _get_store() -> Store:
    if _store is None:
        raise RuntimeError("recipe_routes.bind() not called")
    return _store


# ─── Payload models ─────────────────────────────────────────────────────────


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


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate_recipe_name(name: str) -> None:
    if not name or len(name) > 80:
        raise HTTPException(status_code=400, detail="name vide ou > 80 caractères")
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


# ─── CRUD ───────────────────────────────────────────────────────────────────


@router.get("")
def list_recipes(zone: str | None = None) -> list[dict]:
    _validate_zone(zone)
    return [r.to_dict() for r in _get_store().list_recipes(zone=zone)]


@router.get("/{id_or_name}")
def get_recipe(id_or_name: str) -> dict:
    recipe = _get_store().get_recipe(id_or_name)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recette introuvable")
    return recipe.to_dict()


@router.post("")
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


@router.put("/{recipe_id}")
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


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: str) -> dict:
    deleted = _get_store().delete_recipe(recipe_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recette introuvable")
    return {"deleted": True, "id": recipe_id}
