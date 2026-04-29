"""FastAPI routes for the Lab subsystem (PRD Bloc 4).

Mounted from ``server.py``. CRUD on cohorts + iterations, plus the launch
endpoint that delegates to the IterationRunner, and aggregated read-only
views (trajectory, sensitivity).
"""

from __future__ import annotations

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


def _captures_dir_for(numista_id: int) -> Path:
    return CAPTURES_BASE / str(numista_id) / "captures"

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
    # Auto-freeze the cohort the first time an iteration successfully launches.
    # Frozen cohorts can no longer mutate eurio_ids/recipe — guarantees that
    # every benchmark from now on is comparable.
    if cohort.status == "draft":
        _get_store().update_cohort(
            cohort.id, status="frozen", frozen_at=_iso_now()
        )
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
# the rest of ml/state/ — sits next to training.db.
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


# ─── Runner status (for frontend polling) ──────────────────────────────────


@router.get("/runner/status")
def runner_status() -> dict:
    return {"busy": _get_runner().is_busy()}
