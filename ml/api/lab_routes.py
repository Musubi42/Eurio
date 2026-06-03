"""FastAPI routes for the Lab subsystem (PRD Bloc 4).

Mounted from ``server.py``. CRUD on cohorts + iterations, plus the launch
endpoint that delegates to the IterationRunner, and aggregated read-only
views (trajectory, sensitivity).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from state import (
    ExperimentCohortRow,
    ExperimentIterationRow,
    IterationLiveTestRow,
    Store,
)

from . import coin_lookup
from .iteration_logic import compute_sensitivity
from .iteration_runner import IterationRunner

# Capture protocol — must mirror
# app-android/src/main/java/com/musubi/eurio/features/scan/CaptureProtocol.kt.
# When the Android list grows, update both sides in the same commit.
CAPTURE_STEPS: tuple[str, ...] = (
    "bright_plain",
    "dim_plain",
    "daylight_plain",
    "bright_textured",
    "tilt_plain",
    "close_plain",
)

# Filesystem layout (Statu quo: ml/datasets/<numista_id>/captures/<step>.jpg).
# When the migration to ml/datasets/coins/<numista_id>/ ships this constant
# is the single point to update.
_ML_DIR = Path(__file__).resolve().parent.parent
CAPTURES_BASE = _ML_DIR / "datasets"
AUGMENTATIONS_BASE = _ML_DIR / "datasets"


def _captures_dir_for(numista_id: int) -> Path:
    return CAPTURES_BASE / str(numista_id) / "captures"


def augmentations_dir_for(numista_id: int, iteration_id: str) -> Path:
    """Canonical on-disk location of an iteration's augmentations for a coin."""
    return AUGMENTATIONS_BASE / str(numista_id) / "augmentations" / iteration_id

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


class CohortAddCoinsPayload(BaseModel):
    eurio_ids: list[str]


class CohortClonePayload(BaseModel):
    name: str
    description: str | None = None


class CohortCsvOptionsPayload(BaseModel):
    pass


class CohortSyncPayload(BaseModel):
    pull_dir: str | None = None
    overwrite: bool = False


class IterationCreatePayload(BaseModel):
    name: str
    hypothesis: str | None = None
    parent_iteration_id: str | None = None
    recipe_id: str | None = None
    variant_count: int = 100
    training_config: dict = {}


class IterationPreviewPayload(BaseModel):
    recipe_id: str | None = None
    variant_count: int = 9


class IterationUpdatePayload(BaseModel):
    notes: str | None = None
    verdict_override: str | None = None
    # Mutable on `pending` iterations only — see `update_iteration` route.
    recipe_id: str | None = None
    variant_count: int | None = None


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


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_draft(cohort: ExperimentCohortRow) -> None:
    """409 if the cohort is already frozen — mutating eurio_ids/recipe is
    forbidden once a benchmark has been run against it (reproducibility)."""
    if cohort.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cohort {cohort.name!r} est en status '{cohort.status}'. "
                "Pour modifier ses pièces, clone-le."
            ),
        )


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
    if it.recipe_id:
        recipe = _get_store().get_recipe(it.recipe_id)
        d["recipe_name"] = recipe.name if recipe else None
    else:
        d["recipe_name"] = None
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
def list_cohorts(
    zone: str | None = None,
    status: str | None = None,
) -> list[dict]:
    _validate_zone(zone)
    if status is not None and status not in ("draft", "frozen"):
        raise HTTPException(status_code=400, detail=f"status invalide: {status!r}")
    return [
        _cohort_summary(c)
        for c in _get_store().list_cohorts(zone=zone, status=status)
    ]


@router.post("/cohorts")
def create_cohort(payload: CohortCreatePayload) -> dict:
    _validate_name(payload.name)
    _validate_zone(payload.zone)
    # de-dup + clean. Empty list is allowed: a cohort can be created from
    # the "create cohort" page without any coin and populated later by
    # selecting from /coins (the Cohort lab modal attaches to drafts).
    eurio_ids = sorted({eid.strip() for eid in payload.eurio_ids if eid and eid.strip()})
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


_OBVERSE_NAMES = ("obverse.jpg", "obverse.png")

# Seuil de sources RÉELLES distinctes (obverse Numista + crops eBay reviewés)
# sous lequel une classe est flaggée « trop pauvre » : l'augmentation seule
# gonflerait artificiellement (100 variants depuis 3 photos ≠ 100 vraies vues).
# Reco doctrine lab-streamline §B. En-dessous → aller chercher plus d'eBay.
_MIN_REAL_SOURCES = 15


def _has_obverse(numista_id: int | None) -> bool:
    if numista_id is None:
        return False
    coin_dir = CAPTURES_BASE / str(numista_id)
    return any((coin_dir / name).is_file() for name in _OBVERSE_NAMES)


def _drawer_state_c1(total_coins: int, missing_obverse: list[str]) -> str:
    if total_coins == 0:
        return "empty"
    if missing_obverse:
        return "partial"
    return "ready"


def _drawer_state_c2(
    total_coins: int, fully: int, partial: int, missing: int
) -> str:
    if total_coins == 0:
        return "empty"
    if fully == total_coins:
        return "ready"
    if fully == 0 and partial == 0:
        return "empty"
    return "partial"


@router.get("/cohorts/{cohort_id}/progress")
def cohort_progress(cohort_id: str) -> dict:
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    # ── C1 — selection ────────────────────────────────────────────────
    missing_obverse: list[str] = []
    for eid in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eid)
        if nid is None:
            logger.warning(
                "cohort %s: %s has no numista_id mapping", cohort.id, eid
            )
            missing_obverse.append(eid)
            continue
        if not _has_obverse(nid):
            missing_obverse.append(eid)
    total_coins = len(cohort.eurio_ids)
    c1 = {
        "state": _drawer_state_c1(total_coins, missing_obverse),
        "total_coins": total_coins,
        "missing_obverse": missing_obverse,
    }

    # ── C2 — captures ─────────────────────────────────────────────────
    expected_n = len(CAPTURE_STEPS)
    per_coin = [_coin_capture_status(eid) for eid in cohort.eurio_ids]
    fully = sum(1 for c in per_coin if c["num_files"] >= expected_n)
    partial_n = sum(1 for c in per_coin if 0 < c["num_files"] < expected_n)
    missing_n = sum(1 for c in per_coin if c["num_files"] == 0)
    per_coin_missing = [
        {"eurio_id": c["eurio_id"], "missing_steps": c["missing_steps"]}
        for c in per_coin
        if c["missing_steps"]
    ]
    c2 = {
        "state": _drawer_state_c2(total_coins, fully, partial_n, missing_n),
        "expected_per_coin": expected_n,
        "fully_captured": fully,
        "partial": partial_n,
        "missing": missing_n,
        "per_coin_missing": per_coin_missing,
    }

    return {"c1": c1, "c2": c2}


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


@router.post("/cohorts/{cohort_id}/coins")
def add_coins_to_cohort(
    cohort_id: str, payload: CohortAddCoinsPayload
) -> dict:
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    _require_draft(cohort)
    incoming = sorted({eid.strip() for eid in payload.eurio_ids if eid.strip()})
    if not incoming:
        raise HTTPException(status_code=400, detail="eurio_ids vide")
    merged = sorted(set(cohort.eurio_ids) | set(incoming))
    if merged == sorted(cohort.eurio_ids):
        # No-op: every requested coin was already in the cohort.
        return _cohort_summary(cohort)
    _get_store().update_cohort(cohort.id, eurio_ids=merged)
    updated = _get_store().get_cohort(cohort.id)
    return _cohort_summary(updated) if updated else cohort.to_dict()


@router.delete("/cohorts/{cohort_id}/coins/{eurio_id}")
def remove_coin_from_cohort(cohort_id: str, eurio_id: str) -> dict:
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    _require_draft(cohort)
    if eurio_id not in cohort.eurio_ids:
        raise HTTPException(
            status_code=404, detail=f"{eurio_id!r} pas dans le cohort"
        )
    remaining = [eid for eid in cohort.eurio_ids if eid != eurio_id]
    if not remaining:
        raise HTTPException(
            status_code=400,
            detail="Un cohort doit contenir au moins une pièce — supprime-le plutôt.",
        )
    _get_store().update_cohort(cohort.id, eurio_ids=remaining)
    updated = _get_store().get_cohort(cohort.id)
    return _cohort_summary(updated) if updated else cohort.to_dict()


@router.post("/cohorts/{cohort_id}/clone")
def clone_cohort(cohort_id: str, payload: CohortClonePayload) -> dict:
    src = _get_store().get_cohort(cohort_id)
    if src is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    _validate_name(payload.name)
    if _get_store().get_cohort(payload.name) is not None:
        raise HTTPException(
            status_code=409, detail=f"Cohort {payload.name!r} existe déjà"
        )
    new_id = uuid.uuid4().hex[:12]
    row = ExperimentCohortRow(
        id=new_id,
        name=payload.name,
        description=payload.description if payload.description is not None else src.description,
        zone=src.zone,
        eurio_ids=list(src.eurio_ids),
        status="draft",
        frozen_at=None,
    )
    _get_store().create_cohort(row)
    created = _get_store().get_cohort(new_id)
    return _cohort_summary(created) if created else row.to_dict()


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
    if not cohort.eurio_ids:
        raise HTTPException(
            status_code=400,
            detail="Cohort vide — ajoute des pièces depuis /coins avant de lancer une itération.",
        )
    if payload.variant_count <= 0 or payload.variant_count > 2000:
        raise HTTPException(
            status_code=400, detail="variant_count doit être entre 1 et 2000"
        )
    runner = _get_runner()
    try:
        row = runner.create_iteration(
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
    # Auto-freeze the cohort the first time an iteration is created.
    # Frozen cohorts can no longer mutate eurio_ids — guarantees that
    # every benchmark from now on is comparable. Recipe stays editable
    # at iteration level (PUT /iterations/{iid}).
    if cohort.status == "draft":
        _get_store().update_cohort(
            cohort.id, status="frozen", frozen_at=_iso_now()
        )
    return _iteration_with_run_metrics(row)


@router.post("/cohorts/{cohort_id}/iterations/{iteration_id}/launch-training")
def launch_iteration_training(cohort_id: str, iteration_id: str) -> dict:
    """Trigger the training → benchmark → verdict chain on a pending iteration.

    Pre-conditions enforced by :meth:`IterationRunner.launch_training`:
    iteration is in status ``pending`` AND has augmentations baked on disk
    AND the runner is free.
    """
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    iteration = _get_store().get_iteration(iteration_id)
    if iteration is None or iteration.cohort_id != cohort.id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    try:
        row = _get_runner().launch_training(iteration_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _iteration_with_run_metrics(row)


@router.post("/cohorts/{cohort_id}/iterations/{iteration_id}/launch-benchmark")
def launch_iteration_benchmark(cohort_id: str, iteration_id: str) -> dict:
    """(Re)run the studio benchmark on a 'completed' iteration.

    Used when the training succeeded but the chained benchmark crashed,
    or when the user wants a fresh measurement (new device captures, etc.)
    without re-training.

    Pre-conditions enforced by :meth:`IterationRunner.launch_benchmark`:
    iteration is in status ``completed`` (training+export OK), has a
    ``training_run_id``, and the runner is free.
    """
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    iteration = _get_store().get_iteration(iteration_id)
    if iteration is None or iteration.cohort_id != cohort.id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    try:
        row = _get_runner().launch_benchmark(iteration_id)
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


def _i1_state(recipe_id: str | None) -> str:
    return "ready" if recipe_id else "empty"


def _i2_state(total_baked: int, total_expected: int) -> str:
    if total_expected == 0 or total_baked == 0:
        return "empty"
    if total_baked >= total_expected:
        return "ready"
    return "partial"


def _i3_state(status: str) -> str:
    if status in ("training", "benchmarking"):
        return "running"
    if status == "completed":
        return "ready"
    if status == "failed":
        return "partial"
    return "empty"


def _i4_substate_studio(it: ExperimentIterationRow) -> dict:
    """State of the studio benchmark sub-tiroir.

    Decoupled from ``iteration.status``:
      - ``empty`` : no benchmark has been run yet (incl. iteration not yet
        trained, or iteration trained but benchmark never started).
      - ``running`` : iteration.status='benchmarking', or the benchmark
        row is in 'queued'/'running' state.
      - ``ready`` : benchmark row 'completed' with a non-null R@1.
      - ``partial`` : benchmark row 'failed' (training succeeded but
        benchmark didn't); ``error`` carries the message so the front
        can surface it.
    """
    if it.benchmark_run_id is None:
        # Distinguish "iteration still training" (status=training/benchmarking)
        # from "trained, benchmark never run yet" (status=completed without
        # benchmark_run_id) — both render as 'empty' but the front uses
        # iteration.status to decide whether to show a "Relancer" button.
        return {"state": "empty", "r_at_1": None, "error": None}

    bench = _get_store().get_benchmark_run(it.benchmark_run_id)
    if bench is None:
        return {
            "state": "partial",
            "r_at_1": None,
            "error": "benchmark row missing",
        }

    if bench.status == "completed" and bench.r_at_1 is not None:
        return {"state": "ready", "r_at_1": bench.r_at_1, "error": None}
    if bench.status == "failed":
        return {
            "state": "partial",
            "r_at_1": None,
            "error": bench.error or "benchmark failed",
        }
    # queued / running on the benchmark side, OR iteration toggled into
    # 'benchmarking' by the chain orchestrator.
    if it.status == "benchmarking" or bench.status in ("queued", "running"):
        return {"state": "running", "r_at_1": None, "error": None}
    return {"state": "partial", "r_at_1": None, "error": "état inconnu"}


def _i4_substate_aug_vs_real(iteration_id: str) -> dict:
    rows = _get_store().list_aug_vs_real(iteration_id)
    if not rows:
        return {"state": "empty", "computed_at": None, "mean_cosine": None}
    cosines = [r.cosine for r in rows if r.cosine is not None]
    mean = sum(cosines) / len(cosines) if cosines else None
    computed_at = max((r.computed_at for r in rows if r.computed_at), default=None)
    return {
        "state": "ready" if mean is not None else "partial",
        "computed_at": computed_at,
        "mean_cosine": mean,
    }


def _i4_substate_test_app(it: ExperimentIterationRow) -> dict:
    if it.status != "completed":
        return {"state": "empty", "model_ready": False, "tflite_present": _TFLITE_PATH.exists()}
    tflite_present = _TFLITE_PATH.exists()
    if not tflite_present:
        return {"state": "partial", "model_ready": False, "tflite_present": False}
    return {"state": "ready", "model_ready": True, "tflite_present": True}


def _i4_substate_live_tests(iteration_id: str) -> dict:
    rows = _get_store().list_live_tests(iteration_id)
    total = len(rows)
    if total == 0:
        return {"state": "empty", "total": 0, "recall_at_1": None}
    correct = sum(1 for r in rows if r.is_correct)
    return {
        "state": "ready",
        "total": total,
        "recall_at_1": correct / total if total else None,
    }


def _i4_aggregate(states: list[str]) -> str:
    n_ready = sum(1 for s in states if s == "ready")
    n_started = sum(1 for s in states if s != "empty")
    if n_started == 0:
        return "empty"
    if n_ready == len(states):
        return "ready"
    return "partial"


def _iteration_progress(it: ExperimentIterationRow) -> dict:
    # ── I1 ────────────────────────────────────────────────────────────
    recipe_name: str | None = None
    if it.recipe_id:
        recipe = _get_store().get_recipe(it.recipe_id)
        recipe_name = recipe.name if recipe else None
    i1 = {
        "state": _i1_state(it.recipe_id),
        "recipe_id": it.recipe_id,
        "recipe_name": recipe_name,
        "variant_count": it.variant_count,
    }

    # ── I2 ────────────────────────────────────────────────────────────
    from training.iteration_augmentations import list_for_iteration
    per_coin_aug = list_for_iteration(iteration_id=it.id, store=_get_store())
    cohort = _get_store().get_cohort(it.cohort_id)
    total_coins = len(cohort.eurio_ids) if cohort else 0
    target = max(int(it.variant_count), 1)
    total_expected = total_coins * target
    per_coin_i2: list[dict] = []
    total_baked = 0
    for c in per_coin_aug:
        baked = len(c.get("samples", []))
        total_baked += baked
        skipped: str | None = None
        if c.get("numista_id") is None:
            skipped = "no numista_id mapping"
        elif baked == 0 and not _has_obverse(c["numista_id"]):
            skipped = "no obverse image"
        per_coin_i2.append({
            "eurio_id": c["eurio_id"],
            "numista_id": c.get("numista_id"),
            "baked": baked,
            "expected": target,
            "skipped_reason": skipped,
        })
    i2 = {
        "state": _i2_state(total_baked, total_expected),
        "total_expected": total_expected,
        "total_baked": total_baked,
        "per_coin": per_coin_i2,
    }

    # ── I3 ────────────────────────────────────────────────────────────
    i3 = {
        "state": _i3_state(it.status),
        "status": it.status,
        "training_run_id": it.training_run_id,
        "benchmark_run_id": it.benchmark_run_id,
        "started_at": it.started_at,
        "finished_at": it.finished_at,
        "failure_reason": it.error if it.status == "failed" else None,
    }

    # ── I4 ────────────────────────────────────────────────────────────
    studio = _i4_substate_studio(it)
    avr = _i4_substate_aug_vs_real(it.id)
    test_app = _i4_substate_test_app(it)
    live = _i4_substate_live_tests(it.id)
    i4 = {
        "state": _i4_aggregate(
            [studio["state"], avr["state"], test_app["state"], live["state"]]
        ),
        "studio": studio,
        "aug_vs_real": avr,
        "test_app": test_app,
        "live_tests": live,
    }

    return {"i1": i1, "i2": i2, "i3": i3, "i4": i4}


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}/progress")
def iteration_progress(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    return _iteration_progress(it)


@router.post("/cohorts/{cohort_id}/iterations/{iteration_id}/bake")
def bake_iteration(cohort_id: str, iteration_id: str) -> dict:
    """Idempotent bake — fills missing samples without wiping the rest.

    Distinct from ``regenerate`` which clears + rebakes from scratch.
    """
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    if it.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Itération en status '{it.status}' — bake autorisé seulement "
                "sur 'pending'."
            ),
        )
    if not it.recipe_id:
        raise HTTPException(
            status_code=400,
            detail="Aucune recipe — sélectionne une recipe avant de baker.",
        )
    from training.iteration_augmentations import generate_for_iteration

    reports = generate_for_iteration(iteration_id=iteration_id, store=_get_store())
    total = sum(r.written for r in reports)
    return {
        "ok": True,
        "total_baked": total,
        "reports": [
            {
                "eurio_id": r.eurio_id,
                "numista_id": r.numista_id,
                "written": r.written,
                "sources_used": r.sources_used,
                "skipped_reason": r.skipped_reason,
            }
            for r in reports
        ],
    }


@router.put("/cohorts/{cohort_id}/iterations/{iteration_id}")
def update_iteration(
    cohort_id: str, iteration_id: str, payload: IterationUpdatePayload
) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    _validate_verdict(payload.verdict_override)

    patch: dict[str, object] = {}
    if payload.notes is not None:
        patch["notes"] = payload.notes
    if payload.verdict_override is not None:
        patch["verdict_override"] = payload.verdict_override

    # Recipe + variant_count are mutable only while the iteration is still
    # pending — once a training has run on a given (recipe, variant_count)
    # the row is the audit trail of what was actually trained, mutating it
    # would lie. If either field actually changes, we auto-invalidate the
    # baked augmentation samples on disk so the user must explicitly
    # regenerate before launching training (no stale samples mixed with
    # new recipe choices).
    recipe_changed = (
        payload.recipe_id is not None
        and payload.recipe_id != (it.recipe_id or "")
        and payload.recipe_id != it.recipe_id
    )
    variant_count_changed = (
        payload.variant_count is not None
        and payload.variant_count != it.variant_count
    )
    if recipe_changed or variant_count_changed:
        if it.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Iteration en status '{it.status}' — recipe/variant_count "
                    "ne sont modifiables que sur les itérations 'pending'."
                ),
            )
        if payload.recipe_id is not None:
            if payload.recipe_id and _get_store().get_recipe(payload.recipe_id) is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Recipe {payload.recipe_id!r} introuvable",
                )
            patch["recipe_id"] = payload.recipe_id or None
        if payload.variant_count is not None:
            if payload.variant_count <= 0 or payload.variant_count > 2000:
                raise HTTPException(
                    status_code=400,
                    detail="variant_count doit être entre 1 et 2000",
                )
            patch["variant_count"] = payload.variant_count
        # Wipe baked augmentations so the user re-bakes against the new config.
        from training.iteration_augmentations import clear_for_iteration
        clear_for_iteration(iteration_id=iteration_id, store=_get_store())

    if patch:
        _get_store().update_iteration(iteration_id, **patch)
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


# ─── Captures (cohort capture flow) ────────────────────────────────────────


def _coin_capture_status(eurio_id: str) -> dict:
    """FS-derived capture status for a single coin.

    Looks up the coin's numista_id (statu quo: captures live under
    ``datasets/<numista_id>/captures/``) and inspects the directory.
    """
    nid = coin_lookup.numista_id_for(eurio_id)
    expected = list(CAPTURE_STEPS)
    if nid is None:
        return {
            "eurio_id": eurio_id,
            "numista_id": None,
            "has_captures": False,
            "num_files": 0,
            "expected_steps": expected,
            "missing_steps": expected,
            "last_modified": None,
        }
    captures_dir = _captures_dir_for(nid)
    files: list[Path] = []
    if captures_dir.is_dir():
        files = sorted(captures_dir.glob("*.jpg"))
    present_steps = {f.stem for f in files}
    missing = [s for s in expected if s not in present_steps]
    last_mod: str | None = None
    if files:
        ts = max(f.stat().st_mtime for f in files)
        last_mod = (
            datetime.fromtimestamp(ts, tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    return {
        "eurio_id": eurio_id,
        "numista_id": nid,
        "has_captures": len(files) > 0,
        "num_files": len(files),
        "expected_steps": expected,
        "missing_steps": missing,
        "last_modified": last_mod,
    }


# Where generated cohort CSVs live on disk (gitignored). Same convention as
# the rest of ml/state/ — sits next to eurio.db.
COHORT_CSVS_DIR = _ML_DIR / "state" / "cohort_csvs"

# App-scoped path on the Android device. Pushing here works without any
# storage permission; mirrors DEBUG_DIR_DEVICE in app-android/Taskfile.yml.
DEVICE_CSV_PATH = (
    "/sdcard/Android/data/com.musubi.eurio/files/Documents/eurio_capture/cohort.csv"
)

# Repo root (debug_pull/ lives there).
_REPO_ROOT = _ML_DIR.parent
_DEBUG_PULL_ROOT = _REPO_ROOT / "debug_pull"


def _latest_pull_dir() -> Path | None:
    if not _DEBUG_PULL_ROOT.is_dir():
        return None
    candidates = [d for d in _DEBUG_PULL_ROOT.iterdir() if d.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.stat().st_mtime)


@router.get("/cohorts/{cohort_id}/captures/status")
def cohort_captures_status(cohort_id: str) -> dict:
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    per_coin = [_coin_capture_status(eid) for eid in cohort.eurio_ids]
    expected_n = len(CAPTURE_STEPS)
    fully = sum(1 for c in per_coin if c["num_files"] >= expected_n)
    partial = sum(
        1 for c in per_coin if 0 < c["num_files"] < expected_n
    )
    missing = sum(1 for c in per_coin if c["num_files"] == 0)
    return {
        "cohort_id": cohort.id,
        "total_coins": len(per_coin),
        "fully_captured": fully,
        "partial": partial,
        "missing": missing,
        "expected_steps": list(CAPTURE_STEPS),
        "per_coin": per_coin,
    }


@router.post("/cohorts/{cohort_id}/captures/csv")
def cohort_captures_csv(cohort_id: str) -> dict:
    """Generate the capture CSV (delta only) for the cohort.

    Writes ``ml/state/cohort_csvs/<cohort_name>.csv`` and also returns the
    raw content so the browser can offer a direct download.
    """
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    rows: list[tuple[str, int, str]] = []
    skipped_no_numista: list[str] = []
    skipped_complete = 0
    expected_n = len(CAPTURE_STEPS)
    for eid in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eid)
        if nid is None:
            skipped_no_numista.append(eid)
            continue
        captures_dir = _captures_dir_for(nid)
        present = (
            {f.stem for f in captures_dir.glob("*.jpg")}
            if captures_dir.is_dir()
            else set()
        )
        if all(s in present for s in CAPTURE_STEPS):
            skipped_complete += 1
            continue
        rows.append((eid, nid, coin_lookup.display_name_for(eid)))

    lines = ["eurio_id;numista_id;display_name"]
    for eid, nid, name in rows:
        # display_name may contain a literal `;` — strip to keep the format flat.
        clean = name.replace(";", ",")
        lines.append(f"{eid};{nid};{clean}")
    csv_content = "\n".join(lines) + "\n"

    COHORT_CSVS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = COHORT_CSVS_DIR / f"{cohort.name}.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    push_cmd = (
        f"adb push {csv_path.relative_to(_REPO_ROOT)} {DEVICE_CSV_PATH}"
    )
    pull_cmd = "go-task --taskfile app-android/Taskfile.yml pull-debug"

    return {
        "csv_path": str(csv_path.relative_to(_REPO_ROOT)),
        "csv_content": csv_content,
        "rows": len(rows),
        "skipped_no_numista": skipped_no_numista,
        "skipped_complete": skipped_complete,
        "device_target_path": DEVICE_CSV_PATH,
        "push_command": push_cmd,
        "pull_command": pull_cmd,
        "sync_endpoint_hint": f"POST /lab/cohorts/{cohort.id}/captures/sync",
    }


@router.post("/cohorts/{cohort_id}/captures/sync")
def cohort_captures_sync(cohort_id: str, payload: CohortSyncPayload) -> dict:
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    if payload.pull_dir:
        pull_dir = (_REPO_ROOT / payload.pull_dir).resolve()
        if not pull_dir.is_dir():
            raise HTTPException(
                status_code=400, detail=f"pull_dir introuvable: {payload.pull_dir}"
            )
    else:
        latest = _latest_pull_dir()
        if latest is None:
            raise HTTPException(
                status_code=400,
                detail="Aucun debug_pull/<ts>/ trouvé — fais d'abord `go-task --taskfile app-android/Taskfile.yml pull-debug`",
            )
        pull_dir = latest

    # Lazy import — keeps the route module importable even if cv2 is absent
    # in some thin environment.
    from scan.sync_eval_real import sync as run_sync

    try:
        report = run_sync(
            pull_dir,
            also_write_captures=True,
            overwrite=payload.overwrite,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return report.to_dict()


@router.get("/cohorts/{cohort_id}/ebay-status")
def cohort_ebay_status(cohort_id: str) -> dict:
    """Read-only eBay coverage for a cohort.

    Per coin: discovered listings + extracted crops + training-eligible crops,
    and whether the coin is eBay-scrapable (its (denom,country,year) group is in
    the commemorative discovery view). Plus the offline quota estimate for a
    cohort run. **No eBay API call** — the actual scrape is triggered manually
    via ``POST /sources/ebay/runs {cohort_id}`` (eBay passes are user-owned).
    """
    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    from sources.cohort_scope import cohort_ebay_groups
    from .sources_routes import check_ebay_quota

    groups, non_scrapable = cohort_ebay_groups(store, cohort_id)
    non_set = set(non_scrapable)
    conn = store._connection()  # noqa: SLF001

    per_coin: list[dict] = []
    for eid in cohort.eurio_ids:
        n_listings = conn.execute(
            "SELECT COUNT(*) FROM source_images "
            "WHERE source='ebay' AND target_eurio_id=?",
            (eid,),
        ).fetchone()[0]
        n_crops = conn.execute(
            "SELECT COUNT(*) FROM image_assets ia "
            "JOIN source_images si ON si.id = ia.source_image_id "
            "WHERE si.source='ebay' AND si.target_eurio_id=?",
            (eid,),
        ).fetchone()[0]
        # `train` = crops eBay éligibles pour CE coin selon le label TRANCHÉ en
        # review (ia.eurio_id), pas la cible de découverte — cohérent avec ce que
        # le bake pull réellement (iteration_augmentations._ebay_training_sources).
        n_training = conn.execute(
            "SELECT COUNT(*) FROM image_assets ia "
            "JOIN source_images si ON si.id = ia.source_image_id "
            "WHERE si.source='ebay' AND ia.eurio_id=? "
            "AND ia.training_eligible=1",
            (eid,),
        ).fetchone()[0]
        # Sources réelles distinctes = obverse Numista (0/1) + crops eBay
        # reviewés training-eligible. C'est ce compte (pas les augmentées) qui
        # décide si la classe a besoin de plus d'eBay (§C5).
        nid = coin_lookup.numista_id_for(eid)
        n_real = n_training + (1 if _has_obverse(nid) else 0)
        per_coin.append({
            "eurio_id": eid,
            "numista_id": nid,
            "scrapable": eid not in non_set,
            "n_listings": n_listings,
            "n_crops": n_crops,
            "n_training_eligible": n_training,
            "n_real_sources": n_real,
            "enough": n_real >= _MIN_REAL_SOURCES,
        })

    n_group_coins = sum(g.n_coins for g in groups)
    quota = check_ebay_quota(store, n_eurio_ids=n_group_coins) if groups else None

    return {
        "cohort_id": cohort.id,
        "scrapable_groups": [
            {
                "denomination": g.denomination, "country": g.country,
                "year": g.year, "n_coins": g.n_coins, "kind": g.kind,
            }
            for g in groups
        ],
        "non_scrapable": non_scrapable,
        "quota": quota,
        "per_coin": per_coin,
        "min_real_sources": _MIN_REAL_SOURCES,
    }


# ─── Funnel (§C3b — scrape eBay → review, scopé cohort) ─────────────────────
#
# Étape lab entre §C3 « Images eBay » et §C4 « Review crops » : montre, par
# cohort, comment les N listings scrapés se réduisent aux M crops qui entrent
# en review. Read-only sur eurio.db, run-agnostique (toutes passes), zéro appel
# eBay (passes user-owned). Deux mailles, dictées par la nature des données :
#
#   • per_coin (TAIL, post-attribution) — précis par coin. `source_images`
#     porte `target_eurio_id` = le coin ATTRIBUÉ (theme-match tranché), donc
#     listings retenus → crops → routing (route_decision/route_reason) → review
#     se ventilent proprement par pièce.
#
#   • head (PRÉ-attribution) — maille GROUPE `(pays, année, kind)`. Une
#     recherche commémo couvre toute une (pays, année). Le funnel de découverte
#     (N0 summaries → N3 kept) est keyé sur `discovery_searches.query_filters_json
#     .$.group` = la clé EXACTE {denom, pays, année} posée à la recherche
#     (fiable, même quand `target_eurio_id` est NULL). Les discards itemisés
#     (`discarded_listings.reason`) sont attribués via `target_eurio_id ∈ coins
#     du groupe` — seule clé honnête, car le `target` d'un discard n'est qu'un
#     PRIOR tagué à une sœur ; l'attribuer par pièce sur-compterait. Les drops à
#     `target_eurio_id` NULL ne sont pas rattachables proprement à un coin sans
#     heuristique → non itemisés ici, mais comptés implicitement dans l'écart
#     N0→N3 du funnel de découverte du groupe.


def _group_referential_coins(
    conn,
    *,
    denomination: float,
    country: str,
    year: int | None,
    kind: str,
) -> list[str]:
    """eurio_ids du référentiel couverts par la recherche eBay d'un groupe.

    Commémo = ``(denom, pays, année, is_commemorative=1)`` ; standard =
    ``(denom, pays, is_commemorative=0)`` toutes ères. Variantes
    (``canonical_eurio_id`` non-NULL) exclues — non scrapées (cf.
    ``cohort_ebay_groups``)."""
    if kind == "standard":
        rows = conn.execute(
            "SELECT eurio_id FROM coins WHERE face_value=? AND country=? "
            "AND is_commemorative=0 AND canonical_eurio_id IS NULL",
            (denomination, country),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT eurio_id FROM coins WHERE face_value=? AND country=? "
            "AND year=? AND is_commemorative=1 AND canonical_eurio_id IS NULL",
            (denomination, country, year),
        ).fetchall()
    return [r["eurio_id"] for r in rows]


def _discovery_funnel_for_group(
    conn, *, denomination: float, country: str, year: int | None,
) -> dict:
    """Agrège le funnel de découverte ``discovery_searches`` (N0→N3) d'un groupe.

    Maille fiable : ``discovery_searches.query_filters_json.$.group`` porte la
    clé EXACTE ``{denomination, country, year}`` posée à la recherche (cf.
    ``queries.build_group_query``). On la préfère à ``target_eurio_id`` (souvent
    NULL ou tagué à une seule sœur). ``year=None`` ⇒ groupe standard (recherche
    large sans millésime). Run-agnostique (toutes passes), comme le tail / §C3.
    N0..N3 peuvent être NULL (alias rétro-compat) → ``COALESCE`` à 0."""
    year_clause = (
        "json_extract(query_filters_json,'$.group.year') IS NULL"
        if year is None
        else "CAST(json_extract(query_filters_json,'$.group.year') AS INTEGER)=?"
    )
    params: list = [country, denomination]
    if year is not None:
        params.append(year)
    row = conn.execute(
        f"""
        SELECT COUNT(*)                          AS n_searches,
               COALESCE(SUM(n_summaries), 0)     AS n_summaries,
               COALESCE(SUM(n_after_groups), 0)  AS n_after_groups,
               COALESCE(SUM(n_raw_results), 0)   AS n_raw_results,
               COALESCE(SUM(n_kept_results), 0)  AS n_kept_results
          FROM discovery_searches
         WHERE source='ebay'
           AND json_extract(query_filters_json,'$.group.country')=?
           AND json_extract(query_filters_json,'$.group.denomination')=?
           AND {year_clause}
        """,
        params,
    ).fetchone()
    return {
        "n_searches": row["n_searches"] or 0,
        "n_summaries": row["n_summaries"] or 0,
        "n_after_groups": row["n_after_groups"] or 0,
        "n_raw_results": row["n_raw_results"] or 0,
        "n_kept_results": row["n_kept_results"] or 0,
    }


def _discarded_by_reason(
    conn, *, where_sql: str, params: list
) -> tuple[list[dict], int]:
    """``([{reason, n}], total)`` depuis ``discarded_listings``, trié desc."""
    rows = conn.execute(
        f"""
        SELECT reason, COUNT(*) AS n FROM discarded_listings
         WHERE source='ebay' AND {where_sql}
         GROUP BY reason ORDER BY n DESC
        """,
        params,
    ).fetchall()
    out = [{"reason": r["reason"], "n": r["n"]} for r in rows]
    return out, sum(r["n"] for r in rows)


def _coin_tail(conn, eurio_id: str) -> dict:
    """Tail post-attribution d'un coin : listings retenus ventilés par
    ``route_decision``/``route_reason``, crops, et run le plus récent."""
    breakdown = conn.execute(
        """
        SELECT route_decision, route_reason, COUNT(*) AS n
          FROM source_images
         WHERE source='ebay' AND target_eurio_id=?
         GROUP BY route_decision, route_reason
         ORDER BY n DESC
        """,
        (eurio_id,),
    ).fetchall()
    by_route = [
        {
            "route_decision": r["route_decision"],
            "route_reason": r["route_reason"],
            "n": r["n"],
        }
        for r in breakdown
    ]
    n_source_images = sum(r["n"] for r in breakdown)

    def _roll(pred) -> int:
        return sum(r["n"] for r in by_route if pred(r["route_decision"]))

    n_pending = _roll(lambda d: d == "pending")
    n_review_single = _roll(lambda d: d == "review_single")
    n_review_lot = _roll(lambda d: d == "review_lot")
    n_auto = _roll(lambda d: bool(d) and d.startswith("auto"))
    n_rejected = _roll(lambda d: bool(d) and d.startswith("rejected"))
    n_unrouted = _roll(lambda d: not d)

    n_crops = conn.execute(
        "SELECT COUNT(*) FROM image_assets ia "
        "JOIN source_images si ON si.id = ia.source_image_id "
        "WHERE si.source='ebay' AND si.target_eurio_id=?",
        (eurio_id,),
    ).fetchone()[0]

    # Runs ayant produit des source_images pour ce coin → run le plus récent
    # (deep-link bench) + flag multi-run (limite connue v1 : on linke le
    # dernier run, cf. handoff).
    run_rows = conn.execute(
        """
        SELECT run_id, COUNT(*) AS n, MAX(fetched_at) AS last_fetch
          FROM source_images
         WHERE source='ebay' AND target_eurio_id=? AND run_id IS NOT NULL
         GROUP BY run_id ORDER BY last_fetch DESC
        """,
        (eurio_id,),
    ).fetchall()
    latest_run_id = run_rows[0]["run_id"] if run_rows else None
    latest_run_started_at = None
    if latest_run_id is not None:
        r = conn.execute(
            "SELECT started_at FROM source_runs WHERE id=?", (latest_run_id,),
        ).fetchone()
        latest_run_started_at = r["started_at"] if r else None

    return {
        "n_source_images": n_source_images,
        "n_crops": n_crops,
        "by_route_decision": by_route,
        "n_pending": n_pending,
        "n_review_single": n_review_single,
        "n_review_lot": n_review_lot,
        "n_auto": n_auto,
        "n_rejected": n_rejected,
        "n_unrouted": n_unrouted,
        "latest_run_id": latest_run_id,
        "latest_run_started_at": latest_run_started_at,
        "n_runs": len(run_rows),
    }


def _cohort_funnel_status(store: Store, cohort_id: str) -> dict:
    """Cœur (testable offline) de ``GET /lab/cohorts/{id}/funnel-status``."""
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    from sources.cohort_scope import cohort_ebay_groups

    groups, non_scrapable = cohort_ebay_groups(store, cohort_id)
    non_set = set(non_scrapable)
    conn = store._connection()  # noqa: SLF001

    # ── per_coin (tail) ────────────────────────────────────────────────
    per_coin: list[dict] = []
    for eid in cohort.eurio_ids:
        tail = _coin_tail(conn, eid)
        per_coin.append({
            "eurio_id": eid,
            "numista_id": coin_lookup.numista_id_for(eid),
            "scrapable": eid not in non_set,
            **tail,
        })

    # Runs de la cohort = ceux ayant produit des source_images pour ses coins
    # (contexte du deep-link ; le head est attribué par groupe, pas par run).
    cohort_run_ids = sorted({
        r["run_id"]
        for eid in cohort.eurio_ids
        for r in conn.execute(
            "SELECT DISTINCT run_id FROM source_images "
            "WHERE source='ebay' AND target_eurio_id=? AND run_id IS NOT NULL",
            (eid,),
        ).fetchall()
    })

    # ── head.groups (maille (pays, année, kind)) ───────────────────────
    # Funnel de découverte (N0→N3) keyé sur `query_filters_json.group` —
    # fiable. Discards itemisés via `target_eurio_id ∈ coins du groupe` (seule
    # clé honnête : pas de sur-comptage des sœurs ; les drops à target NULL,
    # non rattachables sans heuristique, restent invisibles ici mais sont
    # comptés implicitement dans l'écart N0→N3 du funnel).
    head_groups: list[dict] = []
    for g in groups:
        coins = _group_referential_coins(
            conn,
            denomination=g.denomination,
            country=g.country,
            year=g.year,
            kind=g.kind,
        )
        disco = _discovery_funnel_for_group(
            conn, denomination=g.denomination, country=g.country, year=g.year,
        )
        if coins:
            ph = ",".join("?" * len(coins))
            discarded, n_disc = _discarded_by_reason(
                conn, where_sql=f"target_eurio_id IN ({ph})", params=list(coins),
            )
            n_kept_si = conn.execute(
                f"SELECT COUNT(*) FROM source_images "
                f"WHERE source='ebay' AND target_eurio_id IN ({ph})",
                list(coins),
            ).fetchone()[0]
        else:
            discarded, n_disc, n_kept_si = [], 0, 0
        head_groups.append({
            "country": g.country,
            "year": g.year,
            "denomination": g.denomination,
            "kind": g.kind,
            "n_referential_coins": len(coins),
            **disco,
            "n_attributed_source_images": n_kept_si,
            "n_discarded_attributed": n_disc,
            "discarded_by_reason": discarded,
        })

    return {
        "cohort_id": cohort.id,
        "per_coin": per_coin,
        "head": {
            "groups": head_groups,
            "run_ids": cohort_run_ids,
        },
        "non_scrapable": non_scrapable,
    }


@router.get("/cohorts/{cohort_id}/funnel-status")
def cohort_funnel_status(cohort_id: str) -> dict:
    """Funnel scrape eBay → review, scopé cohort (read-only, zéro appel eBay).

    Voir le bloc de doc ci-dessus pour la doctrine des deux mailles
    (per_coin tail précis vs head groupe). Alimente le tiroir §C3b et les
    deep-links vers le studio bench (``/bench/runs/<run>?eurio_id=<coin>``)."""
    return _cohort_funnel_status(_get_store(), cohort_id)


# ─── Augmentations (Sprint 1) ──────────────────────────────────────────────


@router.post("/cohorts/{cohort_id}/preview-iteration")
def preview_iteration(cohort_id: str, payload: IterationPreviewPayload) -> dict:
    """Create a ``pending`` iteration without launching training, then bake
    a small augmentations preview for the §3 Recipe section.

    Idempotent per (cohort, recipe): if a ``pending`` iteration already
    exists for the cohort+recipe combo, that one is returned instead of
    spawning a new draft. Frozen cohorts are still allowed — previewing
    doesn't mutate the cohort itself.
    """
    cohort = _get_store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    if not cohort.eurio_ids:
        raise HTTPException(
            status_code=400,
            detail="Cohort vide — impossible de prévisualiser sans pièces.",
        )
    if payload.variant_count < 1 or payload.variant_count > 64:
        raise HTTPException(
            status_code=400, detail="variant_count doit être entre 1 et 64"
        )
    if payload.recipe_id is not None and _get_store().get_recipe(payload.recipe_id) is None:
        raise HTTPException(status_code=400, detail="recipe_id introuvable")

    # Reuse a draft preview iteration if one already exists for this cohort
    # (avoids piling up draft rows). Match by name prefix + recipe + pending.
    existing = [
        it for it in _get_store().list_iterations(cohort_id=cohort.id, status="pending")
        if it.name.startswith("preview-") and it.recipe_id == payload.recipe_id
    ]

    import random as _random
    import uuid as _uuid

    if existing and existing[0].variant_count == payload.variant_count:
        it = existing[0]
    else:
        # Drop any stale preview rows (e.g. variant_count changed) so we
        # don't accumulate orphaned drafts. Recipe-bound previews are scoped
        # so deleting only matches preview-<recipe>* rows.
        for stale in existing:
            from training.iteration_augmentations import clear_for_iteration as _clear
            _clear(iteration_id=stale.id, store=_get_store())
            _get_store().delete_iteration(stale.id)

        seed = _random.randint(0, 2**31 - 1)
        iid = _uuid.uuid4().hex[:12]
        suffix = (payload.recipe_id or "default")[:8]
        row = ExperimentIterationRow(
            id=iid,
            cohort_id=cohort.id,
            name=f"preview-{suffix}",
            hypothesis=None,
            recipe_id=payload.recipe_id,
            variant_count=payload.variant_count,
            status="pending",
            verdict="pending",
            augmentations_seed=seed,
        )
        _get_store().create_iteration(row)
        it = _get_store().get_iteration(iid)

    # Bake (or refresh) the snapshot. Clear first so a recipe change
    # produces fresh samples rather than mixing old and new.
    from training.iteration_augmentations import (
        clear_for_iteration,
        generate_for_iteration,
    )

    clear_for_iteration(iteration_id=it.id, store=_get_store())
    reports = generate_for_iteration(iteration_id=it.id, store=_get_store())
    return {
        "iteration_id": it.id,
        "name": it.name,
        "augmentations_seed": it.augmentations_seed,
        "recipe_id": it.recipe_id,
        "variant_count": it.variant_count,
        "per_coin": [
            {
                "eurio_id": r.eurio_id,
                "numista_id": r.numista_id,
                "written": r.written,
                "skipped_reason": r.skipped_reason,
            }
            for r in reports
        ],
    }


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}/augmentations")
def list_iteration_augmentations(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    from training.iteration_augmentations import list_for_iteration

    per_coin = list_for_iteration(iteration_id=iteration_id, store=_get_store())
    total = sum(len(c["samples"]) for c in per_coin)
    return {
        "iteration_id": iteration_id,
        "augmentations_seed": it.augmentations_seed,
        "variant_count": it.variant_count,
        "total_samples": total,
        "per_coin": per_coin,
    }


@router.post("/cohorts/{cohort_id}/iterations/{iteration_id}/augmentations/regenerate")
def regenerate_iteration_augmentations(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    if it.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Itération en status '{it.status}' — la régénération n'est "
                "autorisée que pour les itérations 'pending'."
            ),
        )
    from training.iteration_augmentations import (
        clear_for_iteration,
        generate_for_iteration,
    )

    clear_for_iteration(iteration_id=iteration_id, store=_get_store())
    reports = generate_for_iteration(iteration_id=iteration_id, store=_get_store())
    return {
        "iteration_id": iteration_id,
        "regenerated": True,
        "per_coin": [
            {
                "eurio_id": r.eurio_id,
                "numista_id": r.numista_id,
                "written": r.written,
                "skipped_reason": r.skipped_reason,
            }
            for r in reports
        ],
    }


# ─── Aug ↔ réelles (Sprint 2 / D-006) ──────────────────────────────────────


def _aug_vs_real_payload(iteration_id: str, *, force: bool = False) -> dict:
    from . import distance_logic

    rows, dino_version = distance_logic.compute_aug_vs_real(
        iteration_id=iteration_id, store=_get_store(), force=force,
    )
    summary = distance_logic.summarize(rows)
    paths = distance_logic.list_paths_for_iteration(
        iteration_id=iteration_id, store=_get_store(),
    )
    paths_by_eid = {p["eurio_id"]: p for p in paths}
    rows_by_eid = {r.eurio_id: r for r in rows}

    it = _get_store().get_iteration(iteration_id)
    cohort = _get_store().get_cohort(it.cohort_id)
    per_coin: list[dict] = []
    for eurio_id in cohort.eurio_ids:
        p = paths_by_eid.get(
            eurio_id,
            {"numista_id": None, "real_samples": [], "aug_samples": []},
        )
        r = rows_by_eid.get(eurio_id)
        per_coin.append({
            "eurio_id": eurio_id,
            "numista_id": p.get("numista_id"),
            "num_real": len(p["real_samples"]),
            "num_aug": len(p["aug_samples"]),
            "cosine": r.cosine if r else None,
            "distance": (1.0 - r.cosine) if r else None,
            "real_samples": p["real_samples"],
            "aug_samples": p["aug_samples"],
            "skipped_reason": (
                "no captures" if not p["real_samples"]
                else "no augmentations" if not p["aug_samples"]
                else None
            ),
        })
    computed_at = max(
        (r.computed_at for r in rows if r.computed_at), default=None
    )
    return {
        "iteration_id": iteration_id,
        "dino_version": dino_version,
        "computed_at": computed_at,
        "summary": summary,
        "per_coin": per_coin,
    }


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}/aug-vs-real")
def get_aug_vs_real(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    return _aug_vs_real_payload(iteration_id, force=False)


@router.post("/cohorts/{cohort_id}/iterations/{iteration_id}/aug-vs-real/recompute")
def recompute_aug_vs_real(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    _get_store().clear_aug_vs_real(iteration_id)
    return _aug_vs_real_payload(iteration_id, force=True)


# ─── Stop training (Sprint 1 / D-009) ──────────────────────────────────────


@router.post("/cohorts/{cohort_id}/iterations/{iteration_id}/stop")
def stop_iteration(cohort_id: str, iteration_id: str) -> dict:
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    if it.status not in ("training", "benchmarking"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Itération en status '{it.status}' — stop n'est valide que pour "
                "training/benchmarking."
            ),
        )
    runner = _get_runner()
    outcome = runner.stop(iteration_id)
    return {"iteration_id": iteration_id, **outcome}


# ─── Runner status (for frontend polling) ──────────────────────────────────


@router.get("/runner/status")
def runner_status() -> dict:
    return {"busy": _get_runner().is_busy()}


@router.get("/runner/runtime-info")
def runner_runtime_info() -> dict:
    from training.runtime import detect, to_dict
    return to_dict(detect())


_TRAINING_PROGRESS_DIR = _ML_DIR / "state" / "training_progress"


@router.get("/runner/training-progress/{iteration_id}")
def runner_training_progress(iteration_id: str) -> dict:
    """Live training progress for a running iteration.

    Combines the on-disk JSON written by ``train_embedder.py`` (per-epoch loss,
    ETA, device) with the per-iteration log buffer (training stdout, TFLite
    export stdout, benchmark stdout — all phases). Front-end polls this every
    ~2s while ``iteration.status`` is ``training`` or ``benchmarking``.
    """
    fp = _TRAINING_PROGRESS_DIR / f"{iteration_id}.json"
    payload: dict
    if fp.exists():
        try:
            payload = json.loads(fp.read_text())
        except Exception:
            payload = {"error": "progress file unreadable"}
    else:
        payload = {
            "schema_version": 1,
            "iteration_id": iteration_id,
            "phase": "unknown",
        }
    log_tail: list[str] = []
    try:
        log_tail = _get_runner().tail_logs(iteration_id, n=500)
    except Exception:
        log_tail = []
    payload["log_tail"] = log_tail
    return payload


# ─── Cohort test app build info (Sprint 3) ─────────────────────────────────


_REPO_ROOT = _ML_DIR.parent
_TFLITE_PATH = _ML_DIR / "output" / "eurio_embedder_v1.tflite"


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}/test-app/build-info")
def cohort_test_build_info(cohort_id: str, iteration_id: str) -> dict:
    """Return the copy-paste command + readiness flags for the cohortTest APK.

    The frontend (`BuildTestAppSection.vue`) renders ``command`` verbatim
    in a ``<pre>`` block. ``model_ready`` gates the UI.
    """
    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    iteration = store.get_iteration(iteration_id)
    if iteration is None or iteration.cohort_id != cohort.id:
        raise HTTPException(status_code=404, detail="Itération introuvable")

    bundle_path = (
        _ML_DIR / "output" / f"cohort_test_{iteration.id}"
    ).relative_to(_REPO_ROOT).as_posix()

    if iteration.status != "completed":
        return {
            "cohort_name": cohort.name,
            "iteration_id": iteration.id,
            "iteration_name": iteration.name,
            "model_ready": False,
            "command": None,
            "bundle_path": bundle_path,
            "tflite_present": _TFLITE_PATH.exists(),
            "reason": (
                f"L'itération est en status '{iteration.status}'. "
                "Lance d'abord le training jusqu'à completion."
            ),
        }

    if not _TFLITE_PATH.exists():
        return {
            "cohort_name": cohort.name,
            "iteration_id": iteration.id,
            "iteration_name": iteration.name,
            "model_ready": False,
            "command": None,
            "bundle_path": bundle_path,
            "tflite_present": False,
            "reason": (
                f"{_TFLITE_PATH.relative_to(_REPO_ROOT)} manque — lance "
                "`python -m training.export_tflite` après le training."
            ),
        }

    command = (
        "go-task -t app-android/Taskfile.yml cohort-test:install "
        f"COHORT={cohort.name} ITERATION={iteration.id}"
    )
    return {
        "cohort_name": cohort.name,
        "iteration_id": iteration.id,
        "iteration_name": iteration.name,
        "model_ready": True,
        "command": command,
        "bundle_path": bundle_path,
        "tflite_present": True,
        "reason": None,
    }


# ─── Live tests (Sprint 4) ─────────────────────────────────────────────────
#
# Wire :
#   1. user runs the cohortTest APK, takes the 9 prescribed snaps
#   2. ``LiveTestLogger.kt`` writes
#      ``/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iid>.jsonl``
#   3. ``go-task -t app-android/Taskfile.yml cohort-test:pull-tests
#      ITERATION=<iid>`` pulls that file under
#      ``ml/state/live_test_logs/<iid>.jsonl`` then POSTs ``/sync``
#   4. ``GET .../live-tests`` exposes the matrix + studio↔live delta
#
# Schema versioning : ``schema_version`` is required on every line and rejected
# if missing. Keeps the JSONL forward-compat — Sprint 5+ may add fields and
# bump the version.

LIVE_TEST_LOGS_DIR = _ML_DIR / "state" / "live_test_logs"
LIVE_TEST_SCHEMA_VERSION = 1
LIVE_TEST_CONDITIONS = {"bright", "dim", "tilt"}


def _safe_repo_relative(p: Path) -> str:
    """Return ``p`` relative to the repo root if possible, else absolute.

    Tests patch ``LIVE_TEST_LOGS_DIR`` to a tmpdir that lives outside the
    repo, so ``relative_to`` would raise. The user-facing string is purely
    informational.
    """
    try:
        return p.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


class LiveTestsSyncPayload(BaseModel):
    """Body of ``POST /lab/cohorts/_/iterations/{iid}/live-tests/sync``.

    The path uses ``_`` because we look up the iteration by id alone — pulling
    the file on the client side already knows which iteration we mean.
    """

    pass


def _parse_live_test_line(
    raw: str, *, expected_iteration_id: str, line_idx: int,
) -> tuple[IterationLiveTestRow | None, str | None]:
    """Validate one JSONL line, return (row, error_msg).

    Skips empty lines silently. Otherwise returns either a parsed row or a
    human-readable validation error (caller surfaces these in the response so
    the user sees what went wrong without grepping logs).
    """
    if not raw.strip():
        return None, None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"line {line_idx}: invalid JSON ({exc.msg})"
    schema_version = obj.get("schema_version")
    if schema_version != LIVE_TEST_SCHEMA_VERSION:
        return None, (
            f"line {line_idx}: schema_version={schema_version!r} "
            f"!= {LIVE_TEST_SCHEMA_VERSION}"
        )
    iteration_id = obj.get("iteration_id")
    if iteration_id != expected_iteration_id:
        return None, (
            f"line {line_idx}: iteration_id={iteration_id!r} "
            f"!= {expected_iteration_id!r}"
        )
    test_idx = obj.get("test_idx")
    if not isinstance(test_idx, int) or test_idx < 1:
        return None, f"line {line_idx}: test_idx must be a positive int"
    expected_eid = obj.get("expected_eurio_id")
    if not isinstance(expected_eid, str) or not expected_eid:
        return None, f"line {line_idx}: expected_eurio_id required"
    condition = obj.get("condition")
    if condition not in LIVE_TEST_CONDITIONS:
        return None, (
            f"line {line_idx}: condition={condition!r} "
            f"not in {sorted(LIVE_TEST_CONDITIONS)}"
        )
    raw_top3 = obj.get("predicted_top3", [])
    if not isinstance(raw_top3, list):
        return None, f"line {line_idx}: predicted_top3 must be a list"
    top3: list[dict] = []
    for entry in raw_top3:
        if not isinstance(entry, dict):
            return None, f"line {line_idx}: predicted_top3 entry must be dict"
        eid = entry.get("eurio_id")
        sim = entry.get("similarity")
        if not isinstance(eid, str) or eid == "":
            return None, f"line {line_idx}: predicted_top3.eurio_id required"
        if not isinstance(sim, (int, float)):
            return None, f"line {line_idx}: predicted_top3.similarity must be a number"
        top3.append({"eurio_id": eid, "similarity": float(sim)})
    predicted_top1 = obj.get("predicted_top1")
    if predicted_top1 is not None and not isinstance(predicted_top1, str):
        return None, f"line {line_idx}: predicted_top1 must be str or null"
    similarity_top1 = obj.get("similarity_top1")
    if similarity_top1 is not None and not isinstance(similarity_top1, (int, float)):
        return None, f"line {line_idx}: similarity_top1 must be a number or null"
    is_correct = bool(obj.get("is_correct"))
    error = obj.get("error")
    if error is not None and not isinstance(error, str):
        return None, f"line {line_idx}: error must be str or null"
    ts = obj.get("ts")
    if not isinstance(ts, str) or not ts:
        return None, f"line {line_idx}: ts required"
    row = IterationLiveTestRow(
        iteration_id=iteration_id,
        test_idx=test_idx,
        expected_eurio_id=expected_eid,
        condition=condition,
        predicted_top3=top3,
        predicted_top1=predicted_top1,
        similarity_top1=(
            float(similarity_top1) if similarity_top1 is not None else None
        ),
        is_correct=is_correct,
        error=error,
        ts=ts,
    )
    return row, None


def _live_tests_summary(
    rows: list[IterationLiveTestRow], iteration: ExperimentIterationRow,
) -> dict:
    total = len(rows)
    correct = sum(1 for r in rows if r.is_correct)
    live_r1 = correct / total if total > 0 else None
    studio_r1: float | None = None
    if iteration.benchmark_run_id:
        bench = _get_store().get_benchmark_run(iteration.benchmark_run_id)
        if bench is not None:
            studio_r1 = bench.r_at_1
    delta = (
        live_r1 - studio_r1
        if (live_r1 is not None and studio_r1 is not None)
        else None
    )
    return {
        "total": total,
        "correct": correct,
        "recall_at_1": live_r1,
        "studio_r_at_1": studio_r1,
        "delta": delta,
    }


@router.post("/cohorts/_/iterations/{iteration_id}/live-tests/sync")
def sync_live_tests(
    iteration_id: str, payload: LiveTestsSyncPayload | None = None,
) -> dict:
    """Parse the pulled JSONL log and upsert into ``iteration_live_tests``.

    The cohort wildcard ``_`` is intentional — the iteration carries the
    cohort_id, so the task that pulls the JSONL doesn't need to thread it
    through. We still resolve+return the cohort name in the response so the
    front can update its cache key.
    """
    store = _get_store()
    iteration = store.get_iteration(iteration_id)
    if iteration is None:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    log_path = LIVE_TEST_LOGS_DIR / f"{iteration_id}.jsonl"
    if not log_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Log JSONL absent: {_safe_repo_relative(log_path)}. "
                "Lance d'abord `go-task -t app-android/Taskfile.yml "
                f"cohort-test:pull-tests ITERATION={iteration_id}`."
            ),
        )
    inserted = 0
    skipped_dupe = 0
    parse_errors: list[str] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line_idx, raw in enumerate(fh, start=1):
            row, err = _parse_live_test_line(
                raw, expected_iteration_id=iteration_id, line_idx=line_idx,
            )
            if err is not None:
                parse_errors.append(err)
                continue
            if row is None:
                continue
            if store.upsert_live_test(row):
                inserted += 1
            else:
                skipped_dupe += 1

    rows = store.list_live_tests(iteration_id)
    summary = _live_tests_summary(rows, iteration)
    return {
        "iteration_id": iteration_id,
        "cohort_id": iteration.cohort_id,
        "log_path": _safe_repo_relative(log_path),
        "inserted": inserted,
        "skipped_dupe": skipped_dupe,
        "parse_errors": parse_errors,
        "summary": summary,
    }


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}/live-tests")
def get_live_tests(cohort_id: str, iteration_id: str) -> dict:
    """Return all parsed live tests + studio↔live delta for §5 admin."""
    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    iteration = store.get_iteration(iteration_id)
    if iteration is None or iteration.cohort_id != cohort.id:
        raise HTTPException(status_code=404, detail="Itération introuvable")

    rows = store.list_live_tests(iteration_id)
    summary = _live_tests_summary(rows, iteration)

    # Group by (eurio_id, condition) for the matrix view. The bundle's
    # live_tests_manifest.json has the full prescription; we only need the
    # entries that survived sync here.
    matrix: dict[str, dict[str, dict]] = {}
    for r in rows:
        per_coin = matrix.setdefault(r.expected_eurio_id, {})
        per_coin[r.condition] = r.to_dict()

    # Manifest path is informational — the Vue side doesn't read it.
    log_path = LIVE_TEST_LOGS_DIR / f"{iteration_id}.jsonl"
    return {
        "iteration_id": iteration_id,
        "cohort_id": cohort.id,
        "cohort_name": cohort.name,
        "conditions": sorted(LIVE_TEST_CONDITIONS),
        "tests": [r.to_dict() for r in rows],
        "matrix": matrix,
        "summary": summary,
        "log_present": log_path.exists(),
        "log_path": _safe_repo_relative(log_path),
    }


# ─── Garbage collect (Sprint 5) ────────────────────────────────────────────


_OUTPUT_DIR = _ML_DIR / "output"


def _cohort_test_bundle_dir(iteration_id: str) -> Path:
    """Mirror the path produced by `cohort-test:bundle` (sprint 3)."""
    return _OUTPUT_DIR / f"cohort_test_{iteration_id}"


@router.delete("/cohorts/{cohort_id}/iterations/{iteration_id}/augmentations")
def purge_iteration_augmentations(cohort_id: str, iteration_id: str) -> dict:
    """Wipe baked augmentations for one iteration (per-numista_id dirs).

    Refuses on running iterations to avoid yanking the rug from under a
    training subprocess. The iteration row + benchmark history stay intact;
    only the augmentation samples + per-iteration symlink staging root go.
    """
    import shutil

    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    iteration = store.get_iteration(iteration_id)
    if iteration is None or iteration.cohort_id != cohort.id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    if iteration.status in ("training", "benchmarking"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Itération en status '{iteration.status}' — purger les "
                "augmentations casserait le subprocess en cours. Stop d'abord."
            ),
        )

    removed_dirs: list[str] = []
    skipped: list[str] = []
    for eurio_id in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eurio_id)
        if nid is None:
            skipped.append(f"{eurio_id} (numista_id missing)")
            continue
        path = augmentations_dir_for(nid, iteration_id)
        if path.exists():
            shutil.rmtree(path)
            removed_dirs.append(_safe_repo_relative(path))
    # The per-iteration symlink staging root used as ImageFolder dataset.
    staging_root = _ML_DIR / "datasets" / "iterations" / iteration_id
    staging_removed = False
    if staging_root.exists():
        shutil.rmtree(staging_root)
        staging_removed = True
    return {
        "iteration_id": iteration_id,
        "cohort_id": cohort.id,
        "removed_dirs": removed_dirs,
        "staging_root_removed": staging_removed,
        "skipped": skipped,
    }


@router.delete("/cohorts/{cohort_id}/iterations/{iteration_id}/test-bundle")
def purge_iteration_test_bundle(cohort_id: str, iteration_id: str) -> dict:
    """Wipe the cohortTest bundle dir produced by `cohort-test:bundle`.

    Doesn't touch the staged copy under
    `app-android/src/cohortTest/assets/cohort_bundle/` — that's overwritten
    on the next bundle anyway and is part of the build tree.
    """
    import shutil

    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    iteration = store.get_iteration(iteration_id)
    if iteration is None or iteration.cohort_id != cohort.id:
        raise HTTPException(status_code=404, detail="Itération introuvable")

    path = _cohort_test_bundle_dir(iteration_id)
    if not path.exists():
        return {
            "iteration_id": iteration_id,
            "cohort_id": cohort.id,
            "bundle_path": _safe_repo_relative(path),
            "removed": False,
        }
    shutil.rmtree(path)
    return {
        "iteration_id": iteration_id,
        "cohort_id": cohort.id,
        "bundle_path": _safe_repo_relative(path),
        "removed": True,
    }


# ─── Dashboard cross-cohort (Sprint 5) ─────────────────────────────────────


# OQ-2 — "difficult coin" = live R@1 mean under this threshold across at
# least DIFFICULT_MIN_ITERATIONS distinct iterations. Tweakable here.
_DIFFICULT_R1_THRESHOLD = 0.5
_DIFFICULT_MIN_ITERATIONS = 3
_DISTANCE_BINS = (
    (0.0, 0.5),
    (0.5, 0.7),
    (0.7, 0.85),
    (0.85, 0.95),
    (0.95, 1.0),
)


def _cosine_bin(cosine: float) -> str:
    for lo, hi in _DISTANCE_BINS:
        if cosine < hi or (hi == 1.0 and cosine <= 1.0):
            return f"{lo:.2f}-{hi:.2f}"
    return "out-of-range"


@router.get("/dashboard")
def dashboard() -> dict:
    """Cross-cohort aggregations. Should stay <1s even with 5+ cohorts."""
    store = _get_store()
    iterations = store.list_iterations()
    completed = [it for it in iterations if it.status == "completed"]

    # ── Top recipes (recipe_id × mean live R@1) ────────────────────────
    # We use *live* R@1 when available (prefers reality over studio); fall
    # back to studio R@1 otherwise so a recipe with no live tests yet still
    # shows up.
    by_recipe: dict[str, dict] = {}
    for it in completed:
        if it.recipe_id is None:
            continue
        live_rows = store.list_live_tests(it.id)
        live_r1: float | None = None
        if live_rows:
            live_r1 = sum(1 for r in live_rows if r.is_correct) / len(live_rows)
        studio_r1: float | None = None
        if it.benchmark_run_id:
            bench = store.get_benchmark_run(it.benchmark_run_id)
            if bench is not None:
                studio_r1 = bench.r_at_1
        bucket = by_recipe.setdefault(
            it.recipe_id,
            {"recipe_id": it.recipe_id, "live_r1s": [], "studio_r1s": [], "iteration_ids": []},
        )
        if live_r1 is not None:
            bucket["live_r1s"].append(live_r1)
        if studio_r1 is not None:
            bucket["studio_r1s"].append(studio_r1)
        bucket["iteration_ids"].append(it.id)

    top_recipes = []
    for recipe_id, bucket in by_recipe.items():
        recipe = store.get_recipe(recipe_id)
        live = bucket["live_r1s"]
        studio = bucket["studio_r1s"]
        top_recipes.append({
            "recipe_id": recipe_id,
            "recipe_name": recipe.name if recipe else None,
            "zone": recipe.zone if recipe else None,
            "n_iterations": len(bucket["iteration_ids"]),
            "mean_live_r_at_1": sum(live) / len(live) if live else None,
            "mean_studio_r_at_1": sum(studio) / len(studio) if studio else None,
            "iteration_ids": bucket["iteration_ids"],
        })
    # Sort: prefer live R@1 ranking, fallback to studio.
    top_recipes.sort(
        key=lambda r: (
            r["mean_live_r_at_1"] if r["mean_live_r_at_1"] is not None
            else (r["mean_studio_r_at_1"] if r["mean_studio_r_at_1"] is not None else -1.0)
        ),
        reverse=True,
    )

    # ── Difficult coins (live R@1 < threshold over ≥N iterations) ──────
    by_coin: dict[str, list[float]] = {}
    coin_iterations: dict[str, set[str]] = {}
    for it in completed:
        rows = store.list_live_tests(it.id)
        if not rows:
            continue
        per_coin: dict[str, list[bool]] = {}
        for r in rows:
            per_coin.setdefault(r.expected_eurio_id, []).append(r.is_correct)
        for eid, results in per_coin.items():
            r1 = sum(1 for ok in results if ok) / len(results)
            by_coin.setdefault(eid, []).append(r1)
            coin_iterations.setdefault(eid, set()).add(it.id)

    difficult_coins = []
    for eid, r1s in by_coin.items():
        n_iter = len(coin_iterations[eid])
        if n_iter < _DIFFICULT_MIN_ITERATIONS:
            continue
        mean_r1 = sum(r1s) / len(r1s)
        if mean_r1 >= _DIFFICULT_R1_THRESHOLD:
            continue
        difficult_coins.append({
            "eurio_id": eid,
            "mean_live_r_at_1": mean_r1,
            "n_iterations": n_iter,
            "iteration_ids": sorted(coin_iterations[eid]),
        })
    difficult_coins.sort(key=lambda c: c["mean_live_r_at_1"])

    # ── Distance distribution (cosine aug↔réel) ────────────────────────
    bins: dict[str, int] = {f"{lo:.2f}-{hi:.2f}": 0 for lo, hi in _DISTANCE_BINS}
    total = 0
    for it in completed:
        for row in store.list_aug_vs_real(it.id):
            if row.cosine is None:
                continue
            bins[_cosine_bin(row.cosine)] += 1
            total += 1

    return {
        "top_recipes": top_recipes,
        "difficult_coins": difficult_coins,
        "distance_distribution": {
            "total": total,
            "bins": [{"range": k, "count": v} for k, v in bins.items()],
            "threshold_difficult_r_at_1": _DIFFICULT_R1_THRESHOLD,
            "min_iterations_for_difficult": _DIFFICULT_MIN_ITERATIONS,
        },
        "totals": {
            "n_cohorts": len(store.list_cohorts()),
            "n_iterations": len(iterations),
            "n_completed": len(completed),
        },
    }
