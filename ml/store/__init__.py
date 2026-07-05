"""Store SQLite local (eurio.db). Façade ré-assemblant Store depuis le socle
connexion + les mixins métier (un module par domaine). Importer `from store import Store`.

Issu du split de state/store.py (refacto ML chunks 5a/5b). `state/store.py` reste
un shim de compat jusqu'à la migration des imports (chunk 7).
"""

from __future__ import annotations

import os
from pathlib import Path

from .augmentation import AugmentationMixin, AugmentationRecipeRow, AugmentationRunRow
from .benchmark import BenchmarkMixin, BenchmarkRunRow
from .cohort_jobs import (
    cohort_job_finish,
    cohort_job_progress,
    cohort_job_set_pid,
    cohort_job_start,
)
from .cohorts import CohortsMixin, ExperimentCohortRow
from .common import ClassRef
from .connection import StoreBase, _SCHEMA_PATH, _register_phash_udfs
from .dino import DinoMixin, DinoPredictionRow
from .dino_references import (
    DinoRefRow,
    clear_reference_override,
    get_class_references,
    get_reference_overrides,
    get_references_for_assets,
    replace_auto_references,
    set_reference_override,
)
from .events import emit_field_event, emit_state_event
from .iterations import (
    AugVsRealRow,
    ExperimentIterationRow,
    IterationLiveTestRow,
    IterationsMixin,
)
from .listing_signals import ListingSignalsMixin, ListingTextSignalsRow
from .runs import ClassMetricRow, EpochRow, RunRow, RunsMixin, StepRow
from .staging import StagingMixin
from .training_scan import (
    ScanResultRow,
    latest_training_scan,
    training_scan_dismiss_intruder,
    training_scan_finish,
    training_scan_progress,
    training_scan_results,
    training_scan_set_pid,
    training_scan_start,
    training_scan_upsert_results,
)


class Store(
    StoreBase,
    RunsMixin,
    StagingMixin,
    AugmentationMixin,
    BenchmarkMixin,
    CohortsMixin,
    IterationsMixin,
    DinoMixin,
    ListingSignalsMixin,
):
    """SQLite store for local training state (WAL, autocommit, single eurio.db)."""


def resolve_db_path(default: str | Path) -> Path:
    """Chemin de la DB locale, honorant ``EURIO_DB_PATH`` (Model B : le compute
    lit la réplique pointée par l'env, pas un fichier codé en dur).

    À utiliser par TOUS les entrypoints détachés (``training/run_*.py``) pour
    qu'ils ouvrent la MÊME DB que le serveur. Sinon le serveur lit la réplique
    (``EURIO_DB_PATH``) mais le subprocess lit ``state/eurio.db`` → l'itération
    créée via le serveur est « introuvable » côté bake/training. Fallback sur
    ``default`` quand l'env est absent (dev local sans réplique)."""
    env = os.environ.get("EURIO_DB_PATH", "").strip()
    return Path(env) if env else Path(default)


def resolve_local_state_db() -> Path:
    """Chemin d'une DB locale **inscriptible** distincte de la réplique read-only,
    pour l'état d'observabilité qui ne voyage PAS au canonique (``cohort_jobs``,
    ``cohort_training_scans*``). Honore ``EURIO_LOCAL_STATE_DB``, défaut
    ``ml/state/eurio.local.db``. Ne pointe JAMAIS la réplique — reste writable même
    sous ``EURIO_DB_READONLY=1``.

    ⚠️ Le câblage complet des writers/readers de bookkeeping sur cette DB est une
    précondition documentée du flip (les tables sont aujourd'hui JOINTES avec des
    tables canoniques — cf. ``store/decisions.py`` — donc un split physique exige
    ATTACH ou une décision d'archi). Ce resolver pose l'infrastructure."""
    env = os.environ.get("EURIO_LOCAL_STATE_DB", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "state" / "eurio.local.db"


def staging_store(*, prefix: str = "eurio-staging-") -> "Store":
    """Réplique SCRATCH **inscriptible** (tempfile dédié) pour stager un run avant
    ``push_run`` — JAMAIS le cache autopull ``eurio.replica.db`` (course avec le
    thread/timer de pull). ``read_only=False`` explicite → reste writable sous
    ``EURIO_DB_READONLY=1``. Modèle : ``scripts/backfill_dino_predictions.py``.

    Le scratch vit dans un ``tempfile.mkdtemp`` (nettoyé par l'OS / best-effort) ;
    l'appelant le jette après push. Retourne un ``Store`` ouvert sur le scratch."""
    import tempfile

    from client.replica import pull_replica

    scratch = Path(tempfile.mkdtemp(prefix=prefix)) / "eurio_scratch.db"
    pull_replica(dest=scratch)
    return Store(scratch, read_only=False)


def resolve_db_readonly() -> bool:
    """Lit ``EURIO_DB_READONLY`` (Direction A, C5) : vrai → la DB locale (une
    réplique pull-ée du VPS) s'ouvre en ``mode=ro`` et le bootstrap est no-op.
    CÂBLÉ (durcissement post-C5) : ``StoreBase.__init__`` résout ce flag par
    défaut — tout Store construit sans ``read_only`` explicite l'honore. Le
    writer canonique (``serving/server_serve.py``) passe ``read_only=False``
    explicite. Opt-in : le défaut sans env var reste False (écriture locale,
    dev Model A)."""
    from .connection import _env_readonly

    return _env_readonly()


__all__ = [
    "AugVsRealRow",
    "AugmentationRecipeRow",
    "AugmentationRunRow",
    "BenchmarkRunRow",
    "ClassMetricRow",
    "ClassRef",
    "DinoPredictionRow",
    "DinoRefRow",
    "EpochRow",
    "ExperimentCohortRow",
    "ExperimentIterationRow",
    "IterationLiveTestRow",
    "ListingTextSignalsRow",
    "RunRow",
    "ScanResultRow",
    "StepRow",
    "Store",
    "StoreBase",
    "cohort_job_finish",
    "cohort_job_progress",
    "cohort_job_set_pid",
    "cohort_job_start",
    "clear_reference_override",
    "get_class_references",
    "get_reference_overrides",
    "get_references_for_assets",
    "replace_auto_references",
    "set_reference_override",
    "emit_field_event",
    "emit_state_event",
    "resolve_db_readonly",
    "resolve_local_state_db",
    "staging_store",
    "latest_training_scan",
    "training_scan_dismiss_intruder",
    "resolve_db_path",
    "training_scan_finish",
    "training_scan_progress",
    "training_scan_results",
    "training_scan_set_pid",
    "training_scan_start",
    "training_scan_upsert_results",
]
