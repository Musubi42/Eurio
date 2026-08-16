"""FastAPI routes for the Lab subsystem (PRD Bloc 4).

Mounted from ``server.py``. CRUD on cohorts + iterations, plus the launch
endpoint that delegates to the IterationRunner, and aggregated read-only
views (trajectory, sensitivity).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from serving import lab_writes as _lab_writes

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from store import (
    ExperimentCohortRow,
    ExperimentIterationRow,
    IterationLiveTestRow,
    Store,
    cohort_job_set_pid,
    cohort_job_start,
    emit_field_event,
    latest_training_scan,
    local_state_store,
    training_scan_dismiss_intruder,
    training_scan_results,
    training_scan_set_pid,
    training_scan_start,
)
from store.decisions import (
    DecisionError,
    apply_accept_training,
    apply_reassign,
    apply_reopen_review,
    apply_set_training_eligible,
)
from store.funnel import list_training_crops
from serving.decision_models import (
    AcceptTrainingResult,
    ReassignAssetPayload,
    ReopenReviewResult,
    SetTrainingEligiblePayload,
)

from training.foundation.enrichment import (
    CANONICAL_REF_SOURCES,
    MIN_REAL as _ENRICH_MIN_REAL,
    TRAINING_TARGET as _ENRICH_TARGET,
    projection as _enrich_projection,
)
import jobs
from sources.ebay.standards import design_group_lot_scope
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
_local_store: Store | None = None


def bind(store: Store, runner: IterationRunner, local_store: Store | None = None) -> None:
    """Câble le store canonique + le runner. ``local_store`` = store d'état local
    (bookkeeping cohort_jobs/scans, writable, cf. ``local_state_store()``) ; None →
    singleton par défaut sur ``eurio.local.db``. Les tests passent un store tmp
    dédié pour rester hermétiques."""
    global _store, _runner, _local_store
    _store = store
    _runner = runner
    _local_store = local_store or local_state_store()


def _get_store() -> Store:
    if _store is None:
        raise RuntimeError("lab_routes.bind() not called")
    return _store


def _get_local_store() -> Store:
    """Store d'état local (bookkeeping). Writable même sous le flip readonly —
    les writes cohort_jobs/scans y vont, jamais dans la réplique canonique."""
    if _local_store is None:
        raise RuntimeError("lab_routes.bind() not called")
    return _local_store


def _get_runner() -> IterationRunner:
    if _runner is None:
        raise RuntimeError("lab_routes.bind() not called")
    return _runner


# Les écritures de dimensions lab (cohortes, itérations) passent toutes par
# `serving/lab_writes.py` — seul endroit qui décide où va une écriture selon
# que le SQLite local est un canonique ou une réplique read-only (Direction A,
# C5). L'ancien `_push_cohort_canonical` (push F09 best-effort APRÈS écriture
# locale) y a été absorbé : sous le flip, une écriture locale n'est plus
# possible, et le canonique n'est plus une destination secondaire mais LA
# destination.


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


def _require_classes_ready(cohort: ExperimentCohortRow) -> None:
    """409 si une classe de la cohorte n'est pas prête à entraîner (preflight).

    Bloque AVANT l'auto-freeze irréversible : pas de source réelle (réf morte),
    sous le plancher dur ``m_per_class``, OU trop pauvre en eBay réel (warn).
    L'admin doit enrichir (scrape eBay) / reviewer avant de lancer. Source de
    vérité = ``training/foundation/preflight`` (même calcul que le run)."""
    from store import ClassRef
    from training.eval.class_resolver import build_resolver
    from training.foundation.preflight import preflight_classes

    store = _get_store()
    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, unresolved = resolver.classes_for_eurio_ids(cohort.eurio_ids)
    refs = [ClassRef(d.class_id, d.class_kind) for d in descriptors]
    report = preflight_classes(refs, store, resolver=resolver)
    not_ready = report.blocked + report.warned
    if not unresolved and not not_ready:
        return
    parts = [f"{c.class_id} ({c.reason or c.status})" for c in not_ready]
    if unresolved:
        parts.append(f"absents du catalogue : {', '.join(unresolved)}")
    raise HTTPException(
        status_code=409,
        detail={
            "message": (
                f"{len(not_ready)} classe(s) pas prête(s) à entraîner — enrichis "
                "(scrape eBay) ou review avant de lancer une itération."
            ),
            "not_ready": [c.to_dict() for c in not_ready],
            "unresolved": unresolved,
            "preflight": report.to_dict(),
        },
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
    """Enrich an iteration row with a compact summary of its benchmark.

    Le résumé (recette + benchmark + training) est construit par la source unique
    ``iteration_summary.build_iteration_summary`` — la MÊME que celle poussée au
    canonique dans ``summary_json`` (R3), pour une parité chiffres locaux ↔ canonique.
    """
    from serving.iteration_summary import build_iteration_summary

    return {**it.to_dict(), **build_iteration_summary(_get_store(), it)}


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
    _lab_writes.write_cohort(_get_store(), row)
    created = _get_store().get_cohort(cohort_id)
    return _cohort_summary(created) if created else row.to_dict()


@router.get("/cohorts/{id_or_name}")
def get_cohort(id_or_name: str) -> dict:
    c = _get_store().get_cohort(id_or_name)
    if c is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    return _cohort_summary(c)


_OBVERSE_NAMES = ("obverse.jpg", "obverse.png")

# Cible et plancher = source de vérité UNIQUE (foundation/enrichment.py), partagée
# avec le bake (training/iteration_augmentations.py). La projection n'est plus un
# ×10 codé en dur mais un facteur dynamique ceil(100/seed) → voir _enrich_projection.
TRAINING_TARGET = _ENRICH_TARGET
MIN_REAL = _ENRICH_MIN_REAL
# Alias legacy conservé pour ne pas casser les usages existants (n_real_sources,
# colonne `enough`) le temps d'un éventuel nettoyage ultérieur.
_MIN_REAL_SOURCES = MIN_REAL


def _has_obverse(numista_id: int | None) -> bool:
    if numista_id is None:
        return False
    coin_dir = CAPTURES_BASE / str(numista_id)
    return any((coin_dir / name).is_file() for name in _OBVERSE_NAMES)


def _has_canonical(conn: sqlite3.Connection, eurio_id: str, source: str) -> bool:
    """Retourne True si ``coin_canonical_images`` contient une obverse pour
    (eurio_id, source).  Utilisé pour calculer n_numista_ref et n_bce_ref."""
    row = conn.execute(
        "SELECT 1 FROM coin_canonical_images "
        "WHERE eurio_id=? AND source=? AND role='obverse' LIMIT 1",
        (eurio_id, source),
    ).fetchone()
    return row is not None


def _count_canonical_refs(conn: sqlite3.Connection, eurio_id: str) -> int:
    """Réfs canoniques officielles (BCE / EUR-Lex JO) RÉELLEMENT présentes sur
    disque — compté à l'identique du bake (``iteration_augmentations
    ._canonical_ref_images``) pour que l'affichage et l'augmentation effective
    partagent le même « seed ». ``local_path`` est relatif à la racine du repo."""
    placeholders = ",".join("?" * len(CANONICAL_REF_SOURCES))
    rows = conn.execute(
        f"""
        SELECT local_path FROM coin_canonical_images
         WHERE eurio_id=? AND role='obverse'
           AND source IN ({placeholders})
           AND local_path IS NOT NULL AND local_path != ''
        """,
        (eurio_id, *CANONICAL_REF_SOURCES),
    ).fetchall()
    repo_root = _ML_DIR.parent
    return sum(1 for r in rows if (repo_root / r[0]).exists())


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
    merged = replace(
        existing,
        name=payload.name if payload.name is not None else existing.name,
        description=(
            payload.description if payload.description is not None else existing.description
        ),
        zone=payload.zone if payload.zone is not None else existing.zone,
    )
    _lab_writes.write_cohort(_get_store(), merged)
    updated = _get_store().get_cohort(cohort_id)
    return _cohort_summary(updated) if updated else merged.to_dict()


@router.delete("/cohorts/{cohort_id}")
def delete_cohort(cohort_id: str) -> dict:
    if not _lab_writes.delete_cohort(_get_store(), cohort_id):
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
    _lab_writes.write_cohort(_get_store(), replace(cohort, eurio_ids=merged))
    updated = _get_store().get_cohort(cohort.id)
    return _cohort_summary(updated) if updated else cohort.to_dict()


@router.get("/cohorts/{cohort_id}/training-readiness")
def cohort_training_readiness(cohort_id: str) -> dict:
    """Lecture seule : la cohorte est-elle prête à entraîner ?

    Le staging est IMPLICITE — une itération entraîne les pièces de la cohorte
    (cohort.eurio_ids). Cet endpoint résout ces eurio_ids → classes
    ``COALESCE(design_group_id, eurio_id)`` (dédup) et fait tourner le preflight,
    sans rien écrire. Le front s'en sert pour bloquer « Nouvelle itération » et
    montrer les classes pas prêtes (le hard-block vit dans ``create_iteration``).
    """
    from store import ClassRef
    from training.eval.class_resolver import build_resolver
    from training.foundation.preflight import preflight_classes

    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, unresolved = resolver.classes_for_eurio_ids(cohort.eurio_ids)
    refs = [ClassRef(d.class_id, d.class_kind) for d in descriptors]
    report = preflight_classes(refs, store, resolver=resolver)
    not_ready = report.blocked + report.warned
    return {
        "cohort_id": cohort.id,
        "ready": not unresolved and not not_ready,
        "n_classes": len(refs),
        "unresolved": unresolved,
        "preflight": report.to_dict(),
    }


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
    _lab_writes.write_cohort(_get_store(), replace(cohort, eurio_ids=remaining))
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
    _lab_writes.write_cohort(_get_store(), row)  # le CLONE ; la source n'a pas bougé
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

    # Garde-fou : une itération entraîne IMPLICITEMENT les pièces de la cohorte
    # (cohort.eurio_ids). On refuse de figer la cohorte + lancer si une classe est
    # trop pauvre — chaque classe doit avoir assez de sources RÉELLES (≥ plancher
    # eBay), sinon l'augmentation gonfle du vide. Réutilise le preflight (source de
    # vérité unique). Bloque sur block ET warn (un run cohorte se veut propre).
    _require_classes_ready(cohort)

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
        _lab_writes.write_cohort(
            _get_store(),
            replace(cohort, status="frozen", frozen_at=_iso_now()),
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
    # Maille design_group (cf. _live_tests_summary) — pas le strict eurio_id.
    correct = sum(1 for r in rows if r.is_correct_eq)
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


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}/sources")
def iteration_sources(cohort_id: str, iteration_id: str) -> dict:
    """Provenance des images d'entraînement, agrégée sur le bake set design_group.

    Réponse à la demande (pas pollée) : compte les sources RÉELLES — avers Numista
    (FS), crops eBay reviewés (`training_eligible`), réfs officielles BCE/EUR-Lex —
    sur l'union des membres des groupes de la cohorte (mêmes sources que le bake et
    le préflight). Donne à l'admin « d'où viennent les images » avant/pendant un run.
    """
    it = _get_store().get_iteration(iteration_id)
    if it is None or it.cohort_id != cohort_id:
        raise HTTPException(status_code=404, detail="Itération introuvable")
    cohort = _get_store().get_cohort(it.cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohorte introuvable")
    from training.iteration_augmentations import real_training_sources
    from training.eval.class_resolver import build_resolver
    from serving import coin_lookup
    store = _get_store()
    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, _ = resolver.classes_for_eurio_ids(cohort.eurio_ids)
    bake_ids = {eid for d in descriptors for eid in d.eurio_ids}
    numista = ebay = ref = 0
    for eid in bake_ids:
        nid = coin_lookup.numista_id_for(eid)
        src = real_training_sources(eid, nid, store)
        numista += src.n_numista
        ebay += src.n_ebay
        ref += src.n_ref
    return {
        "numista_obverse": numista,
        "ebay_crops": ebay,
        "bce_refs": ref,
        "total": numista + ebay + ref,
        "n_classes": len(descriptors),
        "n_coins": len(bake_ids),
    }


@router.post("/cohorts/{cohort_id}/iterations/{iteration_id}/bake", status_code=202)
def bake_iteration(cohort_id: str, iteration_id: str) -> dict:
    """Idempotent bake (sans clear) — DÉTACHÉ. Remplit les samples manquants sans
    effacer le reste. Distinct de ``regenerate`` qui clear + rebuild. 202 → le
    front poll ``…/augmentations/job`` puis re-fetch la galerie."""
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
    bake = _launch_aug_bake(iteration_id, clear=False)
    return {"iteration_id": iteration_id, "job_id": bake["job_id"], "status": "baking"}


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
        # Le patch est appliqué sur la row lue, puis écrite par le writer qui
        # fait autorité (canonique sous flip C5, local sinon + push F09).
        _lab_writes.write_iteration(_get_store(), replace(it, **patch))
    updated = _get_store().get_iteration(iteration_id)
    return _iteration_with_run_metrics(updated) if updated else {}


def _purge_iteration_artifacts(iteration_id: str) -> None:
    """Supprime les artefacts disque (régénérables) d'une itération — l'« événement
    de fin ». Couvre : ``lab/iterations/<iid>`` (modèle/tflite/embeddings/previews/
    manifests), ``datasets/iterations/<iid>`` (staging) et ``datasets/*/augmentations/
    <iid>`` (bakes par-coin, set design_group inclus → glob, pas juste la cohorte).
    Best-effort : un échec de rmtree ne bloque pas la suppression DB."""
    import shutil
    from .iteration_runner import (
        DATASETS_DIR,
        ITERATION_TRAIN_ROOTS,
        LAB_ITERATIONS_DIR,
    )
    for path in (LAB_ITERATIONS_DIR / iteration_id, ITERATION_TRAIN_ROOTS / iteration_id):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    for aug in DATASETS_DIR.glob(f"*/augmentations/{iteration_id}"):
        shutil.rmtree(aug, ignore_errors=True)


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
    # Le delete part au writer qui fait autorité (canonique sous flip C5, local
    # sinon + push F09). Les artefacts disque restent locaux : ils ne vivent que
    # sur la machine de compute, le canonique ne porte que la métadonnée.
    _lab_writes.delete_iteration(_get_store(), iteration_id)
    _purge_iteration_artifacts(iteration_id)
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
    from vision.sync_eval_real import sync as run_sync

    try:
        report = run_sync(
            pull_dir,
            also_write_captures=True,
            overwrite=payload.overwrite,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return report.to_dict()


# ─── eBay — sourcing & funnel (§C3, scopé cohort) ───────────────────────────
#
# Tiroir §C3 fusionné (sourcing + funnel) : montre, par cohort, comment les N
# listings scrapés se réduisent aux M crops qui entrent en review, PLUS le bout
# « sourcing » (train-eligible, sources réelles, quota scrape). Read-only sur
# eurio.db, run-agnostique (toutes passes), zéro appel eBay (passes user-owned).
# Deux mailles, dictées par la nature des données :
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
    ``route_decision``/``route_reason``, crops, et run le plus récent.

    Scope : un STANDARD est scrapé par recherche LARGE pays ; ses crops
    atterrissent en ``target_eurio_id`` NULL (ambigu) ou sur le prior de l'ère
    (1er millésime) — un scope ``target_eurio_id = eurio_id`` exact afficherait
    ~0 alors que des dizaines sont à trancher. On scope donc à l'**ère**
    (``design_group``) via ``design_group_lot_scope`` : membres de l'ère (prior
    inclus) ∪ pool ambigu du pays — IDENTIQUE au scope de la review lot
    (``review_queue_routes.list_lots?design_group=…``) → le cockpit et la review
    affichent le MÊME nombre, sans la pollution des commémos mal-routées (qui
    portent leur propre ``target_eurio_id``). Les commémos gardent le scope
    ``target_eurio_id`` exact.
    """
    std = conn.execute(
        "SELECT country, design_group_id FROM coins "
        "WHERE eurio_id=? AND is_commemorative=0",
        (eurio_id,),
    ).fetchone()
    is_standard = bool(std and std["country"])
    if is_standard:
        # Ère = design_group si présent, sinon le coin seul (ère mono-membre).
        dg_clause, dg_args = design_group_lot_scope(
            conn, std["design_group_id"] or eurio_id, alias="si"
        )
        dg_clause_bare, _ = design_group_lot_scope(
            conn, std["design_group_id"] or eurio_id, alias=""
        )
        scope = "si.source='ebay'" + dg_clause
        scope_bare = "source='ebay'" + dg_clause_bare
        sp: tuple = tuple(dg_args)
        # La review standard ne sert que la lane manuelle (single) — on aligne.
        rq_lane_clause = " AND (rq.lane='manual' OR rq.lane IS NULL)"
    else:
        scope = "si.source='ebay' AND si.target_eurio_id=?"
        scope_bare = "source='ebay' AND target_eurio_id=?"
        sp = (eurio_id,)
        rq_lane_clause = ""

    breakdown = conn.execute(
        f"""
        SELECT route_decision, route_reason, COUNT(*) AS n
          FROM source_images
         WHERE {scope_bare}
         GROUP BY route_decision, route_reason
         ORDER BY n DESC
        """,
        sp,
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
        f"SELECT COUNT(*) FROM image_assets ia "
        f"JOIN source_images si ON si.id = ia.source_image_id "
        f"WHERE {scope}",
        sp,
    ).fetchone()[0]

    n_downloaded = conn.execute(
        f"SELECT COUNT(*) FROM source_images "
        f"WHERE {scope_bare} AND download_status='success'",
        sp,
    ).fetchone()[0]

    n_download_failed = conn.execute(
        f"SELECT COUNT(*) FROM source_images "
        f"WHERE {scope_bare} AND download_status='failed'",
        sp,
    ).fetchone()[0]

    # Raws téléchargés mais SANS aucun crop présent = candidats au re-crop
    # (même condition que la garde d'idempotence DetectCrop). Distingue « il faut
    # recropper » de « il faut rescraper » / « il faut reviewer » (§WS4).
    n_zero_crops = conn.execute(
        f"""
        SELECT COUNT(*) FROM source_images si
         WHERE {scope}
           AND si.download_status='success'
           AND NOT EXISTS (
               SELECT 1 FROM image_assets ia
                WHERE ia.source_image_id = si.id
                  AND ia.storage_status = 'present'
           )
        """,
        sp,
    ).fetchone()[0]

    # File de review RÉELLEMENT ouverte pour ce coin (review_queue.status='open'),
    # par kind. À distinguer de n_review_single/n_review_lot ci-dessus qui comptent
    # le route_decision des source_images (intention de routage) et restent figés
    # même après que les items aient été tranchés. C'EST ÇA qu'il faut afficher
    # comme « reste à reviewer » : sinon le bouton « Reviewer N » ment (ex.
    # georg-henrik : 27 review_single en route_decision mais 0 single open réel).
    rq_open = conn.execute(
        f"""
        SELECT rq.kind AS kind, COUNT(*) AS n
          FROM review_queue rq
          JOIN image_assets ia ON ia.id = rq.image_asset_id
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE {scope} AND rq.status='open'{rq_lane_clause}
         GROUP BY rq.kind
        """,
        sp,
    ).fetchall()
    rq_open_map = {r["kind"]: r["n"] for r in rq_open}
    n_open_review_single = rq_open_map.get("single", 0)
    n_open_review_lot = rq_open_map.get("lot", 0)

    # Ventilation par état CANONIQUE (image_state_current) — la source honnête,
    # persistée, qui remplace les heuristiques route_decision figées. C'est ce que
    # le cockpit doit afficher : `n_in_review` (file vivante) au lieu de
    # n_review_single/lot (gelés), `n_orphaned` (les crops jadis invisibles),
    # `n_resolved`/`n_resolved_training` (tranchés / éligibles train). Scoping par
    # target_eurio_id (clé de découverte stable). Cf. REBUILD-ANALYSIS.md.
    # Scopé via la jointure source_images (et non isc.target_eurio_id) pour
    # capter le pool pays d'un standard (crops ambigus inclus), cohérent avec
    # les autres compteurs ci-dessus.
    state_rows = conn.execute(
        f"""
        SELECT isc.current_state AS state, COUNT(*) AS n,
               SUM(CASE WHEN ia.training_eligible = 1 THEN 1 ELSE 0 END) AS n_te
          FROM image_state_current isc
          JOIN image_assets ia ON ia.id = isc.asset_id
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE {scope}
         GROUP BY isc.current_state
        """,
        sp,
    ).fetchall()
    state_counts = {r["state"]: r["n"] for r in state_rows}
    n_in_review = state_counts.get("queued", 0) + state_counts.get("in_review", 0)
    n_resolved = state_counts.get("resolved", 0)
    n_resolved_training = sum(
        (r["n_te"] or 0) for r in state_rows if r["state"] == "resolved"
    )
    n_orphaned = state_counts.get("orphaned", 0)

    # Runs ayant produit des source_images pour ce coin → run le plus récent
    # (deep-link bench) + flag multi-run (limite connue v1 : on linke le
    # dernier run, cf. handoff).
    run_rows = conn.execute(
        f"""
        SELECT run_id, COUNT(*) AS n, MAX(fetched_at) AS last_fetch
          FROM source_images
         WHERE {scope_bare} AND run_id IS NOT NULL
         GROUP BY run_id ORDER BY last_fetch DESC
        """,
        sp,
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
        "n_downloaded": n_downloaded,
        "n_download_failed": n_download_failed,
        "n_zero_crops": n_zero_crops,
        "by_route_decision": by_route,
        "n_pending": n_pending,
        "n_review_single": n_review_single,
        "n_review_lot": n_review_lot,
        "n_open_review_single": n_open_review_single,
        "n_open_review_lot": n_open_review_lot,
        "n_auto": n_auto,
        "n_rejected": n_rejected,
        "n_unrouted": n_unrouted,
        # ── État canonique (honnête, image_state_current) ──
        "state_counts": state_counts,
        "n_in_review": n_in_review,
        "n_resolved": n_resolved,
        "n_resolved_training": n_resolved_training,
        "n_orphaned": n_orphaned,
        "latest_run_id": latest_run_id,
        "latest_run_started_at": latest_run_started_at,
        "n_runs": len(run_rows),
    }


def _cohort_dedup_status(store: Store, cohort_id: str) -> dict:
    """Cœur (testable offline) de ``GET /lab/cohorts/{id}/dedup-status``.

    Expose les signaux de rupture D (doublons discarded_listings, absents
    discovery_log) — lecture seule, zéro appel eBay.

    Notes de scope :
    - ``n_unique_seen`` est global (``discovery_log`` n'a pas de FK cohort/run
      direct) → indique le volume total de listings jamais vus, toutes cohortes
      confondues. Annoté dans ``scope_note``.
    - ``n_discarded_*`` est scopé aux eurio_ids de la cohort via
      ``target_eurio_id`` — seule clé honnête disponible. Les discards dont
      ``target_eurio_id`` est NULL ne sont pas rattachables sans heuristique
      et ne sont pas comptés ici.
    """
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    conn = store._connection()  # noqa: SLF001
    cohort_eids = list(cohort.eurio_ids)

    # ── n_unique_seen : discovery_log global (pas de FK cohort) ──────────────
    n_unique_seen: int = conn.execute(
        "SELECT COUNT(*) FROM discovery_log WHERE source='ebay'"
    ).fetchone()[0]

    # ── discarded_listings scopé aux eurio_ids de la cohort ──────────────────
    if cohort_eids:
        ph = ",".join("?" * len(cohort_eids))
        row = conn.execute(
            f"""
            SELECT COUNT(*)                    AS n_discarded_total,
                   COUNT(DISTINCT source_ref)  AS n_discarded_unique
              FROM discarded_listings
             WHERE source='ebay'
               AND target_eurio_id IN ({ph})
            """,
            list(cohort_eids),
        ).fetchone()
        n_discarded_total: int = row["n_discarded_total"]
        n_discarded_unique: int = row["n_discarded_unique"]
        n_duplicates: int = n_discarded_total - n_discarded_unique

        # Unique discards absent from discovery_log → re-fetch infini possible
        n_absent: int = conn.execute(
            f"""
            SELECT COUNT(*)
              FROM (
                SELECT DISTINCT dl.source_ref
                  FROM discarded_listings dl
                 WHERE dl.source='ebay'
                   AND dl.target_eurio_id IN ({ph})
              ) unique_discarded
              LEFT JOIN discovery_log dlog
                ON dlog.source='ebay' AND dlog.source_ref = unique_discarded.source_ref
             WHERE dlog.id IS NULL
            """,
            list(cohort_eids),
        ).fetchone()[0]
    else:
        n_discarded_total = 0
        n_discarded_unique = 0
        n_duplicates = 0
        n_absent = 0

    pct_absent: float | None = (
        round(100.0 * n_absent / n_discarded_unique, 1)
        if n_discarded_unique > 0
        else None
    )

    return {
        "cohort_id": cohort_id,
        "scope_note": (
            "discovery_log est global (pas de FK cohort) ; "
            "discarded_listings scopé aux eurio_ids de la cohort via target_eurio_id"
        ),
        "n_unique_seen": n_unique_seen,
        "n_discarded_total": n_discarded_total,
        "n_discarded_unique": n_discarded_unique,
        "n_duplicates": n_duplicates,
        "n_absent_from_discovery": n_absent,
        "pct_absent": pct_absent,
    }


@router.get("/cohorts/{cohort_id}/dedup-status")
def cohort_dedup_status(cohort_id: str) -> dict:
    """Compteurs dédup eBay — lecture seule, zéro appel eBay.

    Expose les signaux de rupture D (doublons discarded_listings, absents
    discovery_log).
    """
    return _cohort_dedup_status(_get_store(), cohort_id)


def _cohort_funnel_status(store: Store, cohort_id: str) -> dict:
    """Cœur (testable offline) de ``GET /lab/cohorts/{id}/funnel-status``."""
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    from sources.cohort_scope import cohort_ebay_groups

    from .sources_routes import check_ebay_quota

    groups, non_scrapable = cohort_ebay_groups(store, cohort_id)
    non_set = set(non_scrapable)
    conn = store._connection()  # noqa: SLF001

    # ── per_coin (tail + sourcing) ─────────────────────────────────────
    # Tail funnel (post-attribution) + le bout « sourcing » fusionné depuis
    # l'ancien §C3 : `n_training_eligible` (crops reviewés OK pour ce coin,
    # label tranché `ia.eurio_id`) et `n_real_sources` (obverse Numista +
    # eBay reviewé) qui décident si la classe a assez de vraies vues pour
    # s'entraîner (§C5, seuil `_MIN_REAL_SOURCES`).
    # Design_group (avers) par coin : un standard dont l'avers est partagé sur
    # plusieurs années (ex. be-1999 ⊕ be-2007) porte le même `design_group_id`,
    # donc la même classe ArcFace. Exposé au cockpit pour scoper la review/le
    # collapse à l'ère plutôt qu'au millésime (cf. §design_group-first).
    dg_by_eid: dict[str, sqlite3.Row] = {}
    if cohort.eurio_ids:
        ph = ",".join("?" * len(cohort.eurio_ids))
        dg_by_eid = {
            r["eurio_id"]: r
            for r in conn.execute(
                f"SELECT c.eurio_id, c.design_group_id, c.is_commemorative, "
                f"dg.designation AS design_group_designation "
                f"FROM coins c "
                f"LEFT JOIN design_groups dg ON dg.id = c.design_group_id "
                f"WHERE c.eurio_id IN ({ph})",
                tuple(cohort.eurio_ids),
            ).fetchall()
        }

    # Membres d'ère (avers) par design_group standard présent dans la cohort —
    # TOUS les coins partageant l'avers (même hors-cohort), car la classe ArcFace
    # EST l'ère. Sert à compter les sources au niveau ère (be-1999 ⊕ be-2007),
    # pas au millésime — sinon un standard affamé paraît plus pauvre qu'il n'est.
    era_members: dict[str, list[str]] = {}
    for r in dg_by_eid.values():
        dgid = r["design_group_id"]
        if not dgid or r["is_commemorative"] or dgid in era_members:
            continue
        era_members[dgid] = [
            row["eurio_id"]
            for row in conn.execute(
                "SELECT eurio_id FROM coins WHERE COALESCE(design_group_id, eurio_id)=?",
                (dgid,),
            ).fetchall()
        ]

    per_coin: list[dict] = []
    for eid in cohort.eurio_ids:
        tail = _coin_tail(conn, eid)
        dg_row = dg_by_eid.get(eid)
        nid = coin_lookup.numista_id_for(eid)
        # Classe = ère (membres avers) pour un standard groupé, sinon le coin seul.
        dgid = dg_row["design_group_id"] if dg_row else None
        is_commemo = bool(dg_row["is_commemorative"]) if dg_row else True
        class_eids = (
            era_members[dgid] if (dgid and not is_commemo and dgid in era_members)
            else [eid]
        )
        ph_cls = ",".join("?" * len(class_eids))
        n_training = conn.execute(
            f"SELECT COUNT(*) FROM image_assets ia "
            f"JOIN source_images si ON si.id = ia.source_image_id "
            f"WHERE si.source='ebay' AND ia.eurio_id IN ({ph_cls}) "
            f"AND ia.training_eligible=1 "
            f"AND (ia.face IS NULL OR ia.face != 'reverse')",
            tuple(class_eids),
        ).fetchone()[0]
        # Seed = sources RÉELLES distinctes, comptées à l'identique du bake
        # (foundation/enrichment.py + iteration_augmentations) : crops eBay
        # validés + avers Numista (FS) + réfs officielles BCE/EUR-Lex (sur disque).
        # Avers partagé sur l'ère → l'obverse/réf ne se cumulent PAS (max, pas sum).
        n_numista_ref = (
            1 if any(_has_obverse(coin_lookup.numista_id_for(m)) for m in class_eids)
            else 0
        )
        n_bce_ref = max((_count_canonical_refs(conn, m) for m in class_eids), default=0)
        n_seed = n_training + n_numista_ref + n_bce_ref
        n_real = n_seed
        aug_factor, n_projected = _enrich_projection(n_seed)
        gap_to_target = max(0, TRAINING_TARGET - n_projected)
        # Signal santé réel : la cible ≥100 est toujours atteignable par
        # augmentation dès seed≥1 ; ce qui compte c'est d'avoir assez de crops
        # eBay RÉELS (diversité). En-dessous du plancher → aller chercher + d'eBay.
        below_real_floor = n_training < MIN_REAL
        never_scraped = tail["n_source_images"] == 0
        per_coin.append({
            "eurio_id": eid,
            "numista_id": nid,
            "scrapable": eid not in non_set,
            "n_training_eligible": n_training,
            "n_real_sources": n_real,
            "n_seed": n_seed,
            "aug_factor": aug_factor,
            "enough": n_training >= MIN_REAL,
            "below_real_floor": below_real_floor,
            "n_numista_ref": n_numista_ref,
            "n_bce_ref": n_bce_ref,
            "n_projected": n_projected,
            "gap_to_target": gap_to_target,
            "never_scraped": never_scraped,
            "design_group_id": dgid,
            "design_group_designation": (
                dg_row["design_group_designation"] if dg_row else None
            ),
            "is_commemorative": (
                bool(dg_row["is_commemorative"]) if dg_row else None
            ),
            "era_member_eurio_ids": class_eids,
            **tail,
        })

    # Collapse design_group-first : les standards d'une même ère (avers partagé)
    # sont déjà comptés au niveau ère (sources + tail), donc identiques entre
    # membres → on n'en garde qu'UNE ligne (le 1er membre de cohort rencontré,
    # ordre catalogue). Évite le doublon be-1999 + be-2007 aux compteurs jumeaux.
    # Les commémoratives (une classe = un eurio_id) ne sont jamais collapsées.
    collapsed: list[dict] = []
    seen_dg: set[str] = set()
    for c in per_coin:
        dgid = c["design_group_id"]
        if dgid and c["is_commemorative"] is False:
            if dgid in seen_dg:
                continue
            seen_dg.add(dgid)
        collapsed.append(c)
    per_coin = collapsed

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
    # B1 : un coin est « 0 attribué » (≠ « jamais scrapé ») si SON groupe de
    # découverte a bien été cherché (n_searches>0) mais qu'il n'a reçu aucune
    # attribution — cas be-2007 (ère 1 an, dispersée sur ses sœurs). Dérivé du
    # funnel de découverte déjà calculé, sans toucher au scrape.
    searched_coins: set[str] = set()
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
        if (disco.get("n_searches") or 0) > 0:
            searched_coins.update(coins)
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

    # B1 : marque chaque coin dont le groupe a été cherché → « 0 attribué » au
    # lieu de « jamais scrapé » quand n_source_images=0 (honnête : le scrape a
    # tourné, la pièce n'a juste rien reçu).
    for _c in per_coin:
        _c["group_scraped"] = _c["eurio_id"] in searched_coins

    # ── Rescue cross-classe : crops validés (training_eligible=1) scrapés SOUS
    # un groupe de la cohort mais ré-attribués en review à une pièce SŒUR hors
    # cohort. Ce sont du training valide pour LEUR pièce — pas pour une pièce de
    # la cohort — donc jamais comptés dans le seed d'une classe cohort ; on les
    # rend juste VISIBLES pour que le travail ne paraisse pas perdu (§WS3).
    rescued_to_sisters: list[dict] = []
    if cohort.eurio_ids:
        ph = ",".join("?" * len(cohort.eurio_ids))
        rescued_to_sisters = [
            {"source_coin": r[0], "sister_eurio_id": r[1], "n": r[2]}
            for r in conn.execute(
                f"""
                SELECT si.target_eurio_id AS source_coin,
                       ia.eurio_id        AS sister_eurio_id,
                       COUNT(*)           AS n
                  FROM image_assets ia
                  JOIN source_images si ON si.id = ia.source_image_id
                 WHERE si.source = 'ebay'
                   AND ia.training_eligible = 1
                   AND si.target_eurio_id IN ({ph})
                   AND ia.eurio_id IS NOT NULL
                   AND ia.eurio_id NOT IN ({ph})
                 GROUP BY si.target_eurio_id, ia.eurio_id
                 ORDER BY n DESC
                """,
                [*cohort.eurio_ids, *cohort.eurio_ids],
            ).fetchall()
        ]

    # Quota offline + groupes scrapables (fusionnés depuis l'ancien §C3 pour
    # alimenter le bouton « Lancer scrape eBay (cohort) »). Aucun appel eBay.
    n_group_coins = sum(g.n_coins for g in groups)
    quota = check_ebay_quota(store, n_eurio_ids=n_group_coins) if groups else None

    return {
        "cohort_id": cohort.id,
        "per_coin": per_coin,
        "rescued_to_sisters": rescued_to_sisters,
        "head": {
            "groups": head_groups,
            "run_ids": cohort_run_ids,
        },
        "scrapable_groups": [
            {
                "denomination": g.denomination, "country": g.country,
                "year": g.year, "n_coins": g.n_coins, "kind": g.kind,
            }
            for g in groups
        ],
        "non_scrapable": non_scrapable,
        "quota": quota,
        "min_real_sources": _MIN_REAL_SOURCES,
        "training_target": TRAINING_TARGET,
    }


@router.get("/cohorts/{cohort_id}/funnel-status")
def cohort_funnel_status(cohort_id: str) -> dict:
    """eBay sourcing + funnel scrape → review, scopé cohort (read-only, zéro
    appel eBay).

    Voir le bloc de doc ci-dessus pour la doctrine des deux mailles
    (per_coin tail précis vs head groupe). Alimente le tiroir §C3 et les
    deep-links vers le studio bench (``/bench/runs/<run>?eurio_id=<coin>``)."""
    return _cohort_funnel_status(_get_store(), cohort_id)


# ── QA crops d'entraînement par classe (boucle d'amélioration — INSPECT) ─────
# Surface, par classe design_group de la cohorte, les crops qui alimentent (ou
# pourraient alimenter) le train, rangés « suspect d'abord », couplés au R@1
# studio par classe — pour repérer les déchets et les exclure en un clic.
# Spéc : docs/work-in-progress/improvement-loop/03-crop-triage-ux.md.

# Statuts de crops qu'on expose au triage : le pool résolu (candidats train) +
# les rejetés (pour pouvoir restaurer). On NE touche PAS resolution_status à
# l'exclusion — seul training_eligible bascule, donc le crop reste visible et le
# prochain bake le drop (filtre training_eligible=1). Cf. 02-pipeline-map.
# Source de vérité partagée avec le scan (même périmètre panneau ↔ scan) : la
# requête SQL vit désormais dans ``store/funnel.py`` (état-DB-portable, C3,
# partagé avec l'image lean du VPS) — ``TRIAGE_STATUSES``/le LIMIT par classe y
# sont importés depuis ``store.funnel_constants``/``store.funnel`` directement.


class TrainingCrop(BaseModel):
    asset_id: str
    source: str
    file_url: str
    eurio_id: str | None = None
    face: str | None = None
    denom: str | None = None
    quality_score: float | None = None
    training_eligible: bool
    resolution_status: str
    # « routé » = une row review_queue OUVERTE existe pour ce crop → il atteindra
    # l'écran de review (compté par §C4 « Review crops »). Un needs_review NON
    # routé est bloqué : jamais enfilé, invisible à la review (cf. n_unrouted).
    routed: bool = False
    # ── P1 · verdict du dernier scan (cohort_training_scan_results) ──
    # « probable intrus » = margin (une autre classe de la cohorte le réclame)
    # et/ou outlier (ne ressemble pas à ses camarades — vraie classe hors
    # cohorte). Suggestion, pas une décision.
    intruder_suspect: bool = False
    intruder_reason: str | None = None  # 'margin' | 'outlier' | 'margin+outlier'
    intruder_top1_class: str | None = None
    intruder_top1_eurio_id: str | None = None
    intruder_margin: float | None = None


class ClassConfusion(BaseModel):
    """P6 · « cette classe se confond avec X » — agrégé du confusion_matrix du
    dernier bench (photos ground-truth de la classe prédites top-1 ailleurs)."""
    class_id: str
    n: int


class TrainingCropClass(BaseModel):
    class_id: str
    class_kind: str
    member_eurio_ids: list[str]
    # « part au train » = compté à l'identique du bake (P3) : training_eligible=1
    # ET face != 'reverse'. Un reverse éligible est exposé dans n_reverse_flagged
    # (anneau ambre) mais n'entre plus au bake.
    n_eligible: int
    n_unknown_face: int  # éligibles face NULL/'unknown' (à confirmer — P2 les résout)
    n_reverse_flagged: int  # éligibles face='reverse' (hors bake depuis P3)
    n_rejected: int
    # needs_review de cette classe SANS row review_queue ouverte → jamais enfilés,
    # invisibles à §C4 « Review crops ». Réconcilie l'écart « 0 solo à trancher »
    # (C4, file vivante) vs « N à reviewer » (C5, resolution_status) : la
    # différence, ce sont ces non-routés bloqués.
    n_review_unrouted: int = 0
    n_intruders: int  # P1 · suspects levés par le dernier scan
    r_at_1: float | None = None  # R@1 studio (dernière itération), moyenné sur les membres
    # ── P5 · Δ vs itération benchée précédente ──
    r_at_1_prev: float | None = None
    r_at_1_delta: float | None = None  # r_at_1 − r_at_1_prev (si les deux existent)
    n_real_last_bake: int | None = None   # seed réel au bake de la dernière itération
    n_real_prev_bake: int | None = None   # idem, itération benchée précédente
    # ── P4 · santé / couverture ──
    n_obverse: int = 0            # éligibles face obverse confirmée
    has_numista_ref: bool = False  # avers canonique Numista sur le FS
    n_bce_ref: int = 0             # réfs officielles BCE / EUR-Lex présentes
    underfed: bool = False         # n_eligible < min_real → « sourcer »
    # ── P6 · confusions du dernier bench ──
    confused_with: list[ClassConfusion] = []
    crops: list[TrainingCrop]


class TrainingScanInfo(BaseModel):
    """Dernier scan TERMINÉ mergé dans la réponse (fraîcheur des badges P1/P2).
    Le statut live d'un scan en cours se lit sur ``training-scan/status``."""
    scan_id: str
    finished_at: str | None = None
    n_intruders: int
    n_faces_written: int
    intruder_margin: float | None = None


class CohortTrainingCropsResponse(BaseModel):
    cohort_id: str
    cohort_name: str
    benchmark_run_id: str | None = None
    prev_benchmark_run_id: str | None = None  # P5 · itération benchée précédente
    min_real: int = MIN_REAL  # plancher qualité (P4) — légende du front
    scan: TrainingScanInfo | None = None
    classes: list[TrainingCropClass]


# ── Overlay dérivé (GPU + FS) — C3, Direction A ──────────────────────────────
# Tout ce qui n'est PAS état-DB-portable : verdicts intrus (scan Dino, GPU),
# R@1/confusions (bench studio, GPU), refs Numista/BCE (checks filesystem).
# Servi UNIQUEMENT full-server (``GET /lab/cohorts/{id}/training-overlay``,
# jamais sur l'image lean) ; se merge côté front par-dessus l'état VPS
# (``store.funnel.list_training_crops`` / ``serving.lab_read_routes``).


class ClassOverlay(BaseModel):
    r_at_1: float | None = None
    r_at_1_prev: float | None = None
    r_at_1_delta: float | None = None
    confused_with: list[ClassConfusion] = []
    n_real_last_bake: int | None = None
    n_real_prev_bake: int | None = None
    has_numista_ref: bool = False  # avers canonique Numista sur le FS
    n_bce_ref: int = 0             # réfs officielles BCE/EUR-Lex présentes sur le FS


class AssetOverlay(BaseModel):
    intruder_suspect: bool = False
    intruder_reason: str | None = None
    intruder_top1_class: str | None = None
    intruder_top1_eurio_id: str | None = None
    intruder_margin: float | None = None


class TrainingOverlayResponse(BaseModel):
    benchmark_run_id: str | None = None
    prev_benchmark_run_id: str | None = None
    scan: TrainingScanInfo | None = None
    classes: dict[str, ClassOverlay]
    assets: dict[str, AssetOverlay]


def _benched_iterations(store: Store, cohort_id: str) -> list:
    """Paires ``(iteration, bench)`` de la cohorte dont le benchmark est
    COMPLETED, la plus récente d'abord. Un bench failed n'a ni per_coin ni
    confusion — le retenir masquerait le vrai « pas encore benché » (badge —)."""
    pairs = []
    for it in store.list_iterations(cohort_id=cohort_id):
        if it.benchmark_run_id is None:
            continue
        bench = store.get_benchmark_run(it.benchmark_run_id)
        if bench is None or bench.status != "completed":
            continue
        pairs.append((it, bench))
    pairs.sort(key=lambda p: p[0].finished_at or p[0].created_at or "",
               reverse=True)
    return pairs


def _bench_per_coin(bench) -> tuple[str | None, dict[str, float], dict]:
    """(benchmark_run_id, {eurio_id: r_at_1}, confusion) d'un bench (ou None)."""
    if bench is None:
        return None, {}, {}
    per_coin: dict[str, float] = {}
    for entry in bench.per_coin:
        eid = entry.get("eurio_id")
        r1 = entry.get("r_at_1")
        if isinstance(eid, str) and isinstance(r1, (int, float)):
            per_coin[eid] = float(r1)
    return bench.id, per_coin, bench.confusion or {}


def _aug_real_by_key(store: Store, iteration_id: str | None) -> dict[str, int]:
    """{clé de bake: num_real} d'une itération (iteration_aug_vs_real) — le seed
    réel par classe au moment du bake (P5 : « n_eligible avant/après »). La clé
    est celle du bake (class_id design_group ou eurio_id) ; le caller matche
    class_id ∪ membres."""
    if iteration_id is None:
        return {}
    conn = store._connection()  # noqa: SLF001
    return {
        r["eurio_id"]: int(r["num_real"])
        for r in conn.execute(
            "SELECT eurio_id, num_real FROM iteration_aug_vs_real "
            "WHERE iteration_id=?",
            (iteration_id,),
        ).fetchall()
    }


def _cohort_training_overlay_data(store: Store, cohort: ExperimentCohortRow) -> dict:
    """Cœur (dict pur, réutilisé par la route ``/training-overlay`` ET par
    ``_cohort_training_crops`` pour le merge full-server) du DÉRIVÉ GPU+FS de la
    cohorte : verdicts intrus (scan Dino), R@1/confusions (bench studio), refs
    Numista/BCE (FS). AUCUN état-DB-portable ici (cf. ``store.funnel``)."""
    from training.eval.class_resolver import build_resolver

    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, _unresolved = resolver.classes_for_eurio_ids(cohort.eurio_ids)

    # ── P5 · les deux dernières itérations benchées : R@1 courant vs précédent,
    # seed réel au bake (iteration_aug_vs_real). ──
    benched = _benched_iterations(store, cohort.id)
    latest_it, latest_bench = benched[0] if benched else (None, None)
    prev_it, prev_bench = benched[1] if len(benched) > 1 else (None, None)
    benchmark_run_id, per_coin_r1, confusion = _bench_per_coin(latest_bench)
    prev_benchmark_run_id, per_coin_r1_prev, _ = _bench_per_coin(prev_bench)
    real_last = _aug_real_by_key(store, latest_it.id if latest_it else None)
    real_prev = _aug_real_by_key(store, prev_it.id if prev_it else None)

    # ── P1 · verdicts du dernier scan TERMINÉ ──
    # cohort_training_scans/_results vivent dans le store d'état LOCAL (bookkeeping) ;
    # les réfs canoniques (_count_canonical_refs, plus bas) restent sur `conn`.
    conn = store._connection()  # noqa: SLF001 — canonique
    lconn = _get_local_store()._connection()  # noqa: SLF001 — scan bookkeeping local
    scan_row = latest_training_scan(lconn, cohort.id, status="done")
    scan_verdicts = (
        training_scan_results(lconn, scan_row["id"]) if scan_row is not None else {}
    )
    scan_info = (
        TrainingScanInfo(
            scan_id=scan_row["id"],
            finished_at=scan_row["finished_at"],
            n_intruders=scan_row["n_intruders"],
            n_faces_written=scan_row["n_faces_written"],
            intruder_margin=scan_row["intruder_margin"],
        )
        if scan_row is not None else None
    )

    # ── P6 · confusion_matrix (eurio_id → eurio_id/class_id) agrégée à la
    # maille classe : {classe gt: {classe prédite: n}}, self exclu. ──
    class_of: dict[str, str] = {}
    for d in descriptors:
        class_of[d.class_id] = d.class_id
        for eid in d.eurio_ids:
            class_of[eid] = d.class_id
    confused_by_class: dict[str, dict[str, int]] = {}
    for gt, preds in confusion.items():
        gt_cls = class_of.get(gt)
        if gt_cls is None:
            continue
        for pred, n in preds.items():
            pred_cls = class_of.get(pred, pred)
            if pred_cls == gt_cls:
                continue
            bucket = confused_by_class.setdefault(gt_cls, {})
            bucket[pred_cls] = bucket.get(pred_cls, 0) + int(n)

    def _real_at_bake(table: dict[str, int], class_id: str, members: list[str]) -> int | None:
        """Seed réel du bake pour la classe — la clé du bake est le class_id
        (design_group) ou l'eurio_id (commemo) selon l'itération ; on matche
        les deux, max (les membres d'ère partagent le même pool)."""
        vals = [table[k] for k in (class_id, *members) if k in table]
        return max(vals) if vals else None

    classes_overlay: dict[str, dict] = {}
    for d in descriptors:
        members = list(d.eurio_ids)
        confusions = [
            ClassConfusion(class_id=cid, n=n)
            for cid, n in sorted(
                confused_by_class.get(d.class_id, {}).items(),
                key=lambda kv: -kv[1],
            )[:3]
        ]
        member_r1 = [per_coin_r1[m] for m in members if m in per_coin_r1]
        r_at_1 = sum(member_r1) / len(member_r1) if member_r1 else None
        member_r1_prev = [
            per_coin_r1_prev[m] for m in members if m in per_coin_r1_prev
        ]
        r_at_1_prev = (
            sum(member_r1_prev) / len(member_r1_prev) if member_r1_prev else None
        )
        classes_overlay[d.class_id] = {
            "r_at_1": r_at_1,
            "r_at_1_prev": r_at_1_prev,
            "r_at_1_delta": (
                r_at_1 - r_at_1_prev
                if (r_at_1 is not None and r_at_1_prev is not None) else None
            ),
            "confused_with": confusions,
            "n_real_last_bake": _real_at_bake(real_last, d.class_id, members),
            "n_real_prev_bake": _real_at_bake(real_prev, d.class_id, members),
            "has_numista_ref": any(
                _has_obverse(coin_lookup.numista_id_for(m)) for m in members
            ),
            "n_bce_ref": max(
                (_count_canonical_refs(conn, m) for m in members), default=0,
            ),
        }

    assets_overlay: dict[str, dict] = {
        asset_id: {
            "intruder_suspect": bool(v["is_intruder"]) and not bool(v["dismissed"]),
            "intruder_reason": v["intruder_reason"],
            "intruder_top1_class": v["top1_class"],
            "intruder_top1_eurio_id": v["top1_eurio_id"],
            "intruder_margin": v["margin"],
        }
        for asset_id, v in scan_verdicts.items()
    }

    return {
        "benchmark_run_id": benchmark_run_id,
        "prev_benchmark_run_id": prev_benchmark_run_id,
        "scan": scan_info,
        "classes": classes_overlay,
        "assets": assets_overlay,
    }


def _cohort_training_crops(store: Store, cohort_id: str) -> CohortTrainingCropsResponse:
    """Cœur (testable offline) de ``GET /lab/cohorts/{id}/training-crops``
    (full-server, LOCAL). Compose l'état-DB-portable (``store.funnel
    .list_training_crops`` — SOURCE UNIQUE, partagée avec l'image lean du VPS,
    cf. ``serving/lab_read_routes.py``) et l'overlay dérivé GPU+FS
    (``_cohort_training_overlay_data``), merge par ``class_id``/``asset_id``.
    Garantit la parité full-local == VPS-lecture ⊕ overlay-local (C3)."""
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    conn = store._connection()  # noqa: SLF001
    try:
        state = list_training_crops(conn, cohort.id)
    except DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    overlay = _cohort_training_overlay_data(store, cohort)
    classes_overlay = overlay["classes"]
    assets_overlay = overlay["assets"]

    classes: list[TrainingCropClass] = []
    for cs in state["classes"]:
        ov = classes_overlay.get(cs["class_id"], {})
        crops: list[TrainingCrop] = []
        for cr in cs["crops"]:
            aov = assets_overlay.get(cr["asset_id"], {})
            crops.append(TrainingCrop(
                **cr,
                intruder_suspect=aov.get("intruder_suspect", False),
                intruder_reason=aov.get("intruder_reason"),
                intruder_top1_class=aov.get("intruder_top1_class"),
                intruder_top1_eurio_id=aov.get("intruder_top1_eurio_id"),
                intruder_margin=aov.get("intruder_margin"),
            ))
        # P1 : les probables intrus en TÊTE — ceux AU TRAIN d'abord (ils
        # polluent le modèle), puis les flagués hors-train (rescue), marge
        # décroissante ; enfin l'ordre suspect-first du SQL (tri stable).
        crops.sort(key=lambda c: (
            0 if (c.intruder_suspect and c.training_eligible)
            else 1 if c.intruder_suspect else 2,
            -(c.intruder_margin or 0.0) if c.intruder_suspect else 0.0,
        ))
        # Compteur d'en-tête = intrus AU TRAIN (ce qui pollue le modèle) ; les
        # flags sur needs_review/rejetés restent visibles via les filtres.
        n_intruders = sum(
            1 for c in crops if c.intruder_suspect and c.training_eligible
        )
        classes.append(TrainingCropClass(
            class_id=cs["class_id"], class_kind=cs["class_kind"],
            member_eurio_ids=cs["member_eurio_ids"],
            n_eligible=cs["n_eligible"],
            n_unknown_face=cs["n_unknown_face"],
            n_reverse_flagged=cs["n_reverse_flagged"],
            n_rejected=cs["n_rejected"],
            n_review_unrouted=cs["n_review_unrouted"],
            n_intruders=n_intruders,
            r_at_1=ov.get("r_at_1"),
            r_at_1_prev=ov.get("r_at_1_prev"),
            r_at_1_delta=ov.get("r_at_1_delta"),
            n_real_last_bake=ov.get("n_real_last_bake"),
            n_real_prev_bake=ov.get("n_real_prev_bake"),
            n_obverse=cs["n_obverse"],
            has_numista_ref=ov.get("has_numista_ref", False),
            n_bce_ref=ov.get("n_bce_ref", 0),
            underfed=cs["underfed"],
            confused_with=ov.get("confused_with", []),
            crops=crops,
        ))

    # Tri des classes : « à inspecter d'abord » = R@1 bas (None → en tête comme
    # non-évalué/risqué), puis plus d'intrus, puis plus de suspects (face ?).
    classes.sort(key=lambda c: (
        c.r_at_1 if c.r_at_1 is not None else -1.0,
        -c.n_intruders,
        -c.n_unknown_face,
    ))
    return CohortTrainingCropsResponse(
        cohort_id=cohort.id, cohort_name=cohort.name,
        benchmark_run_id=overlay["benchmark_run_id"],
        prev_benchmark_run_id=overlay["prev_benchmark_run_id"],
        min_real=state["min_real"],
        scan=overlay["scan"],
        classes=classes,
    )


def _cohort_training_overlay(store: Store, cohort_id: str) -> TrainingOverlayResponse:
    """Cœur (testable offline) de ``GET /lab/cohorts/{id}/training-overlay``
    (full-server, LOCAL uniquement — jamais sur l'image lean)."""
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    data = _cohort_training_overlay_data(store, cohort)
    return TrainingOverlayResponse(
        benchmark_run_id=data["benchmark_run_id"],
        prev_benchmark_run_id=data["prev_benchmark_run_id"],
        scan=data["scan"],
        classes={cid: ClassOverlay(**v) for cid, v in data["classes"].items()},
        assets={aid: AssetOverlay(**v) for aid, v in data["assets"].items()},
    )


@router.get("/cohorts/{cohort_id}/training-crops", response_model=CohortTrainingCropsResponse)
def cohort_training_crops(cohort_id: str) -> CohortTrainingCropsResponse:
    """Crops d'entraînement par classe design_group de la cohorte, rangés suspect
    d'abord et couplés au R@1 studio — pour le triage des déchets (read-only).

    Fusion FULL-SERVER de l'état-DB-portable (``store.funnel.list_training_crops``,
    identique à ``GET /lab/cohorts/{id}/training-crops`` servi sur l'image lean du
    VPS) et de l'overlay dérivé GPU+FS local (``training-overlay`` ci-dessous)."""
    return _cohort_training_crops(_get_store(), cohort_id)


@router.get("/cohorts/{cohort_id}/training-overlay", response_model=TrainingOverlayResponse)
def cohort_training_overlay(cohort_id: str) -> TrainingOverlayResponse:
    """Overlay dérivé GPU+FS de la cohorte (verdicts intrus du dernier scan Dino,
    R@1/confusions du dernier bench studio, refs Numista/BCE sur le FS) — LOCAL
    uniquement, jamais servi sur l'image lean (le VPS n'a pas de GPU). Se merge
    côté front par-dessus l'état VPS (``asset_id``/``class_id``, C3)."""
    return _cohort_training_overlay(_get_store(), cohort_id)


@router.post("/assets/{asset_id}/training-eligible")
def set_asset_training_eligible(
    asset_id: str, payload: SetTrainingEligiblePayload,
) -> dict:
    """Inclut/exclut un crop du train (``training_eligible``). Réversible.

    Exclure pose ``quality_reason='manual_triage'`` (traçable) sans toucher
    ``resolution_status`` ni ``eurio_id`` — le crop reste visible au triage, et
    le prochain bake le drop (filtre ``training_eligible=1``). Restaurer efface
    le ``quality_reason`` posé par le triage (laisse intacts les autres motifs).

    Logique SQL déléguée à ``store.decisions.apply_set_training_eligible`` (source
    unique partagée avec l'image lean du VPS — cf. C2a)."""
    conn = _get_store()._connection()  # noqa: SLF001
    try:
        result = apply_set_training_eligible(conn, asset_id, payload.eligible)
    except DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    conn.commit()
    return result


@router.post("/assets/{asset_id}/reopen-review", response_model=ReopenReviewResult)
def reopen_asset_review(asset_id: str) -> ReopenReviewResult:
    """« Repasser en reviewer » depuis le Jeu d'entraînement : un crop promu au
    train qu'on veut retrancher (erreur de promotion).

    Remet ``resolution_status='needs_review'`` + ``resolved_at=NULL`` ET
    ``training_eligible=0`` (le crop QUITTE le train tant qu'il n'est pas
    re-décidé — sinon le prochain bake le reprendrait malgré son retour en
    review), puis RÉ-ENFILE une row ``review_queue`` OUVERTE (UPSERT sur la
    contrainte ``UNIQUE(image_asset_id)`` : ré-ouvre la ligne 'done' existante
    ou en crée une) → le crop réapparaît dans l'écran Review (§C4). Le dernier
    ``eurio_id`` est conservé comme indice ; la review le confirme ou le
    corrige. Symétrique de la décision de review (qui, à l'acceptation, remet
    ``training_eligible=1``). Même patron que ``/assets/reflag-needs-review``,
    scopé à un asset et avec la bascule d'éligibilité en plus.

    Logique SQL déléguée à ``store.decisions.apply_reopen_review`` (source unique
    partagée avec l'image lean du VPS — cf. C2a)."""
    conn = _get_store()._connection()  # noqa: SLF001
    try:
        result = apply_reopen_review(conn, asset_id)
    except DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    conn.commit()
    return ReopenReviewResult(**result)


@router.post("/assets/{asset_id}/accept-training", response_model=AcceptTrainingResult)
def accept_asset_training(asset_id: str) -> AcceptTrainingResult:
    """« Accepter au train » un crop ``needs_review`` depuis le Jeu
    d'entraînement : décision de review one-clic qui CONFIRME le crop dans sa
    classe courante (on garde ``eurio_id``/``face`` tels quels — le crop est
    dans cette classe parce que son ``eurio_id`` en est membre).

    Miroir de la décision de review (``review_queue/writes.py`` decide_review) :
    ``resolution_status='manual'`` + ``resolution_confidence=1.0`` +
    ``training_eligible=1`` + ``resolved_at`` ; marque la row ``review_queue``
    ouverte 'done' (si elle existe) et émet l'event 'resolved'. Symétrique de
    ``/reopen-review``. Le simple flip ``training-eligible`` ne suffisait pas :
    la pièce restait ``needs_review`` donc affichée sous « À reviewer » (le
    classement met needs_review avant l'éligibilité).

    Logique SQL déléguée à ``store.decisions.apply_accept_training`` (source unique
    partagée avec l'image lean du VPS — cf. C2a)."""
    conn = _get_store()._connection()  # noqa: SLF001
    try:
        result = apply_accept_training(conn, asset_id)
    except DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    conn.commit()
    return AcceptTrainingResult(**result)


@router.post("/assets/{asset_id}/reassign")
def reassign_asset(asset_id: str, payload: ReassignAssetPayload) -> dict:
    """Réassigne un crop à une autre pièce (``eurio_id``) — pour rediriger, depuis
    le Jeu d'entraînement, un intrus vers la bonne classe.

    Ne touche QUE ``image_assets.eurio_id`` : ``training_eligible``, ``face``,
    ``denom`` et ``resolution_status`` sont préservés (un crop bien cadré mais mal
    classé reste un bon crop, juste sur une autre pièce). ``source_images`` est
    laissé intact (provenance du scrape). Symétrique de ``training-eligible`` ;
    l'asset quitte sa classe source et rejoint la classe cible au prochain read.

    Écriture eurio_id déléguée à ``store.decisions.apply_reassign`` (canonique,
    partagée avec l'image lean du VPS — cf. C2a). Le dismiss du verdict intrus est
    un OVERLAY LOCAL (hors canonique) → fait ICI en full-server (la table de scan
    est locale) ; en Direction A c'est le FRONT qui le déclenche (dismissIntruder
    via l'API ML locale) au succès du reassign VPS. Cf. C3/CodeReview."""
    conn = _get_store()._connection()  # noqa: SLF001
    try:
        result = apply_reassign(conn, asset_id, payload.eurio_id)
    except DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    # Overlay LOCAL (cohort_training_scan_results) : le verdict intrus (calculé sur
    # l'ancienne classe) est périmé → dismiss dans le store d'état local.
    training_scan_dismiss_intruder(_get_local_store()._connection(), asset_id)  # noqa: SLF001
    return result


class IntruderDismissResult(BaseModel):
    asset_id: str
    dismissed: bool  # False = aucun verdict à dismisser (déjà propre)


@router.post("/assets/{asset_id}/intruder-dismiss", response_model=IntruderDismissResult)
def intruder_dismiss(
    asset_id: str, cohort_id: str | None = Query(default=None),
) -> IntruderDismissResult:
    """« Faux positif — garde-le au train » : override humain du badge intrus
    depuis le Jeu d'entraînement, SANS changer de classe ni exclure. Marque le
    verdict du dernier scan ``dismissed=1`` (l'audit ``is_intruder`` reste) →
    le crop quitte la sous-liste « Intrus ? » et reste éligible tel quel.

    ``cohort_id`` scope le dismiss au scan de la cohorte affichée (un même crop
    peut être scanné dans plusieurs cohortes — on ne touche que la bonne)."""
    store = _get_store()
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT 1 FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Crop introuvable")
    # Dismiss = overlay LOCAL (cohort_training_scan_results) ; l'audit image_assets
    # et l'event de sync restent canoniques (conn).
    touched = training_scan_dismiss_intruder(
        _get_local_store()._connection(), asset_id, cohort_id=cohort_id,  # noqa: SLF001
    )
    # Verdict scan = dérivé (recomputable), mais l'override humain est une
    # décision : journalisée pour la sync, rejouée best-effort à distance
    # (UPDATE si la ligne de scan existe, no-op sinon).
    emit_field_event(
        conn, asset_id=asset_id, reason="intruder_dismiss",
        fields={"cohort_training_scan_results.dismissed": 1},
        detail={"cohort_id": cohort_id} if cohort_id else None,
    )
    conn.commit()
    return IntruderDismissResult(asset_id=asset_id, dismissed=touched > 0)


# ── Scan Dino du Jeu d'entraînement (P1 intrus + P2 face) ────────────────────
# Subprocess détaché, même doctrine que recrop-zero : l'endpoint ouvre la row
# `cohort_training_scans`, le subprocess la fait avancer et la clôt lui-même.
# Cœur : training/training_set_scan.py. Résultats mergés dans training-crops.

# Au-delà de cette durée, un scan 'running' est considéré orphelin même si son
# PID semble vivant (réutilisation de PID). Un scan réel = quelques minutes
# (~10-15 crops/s vitl14 sur MPS + chargement modèle).
_TRAINING_SCAN_MAX_RUNTIME_MIN = 60


def reap_orphan_training_scans(store: Store) -> int:
    """Marque `failed` les `cohort_training_scans` restés `running` dont le
    subprocess est mort. Appelé au startup (même hook que le reaper recrop)."""
    conn = store._connection()  # noqa: SLF001
    rows = conn.execute(
        "SELECT id, pid, "
        "  CAST((julianday('now') - julianday(started_at)) * 24 * 60 AS REAL) AS age_min "
        "FROM cohort_training_scans WHERE status='running'"
    ).fetchall()
    reaped = 0
    for r in rows:
        pid = r["pid"]
        age_min = r["age_min"] or 0.0
        alive = False
        if pid:
            try:
                os.kill(int(pid), 0)
                alive = True
            except PermissionError:
                alive = True
            except (ProcessLookupError, OSError, ValueError):
                alive = False
        if alive and age_min < _TRAINING_SCAN_MAX_RUNTIME_MIN:
            continue
        reason = ("process restart — orphan scan (reaped at boot)"
                  if not alive else
                  f"reaped at boot — running > {_TRAINING_SCAN_MAX_RUNTIME_MIN}min "
                  f"(pid {pid} suspect)")
        conn.execute(
            "UPDATE cohort_training_scans SET status='failed', "
            "finished_at=COALESCE(finished_at, datetime('now')), "
            "error=COALESCE(error, ?) WHERE id=?",
            (reason, r["id"]),
        )
        reaped += 1
    return reaped


@router.post("/cohorts/{cohort_id}/training-scan", status_code=202)
def start_training_scan(cohort_id: str, margin: float | None = None) -> dict:
    """Lance en arrière-plan le scan Dino du Jeu d'entraînement : détection
    d'intrus en ensemble fermé (P1) + passe de face sur les NULL/'unknown'
    (P2). Écrit `image_assets.face` (jamais par-dessus un label existant) et
    les verdicts dans `cohort_training_scan_results` — la réassignation reste
    une décision humaine. Le front poll `training-scan/status` puis recharge
    `training-crops` (badges intrus mergés)."""
    from training.training_set_scan import (
        DEFAULT_INTRUDER_MARGIN,
        scan_scope_count,
    )
    from training.foundation import (
        SUGGESTIONS_ANCHORS_KIND,
        SUGGESTIONS_ENCODER_VERSION,
    )

    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    # cohort_training_scans = bookkeeping LOCAL (writable même sous le flip readonly).
    # scan_scope_count lit le canonique via `store`.
    lconn = _get_local_store()._connection()  # noqa: SLF001
    running = latest_training_scan(lconn, cohort_id, status="running")
    if running is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "training_scan_already_running",
                    "scan_id": running["id"]},
        )
    eff_margin = margin if margin is not None else DEFAULT_INTRUDER_MARGIN
    n_total = scan_scope_count(store, cohort)
    scan_id = training_scan_start(
        lconn,
        cohort_id=cohort_id,
        anchors_kind=SUGGESTIONS_ANCHORS_KIND,
        encoder_version=SUGGESTIONS_ENCODER_VERSION,
        intruder_margin=eff_margin,
        n_total=n_total,
    )

    # Subprocess DÉTACHÉ (précédent : recrop_zero_coin ci-dessous) — torch/MPS
    # hors du worker, survit au --reload, crash visible in-row (failed).
    log_dir = _ML_DIR / "state" / "job_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"training-scan-{scan_id}.log"
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_ML_DIR) + (os.pathsep + existing if existing else "")
    cmd = [
        sys.executable, "scripts/lab_training_scan.py",
        "--cohort", cohort_id, "--scan-id", scan_id,
        "--margin", str(eff_margin),
    ]
    logf = log_path.open("w")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(_ML_DIR), env=env,
            stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        logf.close()
    training_scan_set_pid(lconn, scan_id, proc.pid)
    lconn.commit()
    logger.info("[training-scan] %s spawned subprocess pid=%s scan=%s log=%s",
                cohort_id, proc.pid, scan_id, log_path)
    return {"status": "started", "scan_id": scan_id,
            "n_total": n_total, "pid": proc.pid,
            "intruder_margin": eff_margin}


@router.get("/cohorts/{cohort_id}/training-scan/status")
def training_scan_status(cohort_id: str) -> dict:
    """Statut du dernier scan de la cohorte (persisté, survit au restart).
    ``idle`` si aucun scan n'a jamais tourné."""
    conn = _get_local_store()._connection()  # noqa: SLF001 — cohort_training_scans = local
    row = latest_training_scan(conn, cohort_id)
    if row is None:
        return {"status": "idle"}
    return {k: row[k] for k in row.keys() if k != "pid"}


# ── Recrop des zéro-crops d'une pièce (census+gate, en arrière-plan) ──────────
# B2 corrigé : l'état du job vit dans la table `cohort_jobs` (persisté, survit au
# restart, progression au fil de l'eau), PLUS de dict in-memory opaque. Le thread
# fait le travail ; son ÉTAT est en base. Source de vérité du recrop =
# scan/recrop_zero.py (partagé avec le CLI batch).


# Au-delà de cette durée, un cohort_jobs 'running' est considéré orphelin même
# si son PID semble vivant (couvre la réutilisation de PID par l'OS). Un recrop
# réel dépasse rarement quelques minutes.
_RECROP_MAX_RUNTIME_MIN = 60


def reap_orphan_cohort_jobs(store: Store) -> int:
    """Marque `failed` les `cohort_jobs` restés `running` dont le subprocess est
    mort (BUG-1 : zombie persisté). Appelé par le hook startup de server.py.

    Précis (vs le reaper brutal de source_runs) : un recrop tourne en subprocess
    DÉTACHÉ qui survit au `--reload` du worker → on ne tue QUE les jobs dont le
    PID n'existe plus (`os.kill(pid, 0)`), ou qui traînent au-delà de
    `_RECROP_MAX_RUNTIME_MIN` (garde anti-réutilisation de PID). Un job sans PID
    (ancien thread, ou subprocess pas encore enregistré) est traité comme mort.
    """
    conn = store._connection()  # noqa: SLF001
    rows = conn.execute(
        "SELECT id, pid, "
        "  CAST((julianday('now') - julianday(started_at)) * 24 * 60 AS REAL) AS age_min "
        "FROM cohort_jobs WHERE status='running'"
    ).fetchall()
    reaped = 0
    for r in rows:
        pid = r["pid"]
        age_min = r["age_min"] or 0.0
        alive = False
        if pid:
            try:
                os.kill(int(pid), 0)
                alive = True
            except PermissionError:
                alive = True  # existe mais pas à nous → vivant
            except (ProcessLookupError, OSError, ValueError):
                alive = False
        if alive and age_min < _RECROP_MAX_RUNTIME_MIN:
            continue
        reason = ("process restart — orphan job (reaped at boot)"
                  if not alive else
                  f"reaped at boot — running > {_RECROP_MAX_RUNTIME_MIN}min "
                  f"(pid {pid} suspect)")
        conn.execute(
            "UPDATE cohort_jobs SET status='failed', "
            "finished_at=COALESCE(finished_at, datetime('now')), "
            "error=COALESCE(error, ?) WHERE id=?",
            (reason, r["id"]),
        )
        reaped += 1
    return reaped


@router.post("/cohorts/{cohort_id}/coins/{eurio_id}/recrop-zero", status_code=202)
def recrop_zero_coin(cohort_id: str, eurio_id: str) -> dict:
    """Re-crope en arrière-plan les raws eBay zéro-crop d'UNE pièce (census+gate
    anti-fragment). Additif & sûr : ne touche que les raws sans crop présent,
    ``training_eligible=0`` → review humaine. Le front poll ``funnel-status``
    (les crops apparaissent) + l'endpoint status ci-dessous."""
    store = _get_store()
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    if eurio_id not in cohort.eurio_ids:
        raise HTTPException(status_code=404, detail="Pièce absente de la cohort")

    conn0 = store._connection()  # noqa: SLF001 — canonique (raws/crops)
    lconn = _get_local_store()._connection()  # noqa: SLF001 — cohort_jobs = bookkeeping local
    running = lconn.execute(
        "SELECT id FROM cohort_jobs WHERE kind='recrop_zero' AND eurio_id=? "
        "AND status='running' LIMIT 1",
        (eurio_id,),
    ).fetchone()
    if running:
        raise HTTPException(
            status_code=409,
            detail={"code": "recrop_already_running", "eurio_id": eurio_id},
        )
    run_id = f"recrop-zero-{eurio_id}"
    tau = float(os.environ.get("EURIO_CENSUS_FRAGMENT_TAU", "0.55"))
    # n_total = raws eBay zéro-crop dans le scope (même filtre que recrop_zero_for_coin)
    n_total = conn0.execute(
        "SELECT COUNT(*) FROM source_images si WHERE si.source='ebay' "
        "AND si.target_eurio_id=? AND si.storage_path IS NOT NULL "
        "AND (SELECT COUNT(*) FROM image_assets ia WHERE ia.source_image_id=si.id "
        "     AND ia.storage_status='present')=0",
        (eurio_id,),
    ).fetchone()[0]
    job_id = cohort_job_start(
        lconn, kind="recrop_zero", cohort_id=cohort_id, eurio_id=eurio_id,
        target_eurio_id=eurio_id, run_id=run_id, n_total=n_total, tau=tau,
    )

    # Exécution en SUBPROCESS DÉTACHÉ (pas un thread daemon) — le subprocess
    # possède le cycle de vie du job (progress + finish) via sa propre connexion.
    # Robustesse vs l'ancien thread (BUG-1 zombie) : (a) survit au `--reload` du
    # worker uvicorn (start_new_session → hors du groupe de signaux du worker) ;
    # (b) torch/MPS hors du worker ; (c) un crash réel clôt le job en `failed`
    # (visible in-row) ; (d) le reaper boot (reap_orphan_cohort_jobs) nettoie via
    # le PID. Précédent : ml/api/training_runner._run_subprocess.
    log_dir = _ML_DIR / "state" / "job_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"recrop-{job_id}.log"
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_ML_DIR) + (os.pathsep + existing if existing else "")
    cmd = [
        sys.executable, "scripts/recrop_cohort_census.py", "--commit",
        "--cohort", cohort_id, "--coin", eurio_id,
        "--job-id", job_id, "--run-id", run_id, "--tau", str(tau),
    ]
    # Direction A / Modèle B (C4b) : si EURIO_API_URL est configuré, le job
    # tourne toujours en compute local (GPU workstation) mais écrit les crops
    # sur une réplique pull-ée puis les POST au canonique VPS (--push), au
    # lieu d'écrire directement le eurio.db Mac. Le bookkeeping cohort_jobs
    # (progress/finish) reste local dans tous les cas (cf. recrop_cohort_census
    # ::_run_single_coin_job). En hébergé/Model A pur (pas d'EURIO_API_URL),
    # comportement inchangé (écriture locale directe).
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement
    if sync_enabled():
        cmd.append("--push")
    logf = log_path.open("w")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(_ML_DIR), env=env,
            stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True,  # détache du process-group du worker --reload
        )
    finally:
        logf.close()  # le child garde son propre fd ouvert
    cohort_job_set_pid(lconn, job_id, proc.pid)
    lconn.commit()
    logger.info("[recrop-zero] %s spawned subprocess pid=%s job=%s log=%s",
                eurio_id, proc.pid, job_id, log_path)
    return {"status": "started", "run_id": run_id, "eurio_id": eurio_id,
            "job_id": job_id, "n_total": n_total, "pid": proc.pid}


@router.get("/cohorts/{cohort_id}/coins/{eurio_id}/recrop-zero/status")
def recrop_zero_status(cohort_id: str, eurio_id: str) -> dict:
    """Statut du dernier job recrop-zero de la pièce, lu depuis cohort_jobs
    (persisté, survit au restart). ``idle`` si aucun job."""
    conn = _get_local_store()._connection()  # noqa: SLF001 — cohort_jobs = local
    row = conn.execute(
        "SELECT id, status, n_total, n_done, n_produced, tau, note, error, "
        "       started_at, finished_at, run_id "
        "FROM cohort_jobs WHERE kind='recrop_zero' AND eurio_id=? "
        "ORDER BY started_at DESC LIMIT 1",
        (eurio_id,),
    ).fetchone()
    return dict(row) if row is not None else {"status": "idle"}


def _reconcile_scrape_jobs(
    conn: sqlite3.Connection, lconn: sqlite3.Connection, cohort_id: str,
) -> None:
    """Réconcilie les `cohort_jobs` scrape 'running' depuis `source_runs` (BUG-3).

    Le scrape eBay s'exécute dans un thread sources : `source_runs` est la source
    de vérité (statut, compteurs, reaper « orphan run »). Le `cohort_jobs` scrape
    est une trace in-row du cockpit, ouverte au trigger et **projetée en lecture**
    depuis le run lié — pas de thread lab fragile, survit au `--reload`, et un run
    `failed` devient visible in-row.

    ``conn`` = canonique (``source_runs``/``coins``/``image_assets``, lecture) ;
    ``lconn`` = store d'état LOCAL (``cohort_jobs``, lecture+écriture). Autocommit
    des deux côtés (isolation_level=None).
    """
    jobs = lconn.execute(
        "SELECT id, run_id, target_eurio_id FROM cohort_jobs "
        "WHERE cohort_id=? AND kind='scrape_ebay' AND status='running'",
        (cohort_id,),
    ).fetchall()
    for j in jobs:
        if not j["run_id"]:
            continue
        run = conn.execute(
            "SELECT status, n_raws_added, n_crops_added, error_summary "
            "FROM source_runs WHERE id=?",
            (j["run_id"],),
        ).fetchone()
        if run is None:
            continue
        if run["status"] == "running":
            # Avancement live : crops produits jusqu'ici.
            lconn.execute(
                "UPDATE cohort_jobs SET n_done=?, n_produced=?, "
                "n_total=COALESCE(n_total, ?) WHERE id=?",
                (run["n_crops_added"], run["n_crops_added"],
                 run["n_raws_added"], j["id"]),
            )
            continue
        # Terminal (success/partial/failed) → clôture le job + diag honnête.
        # Attribution au niveau de la CLASSE (design_group) : un scrape de
        # standard nourrit une classe ArcFace (be-2007 + be-1999 = t1), pas un
        # eurio_id isolé. On compte les crops produits par ce run dont le *prior*
        # (source_images.target_eurio_id) tombe dans la même classe que la cible.
        # Pour un coin sans design_group (commémo), classe = eurio_id → identique
        # à l'ancien comptage (rétro-compatible).
        n_attr = 0
        target_class = j["target_eurio_id"]
        if j["target_eurio_id"]:
            tc = conn.execute(
                "SELECT COALESCE(design_group_id, eurio_id) FROM coins WHERE eurio_id=?",
                (j["target_eurio_id"],),
            ).fetchone()
            if tc:
                target_class = tc[0]
            n_attr = conn.execute(
                "SELECT COUNT(*) FROM image_assets ia "
                "JOIN source_images si ON si.id = ia.source_image_id "
                "LEFT JOIN coins c ON c.eurio_id = si.target_eurio_id "
                "WHERE ia.run_id = ? "
                "AND COALESCE(c.design_group_id, c.eurio_id) = ?",
                (j["run_id"], target_class),
            ).fetchone()[0]
        status = "done" if run["status"] in ("success", "partial") else "failed"
        note = None
        if status == "done" and j["target_eurio_id"] and (run["n_crops_added"] or 0) > 0:
            if n_attr > 0:
                note = (f"{run['n_crops_added']} crops produits, {n_attr} pour la "
                        f"classe « {target_class} »")
            else:
                note = (f"{run['n_crops_added']} crops produits, 0 pour la classe "
                        f"« {target_class} » — offre eBay ~nulle pour cette ère ; "
                        "le reste est attribué aux autres classes du pays (utile pour "
                        "elles), cette classe s'entraîne sur Numista augmenté")
        lconn.execute(
            "UPDATE cohort_jobs SET status=?, n_total=COALESCE(n_total, ?), "
            "n_done=?, n_produced=?, n_attributed_target=?, "
            "note=COALESCE(note, ?), error=COALESCE(error, ?), "
            "finished_at=COALESCE(finished_at, datetime('now')) WHERE id=?",
            (status, run["n_raws_added"], run["n_raws_added"],
             run["n_crops_added"], n_attr, note, run["error_summary"], j["id"]),
        )


@router.get("/cohorts/{cohort_id}/jobs")
def cohort_jobs_list(cohort_id: str) -> dict:
    """Jobs observables de la cohorte (scrape/recrop), récents d'abord.
    Source du statut + barre de progression in-row du cockpit (corrige B2)."""
    conn = _get_store()._connection()  # noqa: SLF001 — canonique (source_runs/coins)
    lconn = _get_local_store()._connection()  # noqa: SLF001 — cohort_jobs = local
    _reconcile_scrape_jobs(conn, lconn, cohort_id)  # projette source_runs → cohort_jobs
    rows = lconn.execute(
        "SELECT id, kind, eurio_id, target_eurio_id, status, n_total, n_done, "
        "       n_produced, n_attributed_target, tau, note, error, "
        "       started_at, finished_at FROM cohort_jobs "
        "WHERE cohort_id=? ORDER BY started_at DESC LIMIT 100",
        (cohort_id,),
    ).fetchall()
    return {"cohort_id": cohort_id, "jobs": [dict(r) for r in rows]}


def _cohort_discard_summary(store: Store, cohort_id: str) -> dict:
    """Cœur (testable offline) de ``GET /lab/cohorts/{id}/discard-summary``.

    Agrège ``discarded_listings`` scopé aux eurio_ids de la cohort (source='ebay')
    par reason_class + is_rescue_candidate. Les raisons ``commemo_in_standard_run:*``
    sont normalisées en ``commemo_in_standard_run`` pour éviter une explosion de
    lignes (51 valeurs distinctes sur la prod actuelle).

    Retourne : ``{cohort_id, total, rows, rescue_total, noise_total, ambiguous_total}``.
    ``rows`` est trié par n desc.
    """
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    eurio_ids = cohort.eurio_ids
    if not eurio_ids:
        return {
            "cohort_id": cohort_id,
            "total": 0,
            "rows": [],
            "rescue_total": 0,
            "noise_total": 0,
            "ambiguous_total": 0,
        }

    conn = store._connection()  # noqa: SLF001
    ph = ",".join("?" * len(eurio_ids))
    raw_rows = conn.execute(
        f"""
        SELECT reason, is_rescue_candidate, COUNT(*) AS n
          FROM discarded_listings
         WHERE source = 'ebay'
           AND target_eurio_id IN ({ph})
         GROUP BY reason, is_rescue_candidate
        """,
        list(eurio_ids),
    ).fetchall()

    # Normalise + agrège : commemo_in_standard_run:* → 'commemo_in_standard_run'.
    from collections import defaultdict
    agg: dict[tuple[str, int | None], int] = defaultdict(int)
    for row in raw_rows:
        reason_class = (
            "commemo_in_standard_run"
            if str(row["reason"]).startswith("commemo_in_standard_run:")
            else str(row["reason"])
        )
        key = (reason_class, row["is_rescue_candidate"])
        agg[key] += int(row["n"])

    rows = [
        {
            "reason_class": reason_class,
            "n": n,
            "is_rescue_candidate": flag,
        }
        for (reason_class, flag), n in sorted(agg.items(), key=lambda kv: -kv[1])
    ]
    total = sum(r["n"] for r in rows)
    rescue_total = sum(r["n"] for r in rows if r["is_rescue_candidate"] == 1)
    noise_total = sum(r["n"] for r in rows if r["is_rescue_candidate"] == 0)
    ambiguous_total = sum(r["n"] for r in rows if r["is_rescue_candidate"] is None)
    return {
        "cohort_id": cohort_id,
        "total": total,
        "rows": rows,
        "rescue_total": rescue_total,
        "noise_total": noise_total,
        "ambiguous_total": ambiguous_total,
    }


@router.get("/cohorts/{cohort_id}/discard-summary")
def cohort_discard_summary(cohort_id: str) -> dict:
    """Agrégat des rejets eBay scopé aux pièces de la cohort (C2).

    Normalise les raisons ``commemo_in_standard_run:*`` en une seule classe.
    Retourne ``rescue_total`` / ``noise_total`` / ``ambiguous_total`` pour
    alimenter le widget §C3 du tiroir CohortDrawerEbay."""
    return _cohort_discard_summary(_get_store(), cohort_id)


def _cohort_rescue_candidates(store: Store, cohort_id: str) -> dict:
    """Cœur (testable offline) de ``GET /lab/cohorts/{id}/rescue-candidates``.

    Retourne un détail par eurio_id avec les IDs individuels de chaque
    ``discarded_listings`` récupérable (``is_rescue_candidate=1``). Contrairement
    à ``_cohort_discard_summary`` (agrégat normalisé §C3), ce endpoint expose les
    ``id`` individuels pour l'action 1-clic Reclasser (C5).

    Séparation noise : lignes à ``target_eurio_id IS NULL`` ou sans
    ``is_rescue_candidate=1`` pour les raisons non commemo → comptées dans
    ``noise_by_reason`` (section bruit readonly).

    Pour les ``commemo_in_standard_run:<eid>`` : l'``eid`` embarqué dans la raison
    est l'eurio_id cible réel (la pièce commémo qui apparaissait dans un run
    standard). On rattache ces discards à l'eurio_id cible extraite de la raison.
    """
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")

    eurio_ids = cohort.eurio_ids
    if not eurio_ids:
        return {
            "cohort_id": cohort_id,
            "per_class": [],
            "noise_total": 0,
            "noise_by_reason": [],
        }

    conn = store._connection()  # noqa: SLF001
    ph = ",".join("?" * len(eurio_ids))

    # Récupère toutes les lignes discarded scopées à la cohort + les commemo
    # dont l'eid embarqué est dans la cohort (target_eurio_id=NULL côté standard run).
    # On doit aussi capturer les commemo dont le target_eurio_id n'est pas dans la
    # cohort mais dont le eurio_id embarqué l'est.
    raw_rows = conn.execute(
        f"""
        SELECT id, reason, target_eurio_id, is_rescue_candidate, rescued_source_image_id
          FROM discarded_listings
         WHERE source = 'ebay'
           AND (
             target_eurio_id IN ({ph})
             OR (
               reason LIKE 'commemo_in_standard_run:%'
               AND SUBSTR(reason, INSTR(reason, ':') + 1) IN ({ph})
             )
           )
        """,
        list(eurio_ids) + list(eurio_ids),
    ).fetchall()

    from collections import defaultdict

    # Structure : per_eurio_id → {reason → {n, is_rescue, ids[]}}
    # Pour une ligne commemo, l'eurio_id clé est celui embarqué dans la raison.
    per_eurio: dict[str, dict] = defaultdict(lambda: defaultdict(
        lambda: {"n": 0, "is_rescue_candidate": False, "discard_ids": []}
    ))
    noise_by_reason: dict[str, int] = defaultdict(int)
    noise_ids: set[str] = set()

    for row in raw_rows:
        reason: str = str(row["reason"])
        is_rescue = bool(row["is_rescue_candidate"])
        row_id: str = row["id"]
        already_rescued = row["rescued_source_image_id"] is not None

        # Commemo dans un run standard → l'eid est dans la raison
        if reason.startswith("commemo_in_standard_run:"):
            embedded_eid = reason[len("commemo_in_standard_run:"):]
            if embedded_eid in eurio_ids:
                # Rescue candidate si l'eid cible est dans la cohort
                bucket = per_eurio[embedded_eid][reason]
                bucket["n"] += 1
                bucket["is_rescue_candidate"] = True
                # Ne propose le rescue que si pas encore rescué
                if not already_rescued:
                    bucket["discard_ids"].append(row_id)
                continue

        # Autres raisons rattachables via target_eurio_id
        target: str | None = row["target_eurio_id"]
        if target and target in eurio_ids:
            if is_rescue:
                bucket = per_eurio[target][reason]
                bucket["n"] += 1
                bucket["is_rescue_candidate"] = True
                if not already_rescued:
                    bucket["discard_ids"].append(row_id)
            else:
                # Rejet non-récupérable rattaché à une pièce → bruit
                noise_by_reason[reason] += 1
                noise_ids.add(row_id)
        else:
            # target NULL (non attribuable proprement) → bruit
            noise_by_reason[reason] += 1
            noise_ids.add(row_id)

    # Construit la liste per_class triée par nombre de discards desc
    per_class = []
    for eid, reasons_map in per_eurio.items():
        by_reason = []
        rescue_count = 0
        total = 0
        for reason, bucket in reasons_map.items():
            n = bucket["n"]
            total += n
            is_rescue_candidate = bucket["is_rescue_candidate"]
            discard_ids = bucket["discard_ids"]
            # rescue_eurio_id : pour commemo c'est l'eid lui-même (= la pièce ciblée)
            rescue_eurio_id = eid if is_rescue_candidate else None
            by_reason.append({
                "reason": reason,
                "n": n,
                "is_rescue_candidate": is_rescue_candidate,
                "rescue_eurio_id": rescue_eurio_id,
                "discard_ids": discard_ids,
            })
            if is_rescue_candidate:
                rescue_count += len(discard_ids)
        by_reason.sort(key=lambda x: -x["n"])
        per_class.append({
            "eurio_id": eid,
            "total_discards": total,
            "by_reason": by_reason,
            "rescue_count": rescue_count,
        })
    per_class.sort(key=lambda x: -x["total_discards"])

    # noise_by_reason trié desc, dédupliqué (on compte les lignes pas les ids)
    noise_by_reason_list = [
        {"reason": r, "n": n}
        for r, n in sorted(noise_by_reason.items(), key=lambda kv: -kv[1])
    ]

    return {
        "cohort_id": cohort_id,
        "per_class": per_class,
        "noise_total": len(noise_ids),
        "noise_by_reason": noise_by_reason_list,
    }


@router.get("/cohorts/{cohort_id}/rescue-candidates")
def cohort_rescue_candidates(cohort_id: str) -> dict:
    """Détail des rejets eBay récupérables (C5), groupé par eurio_id.

    Contrairement à ``/discard-summary`` (agrégat normalisé pour §C3), expose
    les ``id`` individuels des ``discarded_listings`` pour l'action 1-clic
    Reclasser dans le tiroir §C5 CohortDrawerRescue.
    Inclut uniquement les discards pas encore rescués (``rescued_source_image_id IS NULL``)."""
    return _cohort_rescue_candidates(_get_store(), cohort_id)


@router.post("/discarded/{discard_id}/rescue")
def rescue_discard(discard_id: str) -> dict:
    """Reclasse un ``discarded_listings`` vers son eurio_id cible (C5).

    Insère dans ``source_images`` si absent (dédup sur ``source + source_ref``).
    Idempotent : un second appel retourne ``already_existed=true``.
    Marque la ligne ``discarded_listings.rescued_source_image_id`` pour éviter
    qu'elle réapparaisse dans les rescue candidates.

    Note : l'image est reclassée en base, mais aucun crop ne sera généré
    automatiquement. L'utilisateur doit déclencher un re-crop explicitement."""
    store = _get_store()
    conn = store._connection()  # noqa: SLF001

    row = conn.execute(
        "SELECT * FROM discarded_listings WHERE id = ?", (discard_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="discard_id introuvable")

    source: str = row["source"]
    source_ref: str = row["source_ref"]
    run_id: str | None = row["run_id"]
    reason: str = str(row["reason"])

    # Résout l'eurio_id cible
    if reason.startswith("commemo_in_standard_run:"):
        target_eurio_id = reason[len("commemo_in_standard_run:"):]
    else:
        target_eurio_id = row["target_eurio_id"]

    if not target_eurio_id:
        raise HTTPException(
            status_code=422,
            detail="Impossible de déterminer l'eurio_id cible pour ce discard.",
        )

    # Vérifie si déjà rescué
    if row["rescued_source_image_id"] is not None:
        return {
            "discard_id": discard_id,
            "eurio_id": target_eurio_id,
            "n_persisted": 0,
            "already_existed": True,
        }

    # Vérifie si la source_image existe déjà (dédup sur source+source_ref)
    existing = conn.execute(
        "SELECT id FROM source_images WHERE source = ? AND source_ref = ?",
        (source, source_ref),
    ).fetchone()

    if existing is not None:
        # Marque le discard comme rescué
        conn.execute(
            "UPDATE discarded_listings SET rescued_source_image_id = ? WHERE id = ?",
            (existing["id"], discard_id),
        )
        conn.commit()
        return {
            "discard_id": discard_id,
            "eurio_id": target_eurio_id,
            "n_persisted": 0,
            "already_existed": True,
        }

    # Insère dans source_images
    new_id = uuid.uuid4().hex
    title = row["title"]
    raw_payload = row["raw_payload"]
    conn.execute(
        """
        INSERT INTO source_images (
            id, source, source_ref, target_eurio_id, listing_title,
            raw_payload_json, run_id, download_status, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'))
        """,
        (new_id, source, source_ref, target_eurio_id, title, raw_payload, run_id),
    )
    # Marque le discard comme rescué
    conn.execute(
        "UPDATE discarded_listings SET rescued_source_image_id = ? WHERE id = ?",
        (new_id, discard_id),
    )
    conn.commit()

    return {
        "discard_id": discard_id,
        "eurio_id": target_eurio_id,
        "n_persisted": 1,
        "already_existed": False,
    }


# ─── Augmentations (Sprint 1) ──────────────────────────────────────────────


def _launch_aug_bake(iteration_id: str, *, clear: bool) -> dict:
    """Lance le bake d'augmentation en subprocess DÉTACHÉ via le rail `jobs/`.

    Garde de concurrence : si un bake de CETTE itération tourne déjà (PID vivant),
    on renvoie son job existant au lieu d'en lancer un 2e (le bouton Générer peut
    être recliqué). Retourne ``{job_id, status}``."""
    store = _get_store()
    conn = store._connection()  # noqa: SLF001
    existing = jobs.job_by_param(conn, "iteration_id", iteration_id, kind="augmentation")
    if existing and existing["status"] == "running":
        pid = existing.get("pid")
        if pid and jobs._pid_alive(pid):  # noqa: SLF001
            return {"job_id": existing["id"], "status": "running"}
    extra = ["--clear"] if clear else []
    res = jobs.launch(
        conn,
        kind="augmentation",
        cmd_builder=lambda jid: [
            sys.executable, str(_ML_DIR / "training" / "run_augmentation.py"),
            "--iteration-id", iteration_id, "--job-id", jid, *extra,
        ],
        params={"iteration_id": iteration_id},
    )
    return {"job_id": res["job_id"], "status": "running"}


@router.post("/cohorts/{cohort_id}/preview-iteration", status_code=202)
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

    # Bake (or refresh) the snapshot in a DETACHED job (clear first so a recipe
    # change produces fresh samples). 202 → le front poll le statut puis re-fetch
    # la galerie. Le bake survit au `--reload` et ne bloque plus la requête.
    bake = _launch_aug_bake(it.id, clear=True)
    return {
        "iteration_id": it.id,
        "name": it.name,
        "augmentations_seed": it.augmentations_seed,
        "recipe_id": it.recipe_id,
        "variant_count": it.variant_count,
        "job_id": bake["job_id"],
        "status": "baking",
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


@router.post(
    "/cohorts/{cohort_id}/iterations/{iteration_id}/augmentations/regenerate",
    status_code=202,
)
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
    # Bake détaché (clear + génération). 202 → le front poll `…/augmentations/job`.
    bake = _launch_aug_bake(iteration_id, clear=True)
    return {"iteration_id": iteration_id, "job_id": bake["job_id"], "status": "baking"}


@router.get("/cohorts/{cohort_id}/iterations/{iteration_id}/augmentations/job")
def augmentation_job_status(cohort_id: str, iteration_id: str) -> dict:
    """Statut du bake d'augmentation détaché de l'itération (poll par le front).
    `idle` si aucun bake n'a (encore) été lancé."""
    job = jobs.job_by_param(
        _get_store()._connection(), "iteration_id", iteration_id, kind="augmentation",  # noqa: SLF001
    )
    if job is None:
        return {"status": "idle"}
    return {
        "status": job["status"],
        "n_total": job["n_total"],
        "n_done": job["n_done"],
        "note": job["note"],
        "error": job["error"],
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
# Promoted prod model (phase 4) — populated by scripts.promote_iteration.
_TFLITE_PATH = _ML_DIR / "prod" / "current" / "tflite" / "eurio_embedder_v1.tflite"


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
LIVE_TEST_CONDITIONS = {"bright", "dim", "tilt", "glare", "inhand"}


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
    # R@1 de vérité = maille design_group (le modèle prédit des labels de
    # groupe ; le strict eurio_id ne peut structurellement jamais matcher).
    # On expose aussi le strict à titre informatif.
    correct = sum(1 for r in rows if r.is_correct_eq)
    correct_strict = sum(1 for r in rows if r.is_correct)
    live_r1 = correct / total if total > 0 else None
    live_r1_strict = correct_strict / total if total > 0 else None
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
        "correct_strict": correct_strict,
        "recall_at_1": live_r1,
        "recall_at_1_strict": live_r1_strict,
        "studio_r_at_1": studio_r1,
        "delta": delta,
    }


def _best_of_representative(
    frames: list[IterationLiveTestRow], eq_map,
) -> IterationLiveTestRow:
    """Collapse all frames of one test_idx into a single best-of row.

    Each frame is graded server-side (never trust the on-device flag, cf.
    bc17d955): ``strict`` = exact eurio_id match, ``eq`` = design_group
    equivalence. The representative is the argmax frame by
    ``(strict, eq, similarity)`` — so:

      * ``is_correct`` (= rep.strict) equals OR(strict) over frames, and
      * ``is_correct_eq`` (= rep.eq) equals OR(eq) over frames

    (strict ⊆ eq, since an exact match is always equivalent). Best-of: the
    test counts correct if ANY re-scan got it, and the shown prediction is the
    frame that earned the verdict (or the most-confident miss when all fail).
    """
    def _graded(row: IterationLiveTestRow) -> tuple[bool, bool, float]:
        pred = row.predicted_top1
        strict = pred is not None and pred == row.expected_eurio_id
        eq = bool(eq_map.are_equivalent(pred, row.expected_eurio_id))
        sim = row.similarity_top1 if row.similarity_top1 is not None else float("-inf")
        return strict, eq, sim

    rep = max(frames, key=_graded)
    strict, eq, _ = _graded(rep)
    rep.is_correct = strict
    rep.is_correct_eq = eq
    return rep


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
    # Verdict recomputé server-side sur la maille COALESCE(design_group,
    # eurio_id) — on ne fait JAMAIS confiance au flag on-device (l'APK de scan
    # peut précéder un fix de la règle de verdict, cf. bc17d955). Parité avec
    # le matcher Android + feedback_output_contract_parity.md.
    from training.eval.equivalence import build_equivalence_map

    eq_map = build_equivalence_map(db_path=store.db_path)
    parse_errors: list[str] = []

    # A coin is often re-scanned several times → multiple JSONL frames share one
    # test_idx. Group them and collapse each group to ONE representative row so
    # prediction and verdict always come from the same frame (cf. the historical
    # desync bug). Canonical policy = **best-of**: a test counts correct if ANY
    # frame got it. `_best_of_representative` picks the argmax frame by
    # (strict, eq, similarity), which makes the stored verdict equal the OR over
    # frames while keeping the displayed prediction coherent.
    frames_by_test: dict[int, list[IterationLiveTestRow]] = {}
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
            frames_by_test.setdefault(row.test_idx, []).append(row)

    inserted = 0
    skipped_dupe = 0  # existing test rows replaced (resync idempotency signal)
    for frames in frames_by_test.values():
        rep = _best_of_representative(frames, eq_map)
        if store.upsert_live_test(rep):
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
