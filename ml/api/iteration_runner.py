"""Lab iteration orchestrator (PRD Bloc 4).

Architecture (rewritten 2026-05-01) :

  - **Two decoupled phases** : ``_do_training_phase`` (training + TFLite
    export) ends with ``iteration.status='completed'``. ``_do_benchmark_phase``
    runs the studio benchmark and is independent of the iteration's global
    status — its outcome lives in ``benchmark_run`` rows + ``i4.studio.state``.
  - **Default UX still chained** : :meth:`launch_training` runs both phases
    one after the other in a single thread, so the user keeps the
    "one click → R@1" experience. :meth:`launch_benchmark` runs the
    benchmark phase only, on an iteration already ``completed``.
  - **Single global lock** : only one chain runs at a time (training or
    benchmark — they share the GPU and the ``best_model.pth`` file).
  - **Per-iteration log buffer** : every subprocess (training, export,
    benchmark) appends lines to a per-iteration ring buffer, exposed via
    :meth:`tail_logs` for the live monitor. Survives phase transitions —
    fixes the previous bug where logs vanished when entering benchmark.
  - **Streamed subprocesses** : export and benchmark used to be run via
    ``subprocess.run(capture_output=True)`` (silent). They now stream
    line-by-line through :meth:`_run_subprocess_streamed`, so a crash
    leaves a real trail in the log buffer.
  - **Status updated before spawn** : DB transitions are written before
    we kick off the matching subprocess (so a chain thread crash leaves
    a state that recover-on-boot can heal, not a phantom). A top-level
    try/except in each chain forces ``_fail`` if anything escapes the
    inner phase methods. NB: there's still a brief window between the
    DB update and the spawn — recovery handles that on the next boot.
  - **Recovery is cleanup, not retry** : an iteration stuck in ``training``
    after an API restart is marked ``failed``; one stuck in ``benchmarking``
    is marked ``completed`` with the benchmark row failed (so I4a surfaces
    the failure). The user re-launches manually — auto-retry is more
    dangerous than helpful.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import random
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from state import ClassRef, ExperimentIterationRow, Store

from .iteration_logic import compute_delta, compute_input_diff, compute_verdict
from .training_runner import TrainingRunner

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
DATASETS_DIR = ML_DIR / "datasets"
LAB_ITERATIONS_DIR = ML_DIR / "lab" / "iterations"


def _iter_dir(iteration_id: str) -> Path:
    """Per-iteration root under ``ml/lab/iterations/<iid>/`` (phase 2)."""
    return LAB_ITERATIONS_DIR / iteration_id


def _iter_model_path(iteration_id: str) -> Path:
    return _iter_dir(iteration_id) / "checkpoints" / "best_model.pth"
ITERATION_TRAIN_ROOTS = DATASETS_DIR / "iterations"
DEFAULT_TRAINING_CONFIG = {
    "epochs": 40,
    "batch_size": 256,
    "m_per_class": 4,
}

_SEED_MAX = 2**31 - 1


def _generate_seed() -> int:
    return random.randint(0, _SEED_MAX)


PROGRESS_DIR = ML_DIR / "state" / "training_progress"


def _set_progress_phase(iteration_id: str, phase: str, **extra: object) -> None:
    """Patch ``ml/state/training_progress/<iid>.json`` with a new phase.

    Used by the runner around training (bake/export/benchmark/done/failed).
    Inside the training loop, ``train_embedder.py`` writes per-epoch payloads
    with ``phase=training``. We merge into whatever exists so we don't drop
    metrics already written by the subprocess.
    """
    fp = PROGRESS_DIR / f"{iteration_id}.json"
    payload: dict = {}
    if fp.exists():
        try:
            payload = json.loads(fp.read_text())
        except Exception:
            payload = {}
    payload.update({
        "schema_version": payload.get("schema_version", 1),
        "iteration_id": iteration_id,
        "phase": phase,
        "updated_at": _iso_now(),
        **extra,
    })
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(fp)


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
    LOG_BUFFER_MAX = 500
    STOP_GRACEFUL_TIMEOUT_SEC = 30.0

    def __init__(self, store: Store, training_runner: TrainingRunner):
        self._store = store
        self._training_runner = training_runner
        self._global_lock = threading.Lock()  # only one iteration at a time

        # Per-iteration log buffer. Owns the lifecycle: subprocess output
        # (training stream from TrainingRunner via log_sink, plus export
        # and benchmark via _run_subprocess_streamed) all go through here.
        self._iter_logs: dict[str, deque[str]] = {}
        self._iter_logs_lock = threading.Lock()

        # Active subprocess tracker (export, benchmark). Training subprocess
        # is owned by TrainingRunner — its stop() is dispatched separately.
        self._active_subprocess: subprocess.Popen | None = None
        self._active_subprocess_lock = threading.Lock()

    # ─── Per-iteration log buffer ─────────────────────────────────────

    def _append_log(self, iteration_id: str, line: str) -> None:
        with self._iter_logs_lock:
            buf = self._iter_logs.get(iteration_id)
            if buf is None:
                buf = deque(maxlen=self.LOG_BUFFER_MAX)
                self._iter_logs[iteration_id] = buf
            buf.append(line)

    def tail_logs(self, iteration_id: str, n: int = 30) -> list[str]:
        """Return up to ``n`` most recent log lines for an iteration.

        Covers all phases: training, TFLite export, studio benchmark.
        Empty list when no chain has run for this iteration yet (or the
        runner was rebooted since).

        Held under ``_iter_logs_lock`` only long enough to slice the
        deque tail (``itertools.islice`` from ``len-n`` to ``len``) —
        avoids materializing the full 500-line buffer while concurrent
        appenders contend for the lock.
        """
        with self._iter_logs_lock:
            buf = self._iter_logs.get(iteration_id)
            if buf is None:
                return []
            start = max(0, len(buf) - n)
            return list(itertools.islice(buf, start, len(buf)))

    def _reset_logs(self, iteration_id: str) -> None:
        with self._iter_logs_lock:
            self._iter_logs.pop(iteration_id, None)

    # ─── Public API ────────────────────────────────────────────────────

    @property
    def training_runner(self) -> TrainingRunner:
        """Public accessor — kept for backwards compat (used to be called
        for log tailing; now logs are read via :meth:`tail_logs`)."""
        return self._training_runner

    def is_busy(self) -> bool:
        return self._global_lock.locked()

    def stop(self, iteration_id: str) -> dict:
        """Cooperatively stop a running iteration.

        Tries to terminate the active subprocess (training, export, or
        benchmark — whichever is running). Returns a dict with ``outcome``
        ∈ {``graceful``, ``forced``, ``idle``} and ``marked_failed``
        (whether the iteration was transitioned to ``failed``).

        Only iterations in a transient state (``training``/``benchmarking``)
        are marked failed; if the iteration has already reached a terminal
        state (``completed``/``failed``/``pending``) we don't touch it —
        avoids racing a chain thread that just legitimately transitioned.
        """
        # 1) Training subprocess (owned by TrainingRunner)
        outcome = self._training_runner.stop_active(
            graceful_timeout=self.STOP_GRACEFUL_TIMEOUT_SEC,
        )
        if outcome != "idle":
            self._fail(iteration_id, f"Stopped by user ({outcome})")
            return {"outcome": outcome, "marked_failed": True}

        # 2) Our own subprocess (export or benchmark)
        outcome = self._stop_active_subprocess(
            graceful_timeout=self.STOP_GRACEFUL_TIMEOUT_SEC,
        )
        if outcome != "idle":
            self._fail(iteration_id, f"Stopped by user ({outcome})")
            return {"outcome": outcome, "marked_failed": True}

        # 3) Nothing alive. Only fail if the iteration is genuinely
        #    in a transient state — otherwise we'd race a chain thread
        #    that just transitioned to a terminal state.
        it = self._store.get_iteration(iteration_id)
        if it is None:
            return {"outcome": "idle", "marked_failed": False}
        if it.status in ("training", "benchmarking"):
            self._fail(iteration_id, "Stopped by user (no active subprocess)")
            return {"outcome": "idle", "marked_failed": True}
        return {"outcome": "idle", "marked_failed": False}

    def _stop_active_subprocess(self, *, graceful_timeout: float) -> str:
        """Terminate the active export/benchmark subprocess if any.

        Returns the same vocabulary as :meth:`TrainingRunner.stop_active`.
        """
        with self._active_subprocess_lock:
            proc = self._active_subprocess
        if proc is None or proc.poll() is not None:
            return "idle"
        try:
            proc.terminate()
        except ProcessLookupError:
            return "idle"
        try:
            proc.wait(timeout=graceful_timeout)
            return "graceful"
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return "forced"

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
        """Spawn the chained ``training → export → benchmark`` flow.

        Pre-conditions:
          - iteration exists and is in status ``pending``
          - augmentations are baked on disk for every coin in the cohort
          - runner is not busy

        Default UX: a single click runs both phases (training+export, then
        benchmark). The benchmark is best-effort — if it fails, the
        iteration still finishes ``completed`` and the failure is recorded
        on the benchmark row (surfaced via ``i4.studio.state='partial'``).
        """
        iteration = self._validate_for_launch_training(iteration_id)
        if self.is_busy():
            raise RuntimeError(
                "Une itération est déjà en cours — une seule à la fois."
            )

        thread = threading.Thread(
            target=self._run_full_chain,
            args=(iteration_id,),
            daemon=True,
        )
        thread.start()
        return iteration

    def launch_benchmark(self, iteration_id: str) -> ExperimentIterationRow:
        """Re-run (or first-run) the studio benchmark on a trained iteration.

        Pre-conditions:
          - iteration exists and is in status ``completed`` (training+export OK)
          - the training checkpoint (``best_model.pth``) is still on disk —
            we don't validate this, the subprocess will fail loudly if not
          - runner is not busy

        Use case: training succeeded but the chained benchmark crashed (or
        the user added new device captures and wants a fresh measurement
        without re-training).
        """
        iteration = self._validate_for_launch_benchmark(iteration_id)
        if self.is_busy():
            raise RuntimeError(
                "Une itération est déjà en cours — une seule à la fois."
            )

        thread = threading.Thread(
            target=self._run_benchmark_chain,
            args=(iteration_id,),
            daemon=True,
        )
        thread.start()
        return iteration

    def _validate_for_launch_training(
        self, iteration_id: str,
    ) -> ExperimentIterationRow:
        from training.iteration_augmentations import list_for_iteration

        iteration = self._store.get_iteration(iteration_id)
        if iteration is None:
            raise ValueError(f"Iteration {iteration_id!r} introuvable")
        if iteration.status != "pending":
            raise RuntimeError(
                f"Iteration en status '{iteration.status}' — "
                "lancer le training n'est valide que pour 'pending'."
            )
        if self._store.get_cohort(iteration.cohort_id) is None:
            raise ValueError("cohort introuvable")

        per_coin = list_for_iteration(
            iteration_id=iteration_id, store=self._store,
        )
        target = iteration.variant_count
        missing = [
            c["eurio_id"]
            for c in per_coin
            if len(c.get("samples", [])) < target
        ]
        if missing:
            raise RuntimeError(
                f"Augmentations manquantes ou incomplètes pour "
                f"{len(missing)} pièce(s) : {', '.join(missing[:5])}"
                + (f" (+ {len(missing) - 5} autres)" if len(missing) > 5 else "")
                + " — clique « Générer » avant de lancer le training."
            )
        return iteration

    def _validate_for_launch_benchmark(
        self, iteration_id: str,
    ) -> ExperimentIterationRow:
        iteration = self._store.get_iteration(iteration_id)
        if iteration is None:
            raise ValueError(f"Iteration {iteration_id!r} introuvable")
        if iteration.status != "completed":
            raise RuntimeError(
                f"Iteration en status '{iteration.status}' — "
                "le benchmark studio ne peut être (re)lancé que sur "
                "une iteration 'completed' (training + export OK)."
            )
        if iteration.training_run_id is None:
            raise RuntimeError(
                "Iteration sans training_run_id — état incohérent, "
                "impossible de relier le benchmark."
            )
        if self._store.get_cohort(iteration.cohort_id) is None:
            raise ValueError("cohort introuvable")
        return iteration

    def recover_on_boot(self) -> int:
        """Mark stuck iterations as terminal at API boot.

        We don't auto-retry: the orchestrator daemon thread that died
        leaves disk + DB in an unknown state, and resuming blindly is
        more dangerous than helpful (could re-bake mid-flight, trigger
        a duplicate training, etc.). The user re-launches explicitly.

        Returns the number of cleaned-up iterations.
        """
        cleaned = 0
        # Training-stuck → mark failed (no usable model to point at).
        for it in self._store.list_iterations(status="training"):
            logger.info(
                "Recovery: iteration %s stuck in training → failed", it.id,
            )
            self._store.update_iteration(
                it.id,
                status="failed",
                error="Interrupted by API restart",
                finished_at=_iso_now(),
            )
            _set_progress_phase(it.id, "failed", error="Interrupted by API restart")
            cleaned += 1
        # Benchmark-stuck → training+export had completed; the model is
        # usable. Promote the iteration to ``completed`` and mark the
        # benchmark row failed so I4a surfaces the partial state.
        for it in self._store.list_iterations(status="benchmarking"):
            logger.info(
                "Recovery: iteration %s stuck in benchmarking → completed "
                "(benchmark partial)", it.id,
            )
            self._store.update_iteration(
                it.id,
                status="completed",
                finished_at=it.finished_at or _iso_now(),
            )
            if it.benchmark_run_id:
                row = self._store.get_benchmark_run(it.benchmark_run_id)
                if row is not None and row.status not in ("completed", "failed"):
                    self._store.update_benchmark_run(
                        it.benchmark_run_id,
                        status="failed",
                        error="Interrupted by API restart",
                        finished_at=_iso_now(),
                    )
            _set_progress_phase(
                it.id, "benchmark_failed",
                error="Interrupted by API restart",
            )
            cleaned += 1
        return cleaned

    # ─── Chain orchestrators ────────────────────────────────────────────

    def _run_full_chain(self, iteration_id: str) -> None:
        """training+export → benchmark, single global lock for the whole."""
        acquired = self._global_lock.acquire(blocking=False)
        if not acquired:
            logger.warning(
                "Iteration %s waited for the global lock — this should not happen",
                iteration_id,
            )
            self._global_lock.acquire()
        try:
            try:
                trained = self._do_training_phase(iteration_id)
            except Exception as exc:  # noqa: BLE001 — last-resort safety net
                logger.exception(
                    "Unhandled error in training phase for %s", iteration_id,
                )
                self._fail(iteration_id, f"Erreur training: {exc}")
                return

            if not trained:
                # _do_training_phase already _fail'd
                return

            try:
                self._do_benchmark_phase(iteration_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Unhandled error in benchmark phase for %s", iteration_id,
                )
                # Training succeeded — don't taint the iteration. Surface
                # the failure on the benchmark side only.
                self._record_benchmark_phase_failure(iteration_id, str(exc))
        finally:
            self._global_lock.release()

    def _run_benchmark_chain(self, iteration_id: str) -> None:
        """Benchmark only, on a 'completed' iteration.

        Resets the per-iteration log buffer at entry so a relaunch
        doesn't show stale lines from the original training/benchmark
        run (which may have happened hours ago). The chained variant
        (:meth:`_run_full_chain`) resets at the start of training, so
        either way the buffer reflects the current launch only.

        Re-validates the iteration's status after acquiring the global
        lock: if two ``launch_benchmark`` requests slipped past the
        pre-check (validation runs before the lock is taken), the
        loser's status check would now see ``'benchmarking'`` (set by
        the winner) and bail rather than overwrite a fresh
        benchmark_run_id.
        """
        acquired = self._global_lock.acquire(blocking=False)
        if not acquired:
            logger.warning(
                "Iteration %s waited for the global lock — this should not happen",
                iteration_id,
            )
            self._global_lock.acquire()
        try:
            it = self._store.get_iteration(iteration_id)
            if it is None:
                logger.error("Iteration %s disappeared from store", iteration_id)
                return
            if it.status != "completed":
                logger.warning(
                    "Iteration %s status changed to '%s' while waiting for "
                    "the lock — abandoning benchmark relaunch",
                    iteration_id, it.status,
                )
                return
            self._reset_logs(iteration_id)
            try:
                self._do_benchmark_phase(iteration_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Unhandled error in benchmark chain for %s", iteration_id,
                )
                self._record_benchmark_phase_failure(iteration_id, str(exc))
        finally:
            self._global_lock.release()

    # ─── Training phase ────────────────────────────────────────────────

    def _do_training_phase(self, iteration_id: str) -> bool:
        """Run training subprocess + TFLite export.

        Returns True on success (iteration now ``completed``); False on
        failure (already passed through ``_fail``). Caller does not need
        to re-handle.
        """
        it = self._store.get_iteration(iteration_id)
        if it is None:
            logger.error("Iteration %s disappeared from the store", iteration_id)
            return False
        cohort = self._store.get_cohort(it.cohort_id)
        if cohort is None:
            self._fail(iteration_id, "cohort absent au démarrage")
            return False

        # Fresh log buffer for this chain. Previous content (e.g. old
        # benchmark relaunch) is irrelevant once a new training starts.
        self._reset_logs(iteration_id)
        self._append_log(
            iteration_id,
            f"[runner] Iteration {iteration_id}: starting training phase",
        )

        # Atomic transition: status BEFORE spawn.
        self._store.update_iteration(
            iteration_id,
            status="training",
            started_at=_iso_now(),
        )
        _set_progress_phase(iteration_id, "bake")

        # Bake + spawn training subprocess
        try:
            training_run_id = self._launch_training(it, cohort.eurio_ids)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Training launch failed for iteration %s", iteration_id)
            self._append_log(iteration_id, f"[runner] ERROR launch training: {exc}")
            self._fail(iteration_id, f"Lancement training: {exc}")
            return False

        self._store.update_iteration(
            iteration_id,
            training_run_id=training_run_id,
        )

        if not self._wait_training(training_run_id):
            run = self._store.get_run(training_run_id)
            err = run.error if run else "unknown"
            self._append_log(iteration_id, f"[runner] Training {training_run_id} failed: {err}")
            self._fail(iteration_id, f"Training {training_run_id} failed: {err}")
            return False

        # TFLite export — streamed, not silent.
        _set_progress_phase(iteration_id, "export")
        export_ok = True
        try:
            self._export_tflite(iteration_id)
        except Exception as exc:  # noqa: BLE001
            # Training itself succeeded; export failure is non-fatal at the
            # iteration level (the cohortTest bundle script will complain
            # later, the user can re-export by hand). Log and move on.
            export_ok = False
            logger.warning(
                "TFLite export failed for iteration %s: %s",
                iteration_id, exc,
            )
            self._append_log(
                iteration_id,
                f"[runner] WARN export_tflite a échoué: {exc} "
                "(itération continue, bundle cohortTest à régénérer)",
            )

        # finished_at must be ≥ the tflite mtime: the cohortTest bundle
        # script enforces tflite.mtime ≥ iteration.finished_at to detect
        # stale exports (cf scripts/build_cohort_bundle.py:210). If we
        # used `_iso_now()` here, the second-precision rounding plus the
        # gap between subprocess exit and DB update make finished_at land
        # ~1s after the file mtime — false positive stale warning.
        # Adopt the tflite's own mtime as the canonical "training done"
        # timestamp when export succeeded; fall back to now otherwise.
        finished_at = _iso_now()
        if export_ok:
            tflite_path = _iter_dir(iteration_id) / "tflite" / "eurio_embedder_v1.tflite"
            if tflite_path.exists():
                finished_at = (
                    datetime.fromtimestamp(
                        tflite_path.stat().st_mtime, tz=timezone.utc,
                    )
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                )

        # Training phase done. ``completed`` here means "training+export
        # succeeded"; benchmark may follow in _do_benchmark_phase.
        self._store.update_iteration(
            iteration_id,
            status="completed",
            finished_at=finished_at,
        )
        self._append_log(iteration_id, "[runner] Training phase OK")
        return True

    # ─── Benchmark phase ───────────────────────────────────────────────

    def _do_benchmark_phase(self, iteration_id: str) -> bool:
        """Run the studio benchmark subprocess.

        Iteration must be ``completed`` (training+export done). We toggle
        it to ``benchmarking`` while the subprocess runs, then restore
        ``completed`` on success or failure — the iteration's global
        status is untouched by benchmark outcome. Failure surfaces only
        via the benchmark row (``i4.studio.state='partial'``).

        The benchmark_run_id is generated and linked to the iteration
        **before** the subprocess spawns, so any pre-spawn or in-flight
        crash can attach a ``failed`` row to the iteration. There is
        still a brief window between the DB update and the spawn where
        a thread crash would leave ``status='benchmarking'`` with no
        process running — :meth:`recover_on_boot` heals that on next
        API restart.

        Returns True on success.
        """
        it = self._store.get_iteration(iteration_id)
        if it is None:
            logger.error("Iteration %s disappeared at benchmark phase", iteration_id)
            return False
        cohort = self._store.get_cohort(it.cohort_id)
        if cohort is None:
            self._record_benchmark_phase_failure(
                iteration_id, "cohort absent au démarrage",
            )
            return False
        if it.training_run_id is None:
            self._record_benchmark_phase_failure(
                iteration_id, "training_run_id manquant — benchmark impossible",
            )
            return False

        self._append_log(
            iteration_id,
            f"[runner] Iteration {iteration_id}: starting benchmark phase",
        )

        # Pre-create a minimal stub in benchmark_runs so the iteration's
        # FK (experiment_iterations.benchmark_run_id → benchmark_runs.id)
        # can point at it before the subprocess starts. Without this,
        # `update_iteration(benchmark_run_id=...)` would fail with
        # "FOREIGN KEY constraint failed". The script's own create call
        # is idempotent against this stub (cf evaluate_real_photos.py).
        from state import BenchmarkRunRow
        benchmark_run_id = uuid.uuid4().hex[:12]
        model_path = _iter_model_path(iteration_id)
        self._store.create_benchmark_run(
            BenchmarkRunRow(
                id=benchmark_run_id,
                model_path=str(model_path),
                model_name="pending",
                training_run_id=it.training_run_id,
                status="running",
                started_at=_iso_now(),
            )
        )
        self._store.update_iteration(
            iteration_id,
            benchmark_run_id=benchmark_run_id,
            status="benchmarking",
        )
        _set_progress_phase(iteration_id, "benchmark")

        try:
            self._launch_benchmark(
                it, cohort.eurio_ids, it.training_run_id, benchmark_run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Benchmark launch failed for iteration %s", iteration_id)
            self._append_log(
                iteration_id, f"[runner] ERROR launch benchmark: {exc}",
            )
            self._record_benchmark_phase_failure(
                iteration_id, f"Lancement benchmark: {exc}",
            )
            return False

        if not self._wait_benchmark(benchmark_run_id):
            bench = self._store.get_benchmark_run(benchmark_run_id)
            err = bench.error if bench else "unknown"
            self._append_log(iteration_id, f"[runner] Benchmark failed: {err}")
            self._record_benchmark_phase_failure(
                iteration_id, f"Benchmark {benchmark_run_id} failed: {err}",
            )
            return False

        # Benchmark OK — verdict + delta + back to ``completed``.
        try:
            self._finalize_verdict(iteration_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Verdict computation failed for %s", iteration_id)
            self._append_log(
                iteration_id, f"[runner] WARN verdict computation: {exc}",
            )
            # Don't fail the iteration; the benchmark row is healthy.

        # Restore status='completed' (we toggled to 'benchmarking' above).
        self._store.update_iteration(iteration_id, status="completed")
        _set_progress_phase(iteration_id, "done")
        self._append_log(iteration_id, "[runner] Benchmark phase OK")
        return True

    def _record_benchmark_phase_failure(
        self, iteration_id: str, error: str,
    ) -> None:
        """Mark the benchmark phase as failed without tainting the iteration.

        Restores ``iteration.status`` to ``completed`` (training was OK)
        and writes ``phase=benchmark_failed`` to the progress JSON.

        Always ensures there's a ``failed`` benchmark row attached to
        the iteration so the I4a sub-tiroir can surface the error to
        the user across drawer reopens / reloads. Three cases handled:
          1. Row exists and is in-flight → stamp ``failed``.
          2. Row exists in a terminal state → leave as-is (caller had
             a more specific error than ours).
          3. Row missing (subprocess died before its insert) → create
             a stub ``failed`` row keyed by the linked benchmark_run_id.
        """
        from state import BenchmarkRunRow

        it = self._store.get_iteration(iteration_id)
        if it is None:
            return
        if it.benchmark_run_id:
            row = self._store.get_benchmark_run(it.benchmark_run_id)
            if row is None:
                # Subprocess crashed before inserting its own row — stub one.
                model_path = _iter_model_path(iteration_id)
                self._store.create_benchmark_run(
                    BenchmarkRunRow(
                        id=it.benchmark_run_id,
                        model_path=str(model_path),
                        model_name="unknown",
                        report_path="",
                        status="failed",
                        error=error,
                        training_run_id=it.training_run_id,
                        finished_at=_iso_now(),
                    )
                )
            elif row.status not in ("completed", "failed"):
                self._store.update_benchmark_run(
                    it.benchmark_run_id,
                    status="failed",
                    error=error,
                    finished_at=_iso_now(),
                )
        # Restore terminal training status (if we had toggled to 'benchmarking').
        if it.status == "benchmarking":
            self._store.update_iteration(iteration_id, status="completed")
        _set_progress_phase(iteration_id, "benchmark_failed", error=error)

    # ─── Training launch (bake + start training_runner) ────────────────

    def _launch_training(
        self, iteration: ExperimentIterationRow, eurio_ids: list[str],
    ) -> str:
        """Bake persistent augmentations + kick off a training run.

        Augmentations are pre-baked on disk under
        ``ml/datasets/<nid>/augmentations/<iid>/sample_*.jpg``, with a
        symlinked staging root at ``ml/datasets/iterations/<iid>/<eurio_id>/``
        used as the ImageFolder dataset path. ``train_embedder.py`` is then
        run with ``--prebaked-augmentations`` so the recipe layer is bypassed.
        """
        from training.iteration_augmentations import (
            ITERATION_TRAIN_ROOTS,
            generate_for_iteration,
            list_for_iteration,
        )

        # Belt-and-suspenders : the front locks I3 until I2 is ready, and
        # _validate_for_launch_training already enforces this. Re-check so
        # internal callers (tests, scripts) can't bypass it.
        per_coin = list_for_iteration(iteration_id=iteration.id, store=self._store)
        target = max(int(iteration.variant_count), 1)
        incomplete = [
            c["eurio_id"]
            for c in per_coin
            if len(c.get("samples", [])) < target
        ]
        if incomplete:
            raise RuntimeError(
                f"I2 incomplete : {len(incomplete)} pièce(s) sans bake — "
                "génère les augmentations via le tiroir I2 avant de lancer."
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

        # Phase 2 (lab-prod-refacto) : chaque itération vit sous
        # ml/lab/iterations/<iid>/ — checkpoints, embeddings, tflite,
        # metrics, reports y sont écrits explicitement. dataset/train est
        # un symlink vers le bake canonique sous datasets/iterations/<iid>/
        # (laissé en place : déjà bien isolé par iid).
        # Cf. docs/lab-prod-refacto/phase-2-isolation-artefacts.md.
        iter_dir = _iter_dir(iteration.id)
        for sub in ("dataset", "checkpoints", "embeddings", "tflite",
                    "metrics", "reports"):
            (iter_dir / sub).mkdir(parents=True, exist_ok=True)
        train_link = iter_dir / "dataset" / "train"
        train_target = ITERATION_TRAIN_ROOTS / iteration.id
        if train_link.is_symlink() or train_link.exists():
            # idempotent : remplace en cas de relance
            if train_link.is_symlink() or train_link.is_file():
                train_link.unlink()
            else:
                shutil.rmtree(train_link)
        train_link.symlink_to(train_target, target_is_directory=True)

        config = dict(DEFAULT_TRAINING_CONFIG)
        config.update(iteration.training_config or {})
        config["target_augmented"] = iteration.variant_count
        config["prebaked_augmentations"] = True
        config["dataset_override"] = str(train_link)
        config["iteration_id"] = iteration.id
        config["iter_dir"] = str(iter_dir)
        # Lab iteration = label space eurio_id partout. Le COALESCE
        # design_group_id du resolver est désactivé via build_resolver(
        # force_eurio_id=True) côté prepare_dataset. Cf.
        # docs/lab-prod-refacto/phase-1-label-space.md.
        config["class_kind"] = "eurio_id"
        if iteration.recipe_id:
            config["aug_recipe"] = iteration.recipe_id

        added = [ClassRef(eid, "eurio_id") for eid in eurio_ids]
        # Phase 2 : iter_dir auto-suffisant → plus rien à purger inter-run.
        # Le mode "destructif par itération" (purge globale du checkpoint
        # partagé) est retiré ici. Cf.
        # docs/lab-prod-refacto/phase-2-isolation-artefacts.md §"Sémantique
        # du mode destructif actuel".
        removed: list[ClassRef] = []
        # Wire the per-iteration log buffer through the training runner so
        # epoch lines stream into our ring buffer in real time. Failures
        # in the sink must NEVER propagate (logging path).
        iid = iteration.id

        def _sink(line: str) -> None:
            self._append_log(iid, "[training] " + line)

        run = self._training_runner.start_run(
            added=added, removed=removed, config=config, log_sink=_sink,
        )
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

    # ─── TFLite export (streamed) ──────────────────────────────────────

    def _export_tflite(self, iteration_id: str) -> None:
        """Run ``python -m training.export_tflite`` after training succeeds.

        Phase 2 : exporte sous ``lab/iterations/<iid>/tflite/`` puis copie
        embeddings + tflite + meta sous ``ml/output/`` pour les
        consommateurs aval (build_cohort_bundle, seed_supabase) pas encore
        migrés. Ces copies seront retirées en phase 4.
        """
        iter_dir = _iter_dir(iteration_id)
        tflite_out = iter_dir / "tflite"
        tflite_out.mkdir(parents=True, exist_ok=True)
        cmd = [
            VENV_PYTHON, "-u", "-m", "training.export_tflite",
            "--model", str(_iter_model_path(iteration_id)),
            "--output-dir", str(tflite_out),
        ]
        logger.info(
            "Iteration %s: exporting TFLite via %s", iteration_id, " ".join(cmd),
        )
        rc = self._run_subprocess_streamed(
            iteration_id, cmd, label="export",
        )
        if rc != 0:
            raise RuntimeError(f"export_tflite exit {rc}")
        logger.info("Iteration %s: TFLite export OK", iteration_id)

        # Mirror to ml/output/ pour les consommateurs aval (build_cohort_bundle
        # lit ml/output/eurio_embedder_v1.tflite, seed_supabase lit
        # ml/output/embeddings_v1.json). Phase 4 finira l'isolation.
        self._mirror_iter_outputs(iteration_id)

    def _mirror_iter_outputs(self, iteration_id: str) -> None:
        """Copy iter_dir artifacts → ml/output/ for legacy downstream readers."""
        iter_dir = _iter_dir(iteration_id)
        output_dir = ML_DIR / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        sources = [
            iter_dir / "embeddings" / "embeddings_v1.json",
            iter_dir / "embeddings" / "coin_embeddings.json",
            iter_dir / "tflite" / "eurio_embedder_v1.tflite",
            iter_dir / "tflite" / "model_meta.json",
        ]
        for src in sources:
            if src.exists():
                shutil.copy2(src, output_dir / src.name)
            else:
                logger.warning(
                    "Iteration %s: mirror missing source %s", iteration_id, src,
                )

    # ─── Benchmark launch (streamed) ───────────────────────────────────

    def _launch_benchmark(
        self,
        iteration: ExperimentIterationRow,
        eurio_ids: list[str],
        training_run_id: str,
        run_id: str,
    ) -> None:
        """Spawn ``evaluate_real_photos.py`` and stream its output.

        Synchronous from the caller's POV — blocks until the subprocess
        exits (the benchmark runs in the chain thread, holding the global
        lock). The ``run_id`` is generated by the caller and already
        linked to the iteration before we get here, so any pre-spawn or
        in-flight failure can be attached to it.

        On non-zero exit, we update the benchmark row to ``failed`` with
        the captured stdout tail, OR create a stub if the script died
        before inserting its own row.
        """
        model_path = _iter_model_path(iteration.id)
        # Cohort/iteration captures land under `datasets/eval_real_norm/`
        # via `scan.sync_eval_real`. The script's default real-photos
        # path is `ml/data/real_photos/` (legacy manual-benchmark dir).
        # Without --real-photos we'd evaluate on the wrong source.
        real_photos_root = ML_DIR / "datasets" / "eval_real_norm"
        cmd = [
            VENV_PYTHON,
            "-u",  # Unbuffered stdio so streaming actually streams.
            str(ML_DIR / "eval" / "evaluate_real_photos.py"),
            "--model",
            str(model_path),
            "--real-photos",
            str(real_photos_root),
            "--run-id",
            run_id,
            "--eurio-ids",
            ",".join(eurio_ids),
            "--top-confusions",
            "20",
        ]
        if iteration.recipe_id:
            cmd.extend(["--recipe-id", iteration.recipe_id])

        logger.info(
            "Iteration %s: launching benchmark %s via %s",
            iteration.id, run_id, " ".join(cmd),
        )
        rc = self._run_subprocess_streamed(
            iteration.id, cmd, label="benchmark",
        )

        if rc != 0:
            tail = self.tail_logs(iteration.id, n=15)
            error = next(
                (line for line in reversed(tail) if line.strip()),
                f"exit {rc}",
            )
            # The row always exists at this point (pre-created by
            # _do_benchmark_phase). Stamp it failed.
            self._store.update_benchmark_run(
                run_id,
                status="failed",
                error=error,
                finished_at=_iso_now(),
            )
            # Don't raise — the caller reads the row via _wait_benchmark.
        else:
            # Close the traceability loop: stamp training_run_id on
            # the benchmark row (the script's own update may have left
            # it null since it doesn't know the training context).
            self._store.update_benchmark_run(
                run_id, training_run_id=training_run_id,
            )

    def _wait_benchmark(self, run_id: str) -> bool:
        """Poll the benchmark row. With the new streamed launcher, the
        subprocess has already exited by the time this is called — but
        the row update is a separate step, so we still wait briefly.
        """
        deadline_attempts = 0
        while True:
            row = self._store.get_benchmark_run(run_id)
            if row is None:
                # Should not happen with the new streamed launcher (it
                # always writes a row, even on failure). Bail after a
                # few attempts to avoid infinite loop.
                deadline_attempts += 1
                if deadline_attempts > 10:
                    logger.error(
                        "Benchmark run %s never appeared in store", run_id,
                    )
                    return False
                time.sleep(self.POLL_INTERVAL_SEC)
                continue
            if row.status == "completed":
                return True
            if row.status == "failed":
                return False
            time.sleep(self.POLL_INTERVAL_SEC)

    # ─── Verdict / finalize ────────────────────────────────────────────

    def _finalize_verdict(self, iteration_id: str) -> None:
        """Compute verdict + delta against the parent iteration.

        Called after a successful benchmark. Writes verdict/delta on the
        iteration row but does NOT touch ``status``/``finished_at`` —
        those are owned by the chain orchestrator.
        """
        it = self._store.get_iteration(iteration_id)
        if it is None or it.benchmark_run_id is None:
            raise RuntimeError("benchmark_run_id manquant au finalize")

        bench = self._store.get_benchmark_run(it.benchmark_run_id)
        if bench is None:
            raise RuntimeError("benchmark row disparue")

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
            verdict=verdict,
            delta_vs_parent=delta,
            diff_from_parent=diff,
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

    # ─── Streamed subprocess helper ────────────────────────────────────

    def _run_subprocess_streamed(
        self,
        iteration_id: str,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        label: str = "",
    ) -> int:
        """Run ``cmd``, stream stdout+stderr to the per-iteration buffer, return rc.

        Registers the process in ``_active_subprocess`` so :meth:`stop`
        can terminate it. Used for export and benchmark — training has
        its own streaming path inside :class:`TrainingRunner`.

        Forces ``PYTHONUNBUFFERED=1`` on the child (cheap belt-and-
        suspenders alongside the ``-u`` flag we pass to the python
        invocation): without unbuffered stdio, child ``print(...)``
        calls would only flush on ``\\n`` when stdout is a tty — when
        piped, output buffers in 4KB chunks and a fast-failing
        subprocess could exit silently. The streaming benefit matters
        most exactly for those quick crashes.
        """
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd or ML_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered on the parent side
            env=env,
        )
        with self._active_subprocess_lock:
            self._active_subprocess = proc
        try:
            assert proc.stdout is not None
            prefix = f"[{label}] " if label else ""
            for raw in proc.stdout:
                line = raw.rstrip()
                self._append_log(iteration_id, prefix + line)
            rc = proc.wait()
        finally:
            with self._active_subprocess_lock:
                if self._active_subprocess is proc:
                    self._active_subprocess = None
        return rc

    # ─── Failure path (training-side) ──────────────────────────────────

    def _fail(self, iteration_id: str, error: str) -> None:
        """Mark the iteration ``failed`` (training-side failure).

        Distinct from a benchmark phase failure (handled by
        :meth:`_record_benchmark_phase_failure`): a training failure means
        no usable model and the iteration is unusable end-to-end.
        """
        self._store.update_iteration(
            iteration_id,
            status="failed",
            error=error,
            finished_at=_iso_now(),
        )
        _set_progress_phase(iteration_id, "failed", error=error)


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
