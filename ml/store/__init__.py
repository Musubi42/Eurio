"""Store SQLite local (eurio.db). Façade ré-assemblant Store depuis le socle
connexion + les mixins métier (un module par domaine). Importer `from store import Store`.

Issu du split de state/store.py (refacto ML chunks 5a/5b). `state/store.py` reste
un shim de compat jusqu'à la migration des imports (chunk 7).
"""

from __future__ import annotations

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
from .events import emit_state_event
from .iterations import (
    AugVsRealRow,
    ExperimentIterationRow,
    IterationLiveTestRow,
    IterationsMixin,
)
from .listing_signals import ListingSignalsMixin, ListingTextSignalsRow
from .runs import ClassMetricRow, EpochRow, RunRow, RunsMixin, StepRow
from .staging import StagingMixin


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


__all__ = [
    "AugVsRealRow",
    "AugmentationRecipeRow",
    "AugmentationRunRow",
    "BenchmarkRunRow",
    "ClassMetricRow",
    "ClassRef",
    "DinoPredictionRow",
    "EpochRow",
    "ExperimentCohortRow",
    "ExperimentIterationRow",
    "IterationLiveTestRow",
    "ListingTextSignalsRow",
    "RunRow",
    "StepRow",
    "Store",
    "StoreBase",
    "cohort_job_finish",
    "cohort_job_progress",
    "cohort_job_set_pid",
    "cohort_job_start",
    "emit_state_event",
]
