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
import random
import shutil
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
DATASETS_DIR = ML_DIR / "datasets"
ITERATION_TRAIN_ROOTS = DATASETS_DIR / "iterations"
DEFAULT_TRAINING_CONFIG = {
    "epochs": 40,
    "batch_size": 256,
    "m_per_class": 4,
}

_SEED_MAX = 2**31 - 1


def _generate_seed() -> int:
    return random.randint(0, _SEED_MAX)


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

    def stop(self, iteration_id: str) -> dict:
        """Cooperatively stop a running iteration.

        Sends SIGTERM to the active training subprocess and waits up to 30s
        before escalating to SIGKILL. The iteration is then marked
        ``failed`` with a status-specific error message. The chain thread
        will see the failed run and release the global lock on its own.

        Callers must check status (``training``/``benchmarking``) themselves —
        the runner just acts.
        """
        outcome = self._training_runner.stop_active(graceful_timeout=30.0)
        if outcome == "idle":
            # Nothing to terminate (e.g. the iteration was between training
            # and benchmark, or the process already finished). Mark the
            # iteration failed anyway so the user's intent is reflected.
            self._fail(iteration_id, "Stopped by user (no active subprocess)")
            return {"outcome": outcome, "marked_failed": True}
        msg = (
            "Stopped by user (graceful)"
            if outcome == "graceful"
            else "Stopped by user (forced)"
        )
        self._fail(iteration_id, msg)
        return {"outcome": outcome, "marked_failed": True}

    def create_iteration(
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
        augmentations_seed: int | None = None,
    ) -> ExperimentIterationRow:
        """Persist the iteration row WITHOUT starting any background work.

        The new explicit two-phase flow (2026-04-30) means iterations are
        created `pending`, the user generates augmentations explicitly,
        then calls :meth:`launch_training` when ready. This method only
        validates inputs and inserts the row.
        """
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
        seed = augmentations_seed if augmentations_seed is not None else _generate_seed()
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
            augmentations_seed=seed,
        )
        self._store.create_iteration(row)
        return row

    def launch_training(self, iteration_id: str) -> ExperimentIterationRow:
        """Start the training → benchmark → verdict chain on a pending iteration.

        Pre-conditions:
          - iteration exists and is in status ``pending``
          - augmentations are baked on disk for every coin in the cohort
            (caller checks via :func:`iteration_augmentations.list_for_iteration`
            or relies on the explicit "Generate" UI step)
          - runner is not busy

        The chain itself is identical to the legacy ``create_and_launch`` —
        we just decouple the trigger so the user can preview augmentations
        before committing to a 30-minute training run.
        """
        from training.iteration_augmentations import list_for_iteration

        iteration = self._store.get_iteration(iteration_id)
        if iteration is None:
            raise ValueError(f"Iteration {iteration_id!r} introuvable")
        if iteration.status != "pending":
            raise RuntimeError(
                f"Iteration en status '{iteration.status}' — "
                "lancer le training n'est valide que pour 'pending'."
            )
        cohort = self._store.get_cohort(iteration.cohort_id)
        if cohort is None:
            raise ValueError("cohort introuvable")

        # Verify augmentations exist on disk for at least one coin —
        # otherwise the chain would just bake them inline (idempotent path
        # in `iteration_augmentations.generate_for_iteration`) which
        # defeats the whole "explicit generate then launch" UX.
        per_coin = list_for_iteration(
            iteration_id=iteration_id, store=self._store,
        )
        total = sum(len(c.get("samples", [])) for c in per_coin)
        if total == 0:
            raise RuntimeError(
                "Aucune augmentation bakée pour cette itération — "
                "clique « Générer » avant de lancer le training."
            )

        if self.is_busy():
            raise RuntimeError(
                "Une itération est déjà en cours — une seule à la fois."
            )

        thread = threading.Thread(
            target=self._run_chain, args=(iteration_id,), daemon=True
        )
        thread.start()
        return iteration

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

        # Phase 1.5 — TFLite export (Sprint 4)
        # The cohort-test:bundle script needs a TFLite whose mtime is ≥
        # iteration.finished_at, otherwise it bails out with exit 4. Doing
        # this inline removes the manual `python -m training.export_tflite`
        # step from the loop. We don't fail the iteration on export failure
        # — the training is still valid, the user can re-export by hand and
        # bundle later.
        try:
            self._export_tflite(iteration_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "TFLite export failed for iteration %s: %s "
                "(iteration continues; cohortTest bundle will need a manual export)",
                iteration_id, exc,
            )

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
        """Bake persistent augmentations + kick off a training run.

        Sprint 1 / D-004 — augmentations are pre-baked on disk under
        ``ml/datasets/<nid>/augmentations/<iid>/sample_*.jpg``, with a
        symlinked staging root at ``ml/datasets/iterations/<iid>/<eurio_id>/``
        used as the ImageFolder dataset path. ``train_embedder.py`` is then
        run with ``--prebaked-augmentations`` so the recipe layer is bypassed.
        """
        from training.iteration_augmentations import (
            ITERATION_TRAIN_ROOTS,
            generate_for_iteration,
        )

        reports = generate_for_iteration(iteration_id=iteration.id, store=self._store)
        skipped = [r for r in reports if r.skipped_reason]
        if skipped:
            details = "; ".join(
                f"{r.eurio_id} ({r.skipped_reason})" for r in skipped
            )
            raise RuntimeError(f"Augmentations skipped for: {details}")
        total_written = sum(r.written for r in reports)
        logger.info(
            "Iteration %s: baked %d augmentation samples across %d coin(s)",
            iteration.id, total_written, len(reports),
        )

        config = dict(DEFAULT_TRAINING_CONFIG)
        config.update(iteration.training_config or {})
        config["target_augmented"] = iteration.variant_count
        config["prebaked_augmentations"] = True
        config["dataset_override"] = str(ITERATION_TRAIN_ROOTS / iteration.id)
        if iteration.recipe_id:
            config["aug_recipe"] = iteration.recipe_id

        added = [ClassRef(eid, "eurio_id") for eid in eurio_ids]
        run = self._training_runner.start_run(added=added, removed=[], config=config)
        if iteration.recipe_id:
            recipe = self._store.get_recipe(iteration.recipe_id)
            if recipe is not None:
                self._store.update_run_aug_recipe(run.id, recipe.id)
        return run.id

    def _export_tflite(self, iteration_id: str) -> None:
        """Run ``python -m training.export_tflite`` after a successful training.

        Produces ``ml/output/eurio_embedder_v1.tflite`` (+ model_meta.json)
        from the latest ``ml/checkpoints/best_model.pth``. Sprint 3 left this
        as a manual step; Sprint 4 wires it inline so the bundle script
        always sees a fresh mtime.

        We log stdout/stderr but don't fail the iteration if the subprocess
        errors — see ``_chain_steps`` for the rationale.
        """
        cmd = [
            VENV_PYTHON, "-m", "training.export_tflite",
            "--model", str(CHECKPOINTS_DIR / "best_model.pth"),
            "--output-dir", str(ML_DIR / "output"),
        ]
        logger.info(
            "Iteration %s: exporting TFLite via %s", iteration_id, " ".join(cmd),
        )
        result = subprocess.run(
            cmd, cwd=str(ML_DIR), capture_output=True, text=True,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip() or "no output"
            raise RuntimeError(f"export_tflite exit {result.returncode}: {err}")
        logger.info(
            "Iteration %s: TFLite export OK (%d bytes stdout)",
            iteration_id, len(result.stdout),
        )

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
