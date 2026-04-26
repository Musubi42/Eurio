"""Lab iteration orchestrator (PRD Bloc 4).

Chains recipe → training → benchmark for one iteration at a time, computes
verdict + delta against the parent iteration, and survives API restarts by
recovering iterations stuck in 'training' or 'benchmarking' state at boot.

Only one iteration global runs at a time — enforced by a process-wide lock.
The M4 can only produce one best_model.pth at a time anyway (shared
checkpoint path), so parallel iterations would collide.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from state import ClassRef, ExperimentIterationRow, Store

from .iteration_logic import compute_delta, compute_input_diff, compute_verdict
from .training_runner import TrainingRunner

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
CHECKPOINTS_DIR = ML_DIR / "checkpoints"
DEFAULT_TRAINING_CONFIG = {
    "epochs": 40,
    "batch_size": 256,
    "m_per_class": 4,
}


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class IterationRunner:
    """Orchestrate one Lab iteration: stage + train + bench + verdict.

    Not thread-safe for multiple concurrent iterations. Callers must ensure
    only one iteration is launched at a time (we enforce via ``_global_lock``).
    """

    POLL_INTERVAL_SEC = 5.0

    def __init__(self, store: Store, training_runner: TrainingRunner):
        self._store = store
        self._training_runner = training_runner
        self._global_lock = threading.Lock()  # only one iteration at a time

    # ─── Public API ────────────────────────────────────────────────────

    def is_busy(self) -> bool:
        return self._global_lock.locked()

    def create_and_launch(
        self,
        *,
        cohort_id: str,
        name: str,
        hypothesis: str | None,
        parent_iteration_id: str | None,
        recipe_id: str | None,
        variant_count: int,
        training_config: dict,
        iteration_id: str | None = None,
    ) -> ExperimentIterationRow:
        """Persist the iteration row and kick off the background chain.

        Returns immediately with the freshly-created iteration (status=pending).
        The chain transitions status → training → benchmarking → completed.
        """
        if self.is_busy():
            raise RuntimeError(
                "Une itération est déjà en cours — une seule à la fois."
            )

        cohort = self._store.get_cohort(cohort_id)
        if cohort is None:
            raise ValueError(f"Cohort {cohort_id!r} introuvable")
        if not cohort.eurio_ids:
            raise ValueError("Cohort vide — ajoute des eurio_ids avant d'itérer.")

        if recipe_id is not None and self._store.get_recipe(recipe_id) is None:
            raise ValueError(f"Recipe {recipe_id!r} introuvable")

        if parent_iteration_id is not None:
            parent = self._store.get_iteration(parent_iteration_id)
            if parent is None or parent.cohort_id != cohort_id:
                raise ValueError(
                    "parent_iteration_id ne pointe pas sur une itération du cohort"
                )

        iid = iteration_id or uuid.uuid4().hex[:12]
        row = ExperimentIterationRow(
            id=iid,
            cohort_id=cohort_id,
            parent_iteration_id=parent_iteration_id,
            name=name,
            hypothesis=hypothesis,
            recipe_id=recipe_id,
            variant_count=variant_count,
            training_config=training_config,
            status="pending",
            verdict="pending",
        )
        self._store.create_iteration(row)

        thread = threading.Thread(
            target=self._run_chain, args=(iid,), daemon=True
        )
        thread.start()
        return row

    def recover_on_boot(self) -> int:
        """Re-queue iterations stuck in training/benchmarking state.

        Returns the number of resumed iterations.
        """
        resumed = 0
        for status in ("training", "benchmarking"):
            for it in self._store.list_iterations(status=status):
                logger.info(
                    "Resuming iteration %s (status=%s) after API restart",
                    it.id, status,
                )
                thread = threading.Thread(
                    target=self._run_chain, args=(it.id,), daemon=True
                )
                thread.start()
                resumed += 1
        return resumed

    # ─── Internal chain ─────────────────────────────────────────────────

    def _run_chain(self, iteration_id: str) -> None:
        """End-to-end orchestrator. Acquires the global lock; releases on exit."""
        acquired = self._global_lock.acquire(blocking=False)
        if not acquired:
            logger.warning(
                "Iteration %s waited for the global lock — this should not happen",
                iteration_id,
            )
            self._global_lock.acquire()
        try:
            self._chain_steps(iteration_id)
        finally:
            self._global_lock.release()

    def _chain_steps(self, iteration_id: str) -> None:
        it = self._store.get_iteration(iteration_id)
        if it is None:
            logger.error("Iteration %s disappeared from the store", iteration_id)
            return

        cohort = self._store.get_cohort(it.cohort_id)
        if cohort is None:
            self._fail(iteration_id, "cohort absent au démarrage")
            return

        self._store.update_iteration(
            iteration_id, started_at=_iso_now(),
        )

        # Phase 1 — Training
        training_run_id = it.training_run_id
        if training_run_id is None:
            try:
                training_run_id = self._launch_training(it, cohort.eurio_ids)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Training launch failed for iteration %s", iteration_id)
                self._fail(iteration_id, f"Lancement training: {exc}")
                return
            self._store.update_iteration(
                iteration_id,
                status="training",
                training_run_id=training_run_id,
            )
        else:
            self._store.update_iteration(iteration_id, status="training")

        if not self._wait_training(training_run_id):
            run = self._store.get_run(training_run_id)
            self._fail(
                iteration_id,
                f"Training {training_run_id} failed: {run.error if run else 'unknown'}",
            )
            return

        # Phase 2 — Benchmark
        benchmark_run_id = self._store.get_iteration(iteration_id).benchmark_run_id
        if benchmark_run_id is None:
            try:
                benchmark_run_id = self._launch_benchmark(
                    it, cohort.eurio_ids, training_run_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Benchmark launch failed for iteration %s", iteration_id)
                self._fail(iteration_id, f"Lancement benchmark: {exc}")
                return
            self._store.update_iteration(
                iteration_id,
                status="benchmarking",
                benchmark_run_id=benchmark_run_id,
            )
        else:
            self._store.update_iteration(iteration_id, status="benchmarking")

        if not self._wait_benchmark(benchmark_run_id):
            bench = self._store.get_benchmark_run(benchmark_run_id)
            self._fail(
                iteration_id,
                f"Benchmark {benchmark_run_id} failed: {bench.error if bench else 'unknown'}",
            )
            return

        # Phase 3 — Verdict + delta
        self._finalize(iteration_id)

    # ─── Training ───────────────────────────────────────────────────────

    def _launch_training(
        self, iteration: ExperimentIterationRow, eurio_ids: list[str]
    ) -> str:
        """Stage the cohort as classes and kick off a training run.

        Bypasses the `/training/stage` table — pushes refs directly into the
        runner. This means ad-hoc stagings from /coins don't interfere.
        """
        config = dict(DEFAULT_TRAINING_CONFIG)
        config.update(iteration.training_config or {})
        config["target_augmented"] = iteration.variant_count
        if iteration.recipe_id:
            config["aug_recipe"] = iteration.recipe_id

        added = [ClassRef(eid, "eurio_id") for eid in eurio_ids]
        run = self._training_runner.start_run(added=added, removed=[], config=config)
        if iteration.recipe_id:
            recipe = self._store.get_recipe(iteration.recipe_id)
            if recipe is not None:
                self._store.update_run_aug_recipe(run.id, recipe.id)
        return run.id

    def _wait_training(self, run_id: str) -> bool:
        while True:
            run = self._store.get_run(run_id)
            if run is None:
                return False
            if run.status == "completed":
                return True
            if run.status == "failed":
                return False
            time.sleep(self.POLL_INTERVAL_SEC)

    # ─── Benchmark ──────────────────────────────────────────────────────

    def _launch_benchmark(
        self,
        iteration: ExperimentIterationRow,
        eurio_ids: list[str],
        training_run_id: str,
    ) -> str:
        """Spawn `evaluate_real_photos.py` as a subprocess.

        Uses the same daemon-thread + subprocess pattern as
        ``benchmark_routes._launch_run`` — we don't go through the HTTP route
        to stay self-contained.
        """
        run_id = uuid.uuid4().hex[:12]
        model_path = CHECKPOINTS_DIR / "best_model.pth"
        cmd = [
            VENV_PYTHON,
            str(ML_DIR / "evaluate_real_photos.py"),
            "--model",
            str(model_path),
            "--run-id",
            run_id,
            "--eurio-ids",
            ",".join(eurio_ids),
            "--top-confusions",
            "20",
        ]
        if iteration.recipe_id:
            cmd.extend(["--recipe-id", iteration.recipe_id])

        def _run() -> None:
            try:
                result = subprocess.run(
                    cmd, cwd=str(ML_DIR), capture_output=True, text=True,
                )
                if result.returncode != 0:
                    error = (
                        result.stderr.strip()
                        or result.stdout.strip()
                        or f"exit {result.returncode}"
                    )
                    existing = self._store.get_benchmark_run(run_id)
                    if existing is not None:
                        self._store.update_benchmark_run(
                            run_id,
                            status="failed",
                            error=error,
                            finished_at=_iso_now(),
                        )
                    else:
                        # Script died before inserting the row — write a stub.
                        from state import BenchmarkRunRow
                        self._store.create_benchmark_run(
                            BenchmarkRunRow(
                                id=run_id,
                                model_path=str(model_path),
                                model_name="unknown",
                                report_path="",
                                status="failed",
                                error=error,
                                finished_at=_iso_now(),
                            )
                        )
                else:
                    # Close the traceability loop: stamp training_run_id on
                    # the benchmark row the script just created.
                    self._store.update_benchmark_run(
                        run_id, training_run_id=training_run_id,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Benchmark subprocess crashed")
                from state import BenchmarkRunRow
                existing = self._store.get_benchmark_run(run_id)
                if existing is not None:
                    self._store.update_benchmark_run(
                        run_id, status="failed", error=str(exc),
                        finished_at=_iso_now(),
                    )
                else:
                    self._store.create_benchmark_run(
                        BenchmarkRunRow(
                            id=run_id,
                            model_path=str(model_path),
                            model_name="unknown",
                            report_path="",
                            status="failed",
                            error=str(exc),
                            finished_at=_iso_now(),
                        )
                    )

        threading.Thread(target=_run, daemon=True).start()
        return run_id

    def _wait_benchmark(self, run_id: str) -> bool:
        while True:
            row = self._store.get_benchmark_run(run_id)
            if row is None:
                time.sleep(self.POLL_INTERVAL_SEC)
                continue
            if row.status == "completed":
                return True
            if row.status == "failed":
                return False
            time.sleep(self.POLL_INTERVAL_SEC)

    # ─── Finalize ───────────────────────────────────────────────────────

    def _finalize(self, iteration_id: str) -> None:
        it = self._store.get_iteration(iteration_id)
        if it is None or it.benchmark_run_id is None:
            self._fail(iteration_id, "benchmark manquant au finalize")
            return

        bench = self._store.get_benchmark_run(it.benchmark_run_id)
        if bench is None:
            self._fail(iteration_id, "benchmark row disparue")
            return

        parent_metrics: dict | None = None
        parent_inputs: dict | None = None
        if it.parent_iteration_id:
            parent = self._store.get_iteration(it.parent_iteration_id)
            if parent and parent.benchmark_run_id:
                parent_bench = self._store.get_benchmark_run(parent.benchmark_run_id)
                if parent_bench is not None:
                    parent_metrics = parent_bench.to_dict()
                    parent_inputs = self._snapshot_inputs(parent)

        iter_metrics = bench.to_dict()
        iter_inputs = self._snapshot_inputs(it)

        verdict = compute_verdict(iter_metrics, parent_metrics)
        delta = compute_delta(iter_metrics, parent_metrics)
        diff = compute_input_diff(iter_inputs, parent_inputs)

        self._store.update_iteration(
            iteration_id,
            status="completed",
            verdict=verdict,
            delta_vs_parent=delta,
            diff_from_parent=diff,
            finished_at=_iso_now(),
        )

    def _snapshot_inputs(self, iteration: ExperimentIterationRow) -> dict:
        """Build the full inputs snapshot (with recipe config resolved)."""
        recipe_config: dict | None = None
        if iteration.recipe_id:
            recipe = self._store.get_recipe(iteration.recipe_id)
            if recipe is not None:
                recipe_config = recipe.config
        return {
            "recipe": recipe_config,
            "variant_count": iteration.variant_count,
            "training_config": iteration.training_config,
        }

    def _fail(self, iteration_id: str, error: str) -> None:
        self._store.update_iteration(
            iteration_id,
            status="failed",
            error=error,
            finished_at=_iso_now(),
        )


# ─── Module-level bind (same pattern as augmentation/benchmark routes) ─────

_runner: IterationRunner | None = None


def bind(store: Store, training_runner: TrainingRunner) -> IterationRunner:
    global _runner
    _runner = IterationRunner(store, training_runner)
    return _runner


def get_runner() -> IterationRunner:
    if _runner is None:
        raise RuntimeError("iteration_runner.bind() not called")
    return _runner
