"""FastAPI routes for the Lab subsystem (PRD Bloc 4).

Mounted from ``server.py``. CRUD on cohorts + iterations, plus the launch
endpoint that delegates to the IterationRunner, and aggregated read-only
views (trajectory, sensitivity).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from state import (
    ExperimentCohortRow,
    ExperimentIterationRow,
    Store,
)

from .iteration_logic import compute_sensitivity
from .iteration_runner import IterationRunner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lab", tags=["lab"])

_store: Store | None = None
_runner: IterationRunner | None = None


def bind(store: Store, runner: IterationRunner) -> None:
    global _store, _runner
    _store = store
    _runner = runner


def _get_store() -> Store:
    if _store is None:
        raise RuntimeError("lab_routes.bind() not called")
    return _store


def _get_runner() -> IterationRunner:
    if _runner is None:
        raise RuntimeError("lab_routes.bind() not called")
    return _runner


# ─── Payloads ──────────────────────────────────────────────────────────────


class CohortCreatePayload(BaseModel):
    name: str
    description: str | None = None
    zone: str | None = None
    eurio_ids: list[str]


class CohortUpdatePayload(BaseModel):
    name: str | None = None
    description: str | None = None
    zone: str | None = None


class IterationCreatePayload(BaseModel):
    name: str
    hypothesis: str | None = None
    parent_iteration_id: str | None = None
    recipe_id: str | None = None
    variant_count: int = 100
    training_config: dict = {}


class IterationUpdatePayload(BaseModel):
    notes: str | None = None
    verdict_override: str | None = None


# ─── Helpers ───────────────────────────────────────────────────────────────


_NAME_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate_name(name: str) -> None:
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


def _validate_verdict(v: str | None) -> None:
    if v is None:
        return
    allowed = {"pending", "baseline", "better", "worse", "mixed", "no_change"}
    if v not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"verdict_override doit être dans {sorted(allowed)}",
        )


def _cohort_summary(cohort: ExperimentCohortRow) -> dict:
    """Cohort row enriched with iteration stats (count + best R@1)."""
    d = cohort.to_dict()
    iterations = _get_store().list_iterations(cohort_id=cohort.id)
    d["iteration_count"] = len(iterations)
    best_r1: float | None = None
    for it in iterations:
        if it.benchmark_run_id is None:
            continue
        bench = _get_store().get_benchmark_run(it.benchmark_run_id)
        if bench and bench.r_at_1 is not None:
            if best_r1 is None or bench.r_at_1 > best_r1:
                best_r1 = bench.r_at_1
    d["best_r_at_1"] = best_r1
    return d


def _iteration_with_run_metrics(it: ExperimentIterationRow) -> dict:
    """Enrich an iteration row with a compact summary of its benchmark."""
    d = it.to_dict()
    bench_summary: dict | None = None
    if it.benchmark_run_id:
        bench = _get_store().get_benchmark_run(it.benchmark_run_id)
        if bench is not None:
            bench_summary = {
                "id": bench.id,
                "status": bench.status,
                "r_at_1": bench.r_at_1,
                "r_at_3": bench.r_at_3,
                "r_at_5": bench.r_at_5,
                "mean_spread": bench.mean_spread,
                "num_photos": bench.num_photos,
                "num_coins": bench.num_coins,
                "per_zone": bench.per_zone,
            }
    d["benchmark_summary"] = bench_summary
    training_summary: dict | None = None
    if it.training_run_id:
        run = _get_store().get_run(it.training_run_id)
        if run is not None:
            training_summary = {
                "id": run.id,
                "version": run.version,
                "status": run.status,
                "recall_at_1": run.recall_at_1,
                "error": run.error,
            }
    d["training_summary"] = training_summary
    return d


# ─── Cohorts ───────────────────────────────────────────────────────────────


@router.get("/cohorts")
def list_cohorts(zone: str | None = None) -> list[dict]:
    _validate_zone(zone)
    return [_cohort_summary(c) for c in _get_store().list_cohorts(zone=zone)]


@router.post("/cohorts")
def create_cohort(payload: CohortCreatePayload) -> dict:
    _validate_name(payload.name)
    _validate_zone(payload.zone)
    if not payload.eurio_ids:
        raise HTTPException(
            status_code=400, detail="eurio_ids ne peut pas être vide"
        )
    # de-dup + clean
    eurio_ids = sorted({eid.strip() for eid in payload.eurio_ids if eid and eid.strip()})
    if not eurio_ids:
        raise HTTPException(status_code=400, detail="eurio_ids invalides")
    if _get_store().get_cohort(payload.name) is not None:
        raise HTTPException(
            status_code=409, detail=f"Cohort {payload.name!r} existe déjà"
        )
    cohort_id = uuid.uuid4().hex[:12]
    row = ExperimentCohortRow(
        id=cohort_id,
        name=payload.name,
        description=payload.description,
        zone=payload.zone,
        eurio_ids=eurio_ids,
    )
    _get_store().create_cohort(row)
    created = _get_store().get_cohort(cohort_id)
    return _cohort_summary(created) if created else row.to_dict()


@router.get("/cohorts/{id_or_name}")
def get_cohort(id_or_name: str) -> dict:
    c = _get_store().get_cohort(id_or_name)
    if c is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    return _cohort_summary(c)


@router.put("/cohorts/{cohort_id}")
def update_cohort(cohort_id: str, payload: CohortUpdatePayload) -> dict:
    existing = _get_store().get_cohort(cohort_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    if payload.name is not None and payload.name != existing.name:
        _validate_name(payload.name)
        clash = _get_store().get_cohort(payload.name)
        if clash and clash.id != cohort_id:
            raise HTTPException(
                status_code=409, detail=f"name {payload.name!r} déjà pris"
            )
    if payload.zone is not None:
        _validate_zone(payload.zone)
    _get_store().update_cohort(
        cohort_id,
        name=payload.name,
        description=payload.description,
        zone=payload.zone,
    )
    updated = _get_store().get_cohort(cohort_id)
    return _cohort_summary(updated) if updated else {}


@router.delete("/cohorts/{cohort_id}")
def delete_cohort(cohort_id: str) -> dict:
    deleted = _get_store().delete_cohort(cohort_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    return {"deleted": True, "id": cohort_id}


# ─── Iterations ────────────────────────────────────────────────────────────


@router.get("/cohorts/{cohort_id}/iterations")
def list_iterations(cohort_id: str) -> list[dict]:
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    items = _get_store().list_iterations(cohort_id=cohort.id)
    return [_iteration_with_run_metrics(it) for it in items]


@router.post("/cohorts/{cohort_id}/iterations")
def create_iteration(cohort_id: str, payload: IterationCreatePayload) -> dict:
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name requis")
    if payload.variant_count <= 0 or payload.variant_count > 2000:
        raise HTTPException(
            status_code=400, detail="variant_count doit être entre 1 et 2000"
        )
    runner = _get_runner()
    if runner.is_busy():
        raise HTTPException(
            status_code=409,
            detail="Une itération est déjà en cours — une seule à la fois.",
        )
    try:
        row = runner.create_and_launch(
            cohort_id=cohort.id,
            name=payload.name.strip(),
            hypothesis=payload.hypothesis,
            parent_iteration_id=payload.parent_iteration_id,
            recipe_id=payload.recipe_id,
            variant_count=payload.variant_count,
            training_config=payload.training_config or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _iteration_with_run_metrics(row)


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}")
def get_iteration(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    return _iteration_with_run_metrics(it)


@router.put("/cohorts/{cohort_id}/iterations/{iteration_id}")
def update_iteration(
    cohort_id: str, iteration_id: str, payload: IterationUpdatePayload
) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    _validate_verdict(payload.verdict_override)
    _get_store().update_iteration(
        iteration_id,
        notes=payload.notes,
        verdict_override=payload.verdict_override,
    )
    updated = _get_store().get_iteration(iteration_id)
    return _iteration_with_run_metrics(updated) if updated else {}


@router.delete("/cohorts/{cohort_id}/iterations/{iteration_id}")
def delete_iteration(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    if it.status in ("training", "benchmarking"):
        raise HTTPException(
            status_code=409,
            detail="Impossible de supprimer une itération en cours.",
        )
    _get_store().delete_iteration(iteration_id)
    return {"deleted": True, "id": iteration_id}


# ─── Analytics ─────────────────────────────────────────────────────────────


@router.get("/cohorts/{cohort_id}/trajectory")
def cohort_trajectory(cohort_id: str) -> list[dict]:
    """Compact list of (iteration_id, name, r_at_1, verdict, date) for the chart."""
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    out: list[dict] = []
    for it in _get_store().list_iterations(cohort_id=cohort.id):
        r_at_1: float | None = None
        if it.benchmark_run_id:
            bench = _get_store().get_benchmark_run(it.benchmark_run_id)
            if bench is not None:
                r_at_1 = bench.r_at_1
        out.append({
            "iteration_id": it.id,
            "name": it.name,
            "r_at_1": r_at_1,
            "verdict": it.verdict_override or it.verdict,
            "status": it.status,
            "created_at": it.created_at,
        })
    return out


@router.get("/cohorts/{cohort_id}/sensitivity")
def cohort_sensitivity(cohort_id: str) -> list[dict]:
    """Parametric leverage — avg R@1 delta per changed input path."""
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    iterations = _get_store().list_iterations(cohort_id=cohort.id)
    by_id = {it.id: it for it in iterations}
    # Build (iter_inputs, parent_inputs, iter_metrics, parent_metrics) tuples.
    tuples: list[tuple[Any, Any, Any, Any]] = []
    runner = _get_runner()
    for it in iterations:
        if it.parent_iteration_id is None:
            continue
        parent = by_id.get(it.parent_iteration_id)
        if parent is None:
            continue
        iter_inputs = runner._snapshot_inputs(it)
        parent_inputs = runner._snapshot_inputs(parent)
        iter_metrics = None
        parent_metrics = None
        if it.benchmark_run_id:
            b = _get_store().get_benchmark_run(it.benchmark_run_id)
            if b is not None:
                iter_metrics = b.to_dict()
        if parent.benchmark_run_id:
            pb = _get_store().get_benchmark_run(parent.benchmark_run_id)
            if pb is not None:
                parent_metrics = pb.to_dict()
        tuples.append((iter_inputs, parent_inputs, iter_metrics, parent_metrics))
    return [e.to_dict() for e in compute_sensitivity(tuples)]


# ─── Runner status (for frontend polling) ──────────────────────────────────


@router.get("/runner/status")
def runner_status() -> dict:
    return {"busy": _get_runner().is_busy()}
