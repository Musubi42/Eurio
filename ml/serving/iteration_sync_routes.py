"""Itérations canoniques — lecture + upsert (R3, Model B).

Une itération lab se **calcule** localement (bake/train, cv2/torch) mais son
**état** (métadonnée + métriques dénormalisées) doit être canonique pour être vu
partout (Mac ↔ PC). Ce router LÉGER (Store + validateur, aucun import lourd) est
monté sur le canonique `eurio-api` :

- ``GET /iterations?cohort_id=`` (scope ``lab:read``) → liste toutes machines.
- ``GET /iterations/{id}``       (scope ``lab:read``) → détail métadonnée.
- ``PUT /iterations/{id}``       (scope ``ingest:write``) → **upsert** d'un
  snapshot poussé par une machine de calcul (last-writer-wins par itération).
- ``DELETE /iterations/{id}``    (scope ``ingest:write``) → delete propagé par
  le lab local (idempotent, F09).

Il ne remplace PAS les routes lab lourdes (`/lab/.../bake`, `launch-training`) qui
restent sur le ML local :8042. Le canonique ne stocke que l'état, jamais le calcul.
Cf. docs/work-in-progress/model-b/R3-iterations-canonical.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from serving.auth_principal import require_scope
from store import ExperimentIterationRow, Store

router = APIRouter(prefix="/iterations", tags=["iterations"])

_store: Store | None = None


def bind(store: Store) -> None:
    """Wire the shared Store. Called once by the mounting app at import."""
    global _store
    _store = store


def _get_store() -> Store:
    if _store is None:
        raise RuntimeError("iteration_sync_routes.bind() not called")
    return _store


class IterationSnapshot(BaseModel):
    """Snapshot poussé par une machine de calcul (miroir de ``to_dict``).

    ``id`` vient du path (ignoré ici s'il est fourni). Champs permissifs : le
    canonique stocke ce que la source envoie, il ne recalcule rien.
    """

    cohort_id: str
    name: str
    status: str
    parent_iteration_id: str | None = None
    hypothesis: str | None = None
    recipe_id: str | None = None
    variant_count: int = 100
    training_config: dict = Field(default_factory=dict)
    training_run_id: str | None = None
    benchmark_run_id: str | None = None
    verdict: str | None = None
    verdict_override: str | None = None
    delta_vs_parent: dict = Field(default_factory=dict)
    diff_from_parent: dict = Field(default_factory=dict)
    notes: str | None = None
    error: str | None = None
    augmentations_seed: int | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_on: str | None = None
    summary: dict | None = None


# Scopes par-route, explicites et testables en isolation : lecture = `lab:read`,
# upsert (push d'une machine de calcul) = `ingest:write`.
_READ = [Depends(require_scope("lab:read"))]
_WRITE = [Depends(require_scope("ingest:write"))]


@router.get("", dependencies=_READ)
def list_iterations(cohort_id: str | None = None, status: str | None = None) -> list[dict]:
    rows = _get_store().list_iterations(cohort_id=cohort_id, status=status)
    return [r.to_dict() for r in rows]


@router.get("/{iteration_id}", dependencies=_READ)
def get_iteration(iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    return it.to_dict()


@router.put("/{iteration_id}", dependencies=_WRITE)
def upsert_iteration(iteration_id: str, payload: IterationSnapshot) -> dict:
    store = _get_store()
    data = payload.model_dump()

    # Garde FK lisible (F09) : la cohorte est le PARENT (FK `cohort_id`,
    # `foreign_keys=ON`) et n'est jamais nullable — sans elle l'upsert
    # exploserait en 500 FK opaque. On échoue tôt avec la marche à suivre.
    exists = store._connection().execute(  # noqa: SLF001
        "SELECT 1 FROM experiment_cohorts WHERE id = ?", (data["cohort_id"],)
    ).fetchone()
    if exists is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"cohorte {data['cohort_id']!r} absente du canonique — "
                "pousse la cohorte d'abord (POST /ingest/cohort)"
            ),
        )

    # Tolérance FK : une itération poussée référence des rows qui ne vivent pas
    # sur le canonique — recette/parent legacy, et SURTOUT les runs
    # (training_run_id / benchmark_run_id) qui restent locaux (MVP R3 =
    # métadonnée seule, les tables lourdes ne sont jamais poussées). On null les
    # références non résolues pour ne pas violer la FK (`foreign_keys=ON`). Pas de
    # perte : `summary` porte déjà recipe_name + les métriques bench/training.
    if data.get("recipe_id") and store.get_recipe(data["recipe_id"]) is None:
        data["recipe_id"] = None
    if data.get("parent_iteration_id") and store.get_iteration(data["parent_iteration_id"]) is None:
        data["parent_iteration_id"] = None
    if data.get("training_run_id") and store.get_run(data["training_run_id"]) is None:
        data["training_run_id"] = None
    if data.get("benchmark_run_id") and store.get_benchmark_run(data["benchmark_run_id"]) is None:
        data["benchmark_run_id"] = None

    row = ExperimentIterationRow(id=iteration_id, **data)
    store.upsert_iteration(row)
    saved = store.get_iteration(iteration_id)
    return saved.to_dict() if saved else row.to_dict()


@router.delete("/{iteration_id}", dependencies=_WRITE)
def delete_iteration(iteration_id: str) -> dict:
    """Supprime une itération du canonique (delete propagé par le lab local,
    F09). Idempotent : un id déjà absent → ``op='absent'``, pas de 404 (un
    retry après succès réussit)."""
    deleted = _get_store().delete_iteration(iteration_id)
    return {"id": iteration_id, "op": "deleted" if deleted else "absent"}
