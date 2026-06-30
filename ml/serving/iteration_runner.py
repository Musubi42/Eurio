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

from store import ClassRef, ExperimentIterationRow, Store

import jobs
from jobs import _pid_alive
from training.pipeline import TrainingPipeline
from .iteration_logic import compute_delta, compute_input_diff, compute_verdict
from .training_runner import TrainingRunner

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
DATASETS_DIR = ML_DIR / "datasets"
LAB_ITERATIONS_DIR = ML_DIR / "lab" / "iterations"
RUN_ITERATION_SCRIPT = str(ML_DIR / "training" / "run_iteration.py")


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
        # Single iteration per detached chain process; this lock just guards the
        # chain body within that process (the API-side concurrency guard is
        # `is_busy()`, which checks the live iteration job).
        self._global_lock = threading.Lock()

        # Per-iteration log buffer used by the chain WHILE it runs (detached
        # process). `_append_log` also prints to stdout → captured into the job
        # log file, which the API process tails via `tail_logs`.
        self._iter_logs: dict[str, deque[str]] = {}
        self._iter_logs_lock = threading.Lock()

    # ─── Per-iteration log buffer ─────────────────────────────────────

    def _append_log(self, iteration_id: str, line: str) -> None:
        # Imprime sur stdout → capté dans le fichier de log du job détaché (lu par
        # l'API via `tail_logs`). Le deque mémoire reste utile au sein du process
        # détaché (ex. `_launch_benchmark` relit la tail pour son message d'erreur).
        print(line, flush=True)
        with self._iter_logs_lock:
            buf = self._iter_logs.get(iteration_id)
            if buf is None:
                buf = deque(maxlen=self.LOG_BUFFER_MAX)
                self._iter_logs[iteration_id] = buf
            buf.append(line)

    def tail_logs(self, iteration_id: str, n: int = 30) -> list[str]:
        """Up to ``n`` most recent log lines for an iteration — couvre toutes les
        phases (training, export, benchmark). Côté API : lit la tail du fichier de
        log du job détaché. Vide si aucune chaîne n'a (encore) tourné."""
        job = jobs.job_by_param(
            self._store._connection(), "iteration_id", iteration_id, kind="iteration",  # noqa: SLF001
        )
        if not job or not job.get("log_path"):
            # Dans le process détaché lui-même, la row job peut ne pas être visible
            # avant le 1er commit → fallback sur le deque mémoire local.
            with self._iter_logs_lock:
                buf = self._iter_logs.get(iteration_id)
                if buf is None:
                    return []
                start = max(0, len(buf) - n)
                return list(itertools.islice(buf, start, len(buf)))
        p = Path(job["log_path"])
        if not p.exists():
            return []
        return p.read_text(errors="replace").splitlines()[-n:]

    def _reset_logs(self, iteration_id: str) -> None:
        with self._iter_logs_lock:
            self._iter_logs.pop(iteration_id, None)

    # ─── Public API ────────────────────────────────────────────────────

    @property
    def training_runner(self) -> TrainingRunner:
        """Public accessor — kept for backwards compat (used to be called
        for log tailing; now logs are read via :meth:`tail_logs`)."""
        return self._training_runner

    def _active_job(self, iteration_id: str) -> dict | None:
        # kind='iteration' : ne PAS confondre avec un job 'augmentation' qui porte
        # le même iteration_id (bake standalone). Cf. lab_routes augmentations.
        return jobs.job_by_param(
            self._store._connection(), "iteration_id", iteration_id, kind="iteration",  # noqa: SLF001
        )

    def is_busy(self) -> bool:
        """True si une itération tourne actuellement (job détaché vivant). Garde
        de concurrence côté API : une seule chaîne à la fois (GPU + best_model.pth)."""
        job = jobs.job_latest(self._store._connection(), "iteration")  # noqa: SLF001
        if not job or job["status"] != "running":
            return False
        pid = job.get("pid")
        return bool(pid and _pid_alive(pid))

    def stop(self, iteration_id: str) -> dict:
        """Cooperatively stop a running iteration by signalling its DETACHED
        process-group (training/export/benchmark children inclus).

        Returns ``{outcome ∈ graceful|forced|idle, marked_failed}``. Only
        iterations in a transient state (``training``/``benchmarking``) are
        marked failed; terminal ones are left untouched (avoids racing a chain
        that just legitimately transitioned)."""
        job = self._active_job(iteration_id)
        pid = job.get("pid") if job else None
        if pid and _pid_alive(pid):
            outcome = jobs.stop_process_group(
                int(pid), graceful_timeout=self.STOP_GRACEFUL_TIMEOUT_SEC,
            )
            if outcome != "idle":
                self._fail(iteration_id, f"Stopped by user ({outcome})")
                return {"outcome": outcome, "marked_failed": True}

        # Nothing alive. Only fail if the iteration is genuinely transient.
        it = self._store.get_iteration(iteration_id)
        if it is None:
            return {"outcome": "idle", "marked_failed": False}
        if it.status in ("training", "benchmarking"):
            self._fail(iteration_id, "Stopped by user (no active process)")
            return {"outcome": "idle", "marked_failed": True}
        return {"outcome": "idle", "marked_failed": False}

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

        # C7 (Model B) : garde-fou par cohorte — refuse de créer une nouvelle
        # itération tant qu'une itération de CETTE cohorte est en `training`
        # (résultats pas encore connus). RuntimeError → 409 (lab_routes mapping).
        # Complète `is_busy()` (single-flight GLOBAL au launch) par une garde
        # sémantique par-cohorte au create. Raisonne sur l'état canonique des
        # itérations (cf. C6c qui transporte experiment_iterations au serveur).
        training = self._store.list_iterations(cohort_id=cohort_id, status="training")
        if training:
            raise RuntimeError(
                f"Cohorte {cohort_id!r} : une itération est déjà en entraînement "
                f"({training[0].id}) — attends sa fin avant d'en créer une nouvelle."
            )

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
        self._launch_chain(iteration_id, mode="full")
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
        self._launch_chain(iteration_id, mode="benchmark")
        return iteration

    def _launch_chain(self, iteration_id: str, *, mode: str) -> None:
        """Lance la chaîne (`full` = training→export→benchmark, ou `benchmark`
        seul) en subprocess DÉTACHÉ via le rail `jobs/` → survit au `--reload`."""
        jobs.launch(
            self._store._connection(),  # noqa: SLF001
            kind="iteration",
            cmd_builder=lambda jid: [
                VENV_PYTHON, RUN_ITERATION_SCRIPT,
                "--iteration-id", iteration_id, "--mode", mode, "--job-id", jid,
            ],
            params={"iteration_id": iteration_id, "mode": mode},
        )

    def _validate_for_launch_training(
        self, iteration_id: str,
    ) -> ExperimentIterationRow:
        from training.iteration_augmentations import class_sample_counts

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

        # Maille = CLASSE (design_group), pas membre. Un membre sans crops propres
        # (ex. be-2007) baке 0 sample, mais sa classe a les samples via un autre
        # millésime (ex. be-1999) — le préflight valide déjà au niveau groupe. On
        # exige donc ≥ target samples *par classe*, pas par pièce de cohorte.
        target = iteration.variant_count
        counts = class_sample_counts(iteration_id=iteration_id, store=self._store)
        missing = [cid for cid, n in counts.items() if n < target]
        if missing:
            raise RuntimeError(
                f"Augmentations manquantes ou incomplètes pour "
                f"{len(missing)} classe(s) : {', '.join(missing[:5])}"
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

    def _chain_alive(self, iteration_id: str) -> bool:
        """True si la chaîne détachée de cette itération a survécu au reload
        (job `running` + PID vivant). Le reaper du rail clôt sa row job si mort."""
        job = self._active_job(iteration_id)
        pid = job.get("pid") if job else None
        return bool(pid and _pid_alive(pid))

    def recover_on_boot(self) -> int:
        """Reconcile stuck iterations at API boot.

        Une chaîne détachée qui a survécu au `--reload` (PID vivant) est
        **laissée tourner**. On ne nettoie que les itérations dont le process est
        mort. Pas d'auto-retry : reprendre à l'aveugle est plus dangereux qu'utile
        (re-bake mid-flight, training dupliqué…) — l'utilisateur relance.

        Returns the number of cleaned-up iterations.
        """
        cleaned = 0
        # Training-stuck → mark failed (no usable model to point at).
        for it in self._store.list_iterations(status="training"):
            if self._chain_alive(it.id):
                continue  # survived the reload — leave it running
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
            if self._chain_alive(it.id):
                continue  # survived the reload — leave it running
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
        from store import BenchmarkRunRow
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
        from store import BenchmarkRunRow

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
            class_sample_counts,
            generate_for_iteration,
        )
        from training.eval.class_resolver import build_resolver

        # (Re)bake idempotent des augmentations persistantes. La maille de vérité
        # est la CLASSE (design_group) : un membre sans crops propres (ex.
        # be-2007, qui hérite de be-1999) est skippé — c'est attendu, pas une
        # erreur. On ne refuse que si une CLASSE finit sous le seuil (samples
        # poolés sur tous ses membres). _validate_for_launch_training fait déjà
        # ce contrôle en amont ; re-check ici pour les callers internes.
        target = max(int(iteration.variant_count), 1)
        reports = generate_for_iteration(iteration_id=iteration.id, store=self._store)
        counts = class_sample_counts(iteration_id=iteration.id, store=self._store)
        under = [cid for cid, n in counts.items() if n < target]
        if under:
            raise RuntimeError(
                f"I2 incomplète : {len(under)} classe(s) sous le seuil de "
                f"{target} samples ({', '.join(under[:5])}) — relance le bake "
                "via le tiroir I2 avant de lancer."
            )
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
        # Lab iteration entraîne à la maille CANONIQUE du label ArcFace =
        # COALESCE(design_group_id, eurio_id) (cf. docs/design/_shared/
        # design-groups.md §6.1). Les standards pluri-millésimes d'un même avers
        # (ex. be-1999 ⊕ be-2007 → be-2euro-albert-ii-t1) s'effondrent en UNE
        # classe → pooling des sources réelles (be-2007 hérite des crops de
        # be-1999) au lieu de starve en eurio_id pur. L'invariant phase-1
        # (--only-classes doit matcher le label space) est préservé : on stage
        # les class_id design_group ET on prépare en class_kind="design_group".
        config["class_kind"] = "design_group"
        if iteration.recipe_id:
            config["aug_recipe"] = iteration.recipe_id

        resolver = build_resolver(
            force_eurio_id=False, db_path=self._store.db_path,
        )
        descriptors, unresolved = resolver.classes_for_eurio_ids(eurio_ids)
        if unresolved:
            raise RuntimeError(
                "eurio_ids absents du catalogue (réf morte / slug drift), "
                f"impossible de stager : {', '.join(unresolved)}"
            )
        added = [ClassRef(d.class_id, d.class_kind) for d in descriptors]
        # Phase 2 : iter_dir auto-suffisant → plus rien à purger inter-run.
        # Le mode "destructif par itération" (purge globale du checkpoint
        # partagé) est retiré ici. Cf.
        # docs/lab-prod-refacto/phase-2-isolation-artefacts.md §"Sémantique
        # du mode destructif actuel".
        removed: list[ClassRef] = []
        # 2b-2 : on est DÉJÀ dans le process détaché de la chaîne → le pipeline
        # training tourne SYNCHRONIQUEMENT ici. Son stdout (les lignes d'epoch
        # incluses) est capté dans le fichier de log du job iteration, que l'API
        # tail via `tail_logs`. Plus de thread ni de `log_sink`.
        run = self._training_runner.create_run_row(
            added=added, removed=removed, config=config,
        )
        if iteration.recipe_id:
            recipe = self._store.get_recipe(iteration.recipe_id)
            if recipe is not None:
                self._store.update_run_aug_recipe(run.id, recipe.id)
        try:
            TrainingPipeline(
                self._store, run.id, device=self._training_runner.device,
            ).run()
        except Exception:  # noqa: BLE001 — run() a marqué le run 'failed' ; _wait_training le verra
            logger.exception("Iteration training pipeline failed (run %s)", run.id)
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

        Phase 4 : exporte uniquement sous ``lab/iterations/<iid>/tflite/``.
        Les artefacts ne deviennent « prod » que via
        ``scripts.promote_iteration`` (→ ``ml/prod/current/``). Le mirror
        legacy vers ``ml/output/`` a été retiré : tous les consommateurs
        (server.py, lab_routes, seed_supabase, eval) lisent désormais
        ``prod/current/`` ou la lab iteration explicite.
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
        # Centroïdes = ceux de CETTE itération (calculés au step compute_embeddings
        # → lab/iterations/<iid>/embeddings/). Sans --centroids, le script tombe
        # sur son défaut = prod/current/embeddings/ (le modèle PROMU), qui est soit
        # absent (rien promu → "Centroids file not found" → bench raté), soit
        # incohérent avec le modèle de l'itération (espace d'embedding ≠). On
        # benche toujours l'itération contre SES propres prototypes.
        centroids_path = (
            _iter_dir(iteration.id) / "embeddings" / "embeddings_v1.json"
        )
        # Cohort/iteration captures land under `datasets/eval_real_norm/`
        # via `scan.sync_eval_real`. The script's default real-photos
        # path is `ml/data/real_photos/` (legacy manual-benchmark dir).
        # Without --real-photos we'd evaluate on the wrong source.
        real_photos_root = ML_DIR / "datasets" / "eval_real_norm"
        cmd = [
            VENV_PYTHON,
            "-u",  # Unbuffered stdio so streaming actually streams.
            str(ML_DIR / "training" / "eval" / "evaluate_real_photos.py"),
            "--model",
            str(model_path),
            "--centroids",
            str(centroids_path),
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

        Export & benchmark children. Stop is handled cross-process by
        signalling the whole DETACHED chain group (`jobs.stop_process_group`) —
        these children share the chain's session, so no local tracking needed.

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
        assert proc.stdout is not None
        prefix = f"[{label}] " if label else ""
        for raw in proc.stdout:
            line = raw.rstrip()
            self._append_log(iteration_id, prefix + line)
        return proc.wait()

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
