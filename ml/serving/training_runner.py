"""Training runner — one retrain per run, many classes in one retrain.

ArcFace has no incremental add: every added (or removed) class triggers a
full retrain of the model on the complete class set. This runner reflects
that reality:

  - `start_run(added, removed)` creates a single `TrainingRun` that covers
    all requested mutations in one pipeline execution.
  - Only one run may be active at a time; a second `start_run` raises.
  - Persistence lives in the SQLite Store (`state/eurio.db`). History,
    logs, per-epoch metrics, and per-class metrics all survive process
    restarts.

Refacto-ml chunk 2 :
  - 2a : l'orchestration des 6 étapes vit dans `training.pipeline.TrainingPipeline`.
  - 2b : `start_run` lance le pipeline en **subprocess détaché** (`run_pipeline.py`
    via le rail `jobs/`) → survit au `--reload`. L'état se lit via `training_runs`
    + la row `jobs` + le fichier de log. Plus aucune exécution in-process ici :
    le Lab (IterationRunner) exécute `TrainingPipeline` directement dans SON propre
    process détaché (`run_iteration.py`), via `create_run_row` + le pipeline.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

import jobs
from jobs import _pid_alive
from store import (
    ClassMetricRow,
    ClassRef,
    EpochRow,
    RunRow,
    StepRow,
    Store,
)
from training.pipeline import DEFAULT_CONFIG, ML_DIR, STEPS, VENV_PYTHON, _read_current_classes

RUN_PIPELINE_SCRIPT = str(ML_DIR / "training" / "run_pipeline.py")


class TrainingRunner:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._device = "auto"  # forwarded to train_embedder.py --device; resolves cuda/mps/cpu
        self._rehydrate()

    # ─── Config ──────────────────────────────────────────────────────────

    @property
    def device(self) -> str:
        return self._device

    @device.setter
    def device(self, value: str) -> None:
        self._device = value

    # ─── Active-run resolution (detached) ────────────────────────────────

    def _active_run(self) -> RunRow | None:
        """The currently running/queued run (only one is active globally)."""
        for st in ("running", "queued"):
            runs = self._store.list_runs(status=st)
            if runs:
                return runs[0]
        return None

    def _job_for(self, run_id: str) -> dict | None:
        return jobs.job_by_param(jobs.connection(), "run_id", run_id)

    def _tail_job_log(self, run_id: str, n: int) -> list[str]:
        job = self._job_for(run_id)
        if not job or not job.get("log_path"):
            return []
        p = Path(job["log_path"])
        if not p.exists():
            return []
        return p.read_text(errors="replace").splitlines()[-n:]

    # ─── Public query API ────────────────────────────────────────────────

    def active_run(self) -> RunRow | None:
        return self._active_run()

    def active_snapshot(self) -> dict | None:
        d = self._active_run()
        if d is None:
            return None
        cur = max((e.epoch for e in self._store.list_epochs(d.id)), default=0)
        total = int(d.config.get("epochs", 40)) if d.config else 40
        return {"run_id": d.id, "epoch": cur, "epochs_total": total}

    def get_run(self, run_id: str) -> RunRow | None:
        return self._store.get_run(run_id)

    def list_runs(self, *, limit: int = 50, offset: int = 0) -> list[RunRow]:
        return self._store.list_runs(limit=limit, offset=offset)

    def count_runs(self, *, status: str | None = None) -> int:
        return self._store.count_runs(status=status)

    def list_steps(self, run_id: str) -> list[StepRow]:
        return self._store.list_steps(run_id)

    def list_epochs(self, run_id: str) -> list[EpochRow]:
        return self._store.list_epochs(run_id)

    def list_run_classes(self, run_id: str) -> list[ClassMetricRow]:
        return self._store.list_classes_for_run(run_id)

    def list_runs_for_class(self, class_id: str):
        return self._store.list_runs_for_class(class_id)

    def load_logs(self, run_id: str) -> list[str]:
        archived = self._store.load_logs(run_id)
        if archived:
            return archived
        # Detached run still streaming → archive not written yet; read its log file.
        return self._tail_job_log(run_id, n=10_000)

    def tail_logs(self, n: int = 30) -> list[str]:
        """Up to ``n`` most recent stdout lines of the active run (job log tail)."""
        d = self._active_run()
        if d is None:
            return []
        return self._tail_job_log(d.id, n)

    def current_classes(self) -> list[ClassRef]:
        return _read_current_classes()

    # ─── Run-row creation (shared with IterationRunner's detached chain) ──

    def create_run_row(
        self,
        *,
        added: list[ClassRef],
        removed: list[ClassRef],
        config: dict | None = None,
    ) -> RunRow:
        """Create the `training_runs` row (status='queued') + 6 'pending' steps.
        Does NOT launch anything — the caller runs the pipeline (detached for the
        /runs path, in-process inside the detached iteration chain)."""
        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg.update({k: v for k, v in config.items() if v is not None})

        classes_before = _read_current_classes()
        removed_ids = {c.class_id for c in removed}
        added_map = {c.class_id: c for c in added}
        classes_after_map: dict[str, ClassRef] = {
            c.class_id: c for c in classes_before if c.class_id not in removed_ids
        }
        for class_id, ref in added_map.items():
            classes_after_map[class_id] = ref
        classes_after = sorted(classes_after_map.values(), key=lambda c: c.class_id)

        run_id = uuid.uuid4().hex[:8]
        version = self._store.next_version()
        row = RunRow(
            id=run_id,
            version=version,
            status="queued",
            config=cfg,
            classes_before=classes_before,
            classes_after=classes_after,
            classes_added=list(added),
            classes_removed=list(removed),
        )
        self._store.create_run(row)
        for i, name in enumerate(STEPS):
            self._store.upsert_step(
                run_id, StepRow(step_index=i, name=name, status="pending")
            )
        return row

    # ─── Public mutation API — DETACHED (legacy /runs path) ──────────────

    def start_run(
        self,
        *,
        added: list[ClassRef],
        removed: list[ClassRef],
        config: dict | None = None,
    ) -> RunRow:
        """Create a run and launch the pipeline in a DETACHED subprocess (survives
        `--reload`). The API only enqueues + reads status afterwards."""
        if self.active_run() is not None:
            raise RuntimeError("A training run is already active")
        row = self.create_run_row(added=added, removed=removed, config=config)
        run_id = row.id
        jobs.launch(
            jobs.connection(),
            kind="training",
            cmd_builder=lambda jid: [
                VENV_PYTHON, RUN_PIPELINE_SCRIPT,
                "--run-id", run_id, "--device", self._device, "--job-id", jid,
            ],
            params={"run_id": run_id},
        )
        return row

    # ─── Boot reconciliation ─────────────────────────────────────────────

    def _rehydrate(self) -> None:
        """Fail leftover 'running' runs whose process is gone. A DETACHED run
        whose job PID is still alive survived the reload → left untouched."""
        from training.pipeline import _now_iso

        conn = jobs.connection()
        for r in self._store.list_runs(status="running"):
            job = jobs.job_by_param(conn, "run_id", r.id)
            pid = job.get("pid") if job else None
            if pid and _pid_alive(pid):
                continue  # detached run survived the reload
            self._store.update_run_status(
                r.id, "failed",
                error="Interrupted by API restart", finished_at=_now_iso(),
            )
