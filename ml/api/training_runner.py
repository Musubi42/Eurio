"""Training runner — one retrain per run, many classes in one retrain.

ArcFace has no incremental add: every added (or removed) class triggers a
full retrain of the model on the complete class set. This runner reflects
that reality:

  - `start_run(added, removed)` creates a single `TrainingRun` that covers
    all requested mutations in one pipeline execution.
  - Only one run may be active at a time; a second `start_run` raises.
  - Persistence lives in the SQLite Store (`state/training.db`). History,
    logs, per-epoch metrics, and per-class metrics all survive process
    restarts.

Pipeline steps:
  0. Suppression           — rm prepared split dirs + Supabase rows of removed classes
  1. Préparation           — prepare_dataset.py (rebuild eurio-poc + manifest)
  2. Entraînement          — train_embedder.py with --model-version vN-arcface
                             (augmentation is on-the-fly, per-zone, in the DataLoader)
  3. Embeddings            — compute_embeddings.py with --model-version
  4. Synchronisation       — seed_supabase.py (dual-write model_classes + legacy)
  5. Validation per-class  — validate_per_class.py → training_run_classes
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

import httpx

from state import (
    ClassMetricRow,
    ClassRef,
    EpochRow,
    RunRow,
    StepRow,
    Store,
)

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
DATASETS_DIR = ML_DIR / "datasets"
CHECKPOINTS_DIR = ML_DIR / "checkpoints"
OUTPUT_DIR = ML_DIR / "output"
EURIO_POC = DATASETS_DIR / "eurio-poc"
PER_CLASS_METRICS = OUTPUT_DIR / "per_class_metrics.json"

# Ensure ml/ root is in sys.path for absolute package imports (referential, eval, etc.).
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

STEPS = [
    "Suppression",
    "Préparation",
    "Entraînement",
    "Embeddings",
    "Synchronisation",
    "Validation per-class",
]

STEP_INDEX = {name: i for i, name in enumerate(STEPS)}

DEFAULT_CONFIG = {
    "epochs": 40,
    "batch_size": 256,
    "m_per_class": 4,
    "target_augmented": 50,
    "mode": "arcface",
}


@dataclass
class ActiveState:
    """Ephemeral in-memory view of the currently executing run."""

    run_id: str
    epoch: int = 0
    epochs_total: int = 0
    log_lines: list[str] = field(default_factory=list)
    epoch_start_ts: float | None = None
    # Optional sink invoked for every line read from the training subprocess.
    # Used by IterationRunner to mirror lines into its per-iteration buffer
    # (so the live monitor sees logs regardless of which phase is active).
    log_sink: Callable[[str], None] | None = None


class TrainingRunner:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._active: ActiveState | None = None
        self._active_proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._device = "auto"  # forwarded to train_embedder.py --device; resolves to cuda/mps/cpu per host
        self._rehydrate()

    # ─── Config ──────────────────────────────────────────────────────────

    @property
    def device(self) -> str:
        return self._device

    @device.setter
    def device(self, value: str) -> None:
        self._device = value

    # ─── Public query API ────────────────────────────────────────────────

    def active_run(self) -> RunRow | None:
        with self._lock:
            run_id = self._active.run_id if self._active else None
        return self._store.get_run(run_id) if run_id else None

    def active_snapshot(self) -> dict | None:
        with self._lock:
            if self._active is None:
                return None
            return {
                "run_id": self._active.run_id,
                "epoch": self._active.epoch,
                "epochs_total": self._active.epochs_total,
            }

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
        with self._lock:
            if self._active and self._active.run_id == run_id:
                return list(self._active.log_lines)
        return self._store.load_logs(run_id)

    def tail_logs(self, n: int = 30) -> list[str]:
        """Return up to ``n`` most recent stdout lines of the active subprocess.

        Empty list when no run is active. Thread-safe: reads under the runner's
        lock (the writer in ``_run_subprocess`` also takes it).
        """
        with self._lock:
            if self._active is None:
                return []
            lines = self._active.log_lines
            return list(lines[-n:])

    def current_classes(self) -> list[ClassRef]:
        return _read_current_classes()

    # ─── Public mutation API ─────────────────────────────────────────────

    def start_run(
        self,
        *,
        added: list[ClassRef],
        removed: list[ClassRef],
        config: dict | None = None,
        log_sink: Callable[[str], None] | None = None,
    ) -> RunRow:
        """Create and kick off a training run covering `added` + `removed`.

        ``log_sink`` (optional) is invoked for every line of subprocess
        output. The runner still keeps its own ``log_lines`` buffer (used
        for the post-run archive); the sink is purely a mirror for live
        consumers that outlive the ``ActiveState`` (e.g. ``IterationRunner``
        which needs logs to survive into the benchmark phase).
        """
        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg.update({k: v for k, v in config.items() if v is not None})

        with self._lock:
            if self._active is not None:
                raise RuntimeError("A training run is already active")

            classes_before = _read_current_classes()
            removed_ids = {c.class_id for c in removed}
            added_map = {c.class_id: c for c in added}

            classes_after_map: dict[str, ClassRef] = {
                c.class_id: c
                for c in classes_before
                if c.class_id not in removed_ids
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
            self._active = ActiveState(
                run_id=run_id,
                epochs_total=int(cfg.get("epochs", 40)),
                log_sink=log_sink,
            )

        thread = threading.Thread(
            target=self._execute, args=(run_id,), daemon=True
        )
        thread.start()
        return row

    # ─── Execution ───────────────────────────────────────────────────────

    def _rehydrate(self) -> None:
        """Mark any leftover 'running' runs as failed (process was killed)."""
        for r in self._store.list_runs(status="running"):
            self._store.update_run_status(
                r.id,
                "failed",
                error="Interrupted by API restart",
                finished_at=_now_iso(),
            )

    def _execute(self, run_id: str) -> None:
        version_str = self._version_string(run_id)
        try:
            self._store.update_run_status(
                run_id, "running", started_at=_now_iso()
            )
            self._run_step(run_id, 0, lambda row: self._delete(row))
            self._run_step(run_id, 1, lambda row: self._prepare(row))
            self._run_step(run_id, 2, lambda row: self._train(row, version_str))
            self._run_step(run_id, 3, lambda row: self._compute_embeddings(row, version_str))
            self._run_step(run_id, 4, lambda row: self._seed(row))
            self._run_step(run_id, 5, lambda row: self._validate_per_class(row))
            self._finalize_run(run_id)
            self._store.update_run_status(
                run_id, "completed", finished_at=_now_iso()
            )
        except Exception as exc:  # noqa: BLE001 — top-level run failure
            self._store.update_run_status(
                run_id,
                "failed",
                error=str(exc),
                finished_at=_now_iso(),
            )
        finally:
            with self._lock:
                active = self._active
                self._active = None
            if active is not None:
                self._store.save_logs(run_id, active.log_lines)

    def _version_string(self, run_id: str) -> str:
        row = self._store.get_run(run_id)
        mode = (row.config.get("mode") if row and row.config else None) or "arcface"
        version = row.version if row else 0
        return f"v{version}-{mode}"

    def _run_step(self, run_id: str, idx: int, action) -> None:
        row = self._store.get_run(run_id)
        if row is None:
            raise RuntimeError(f"Run {run_id} disappeared")
        name = STEPS[idx]
        started = _now_iso()
        self._store.upsert_step(
            run_id,
            StepRow(step_index=idx, name=name, status="running", started_at=started),
        )
        try:
            detail = action(row)
            status = "skipped" if detail and detail.startswith("skipped") else "done"
            self._store.upsert_step(
                run_id,
                StepRow(
                    step_index=idx,
                    name=name,
                    status=status,
                    started_at=started,
                    finished_at=_now_iso(),
                    detail=detail,
                ),
            )
        except Exception as exc:
            self._store.upsert_step(
                run_id,
                StepRow(
                    step_index=idx,
                    name=name,
                    status="failed",
                    started_at=started,
                    finished_at=_now_iso(),
                    detail=str(exc),
                ),
            )
            raise

    # ─── Steps ───────────────────────────────────────────────────────────

    def _delete(self, row: RunRow) -> str:
        # Phase 2 (lab-prod-refacto) : avec iter_dir, chaque itération vit
        # dans son propre univers ; il n'y a plus rien à purger inter-run.
        # Cf. docs/lab-prod-refacto/phase-2-isolation-artefacts.md.
        if _iter_dir(row) is not None:
            return "skipped (iter_dir self-contained)"
        if not row.classes_removed:
            return "skipped (no removed classes)"
        # If the same class is also being added (e.g. user removed all old
        # classes then re-staged a subset), skip its removal — augmentation is
        # now on-the-fly so there's nothing dataset-side to wipe, and we want
        # the new staging to take effect.
        added_ids = {ref.class_id for ref in row.classes_added}
        resolver = _build_resolver()
        removed_count = 0
        for ref in row.classes_removed:
            if ref.class_id in added_ids:
                self._log(
                    row.id,
                    f"  {ref.class_id}: also in classes_added, skipping removal",
                )
                continue
            descriptor = resolver.for_class(ref.class_id)
            for split in ("train", "val", "test"):
                split_dir = EURIO_POC / split / ref.class_id
                if split_dir.exists():
                    shutil.rmtree(split_dir)
                    self._log(row.id, f"  removed {split_dir}")
            _purge_supabase(ref, descriptor.eurio_ids if descriptor else ())
            removed_count += 1
        return f"{removed_count} class(es) removed"

    def _prepare(self, row: RunRow) -> str:
        cmd = [VENV_PYTHON, str(ML_DIR / "training" / "prepare_dataset.py")]
        if row.classes_after:
            only = ",".join(sorted({c.class_id for c in row.classes_after}))
            cmd.extend(["--only-classes", only])
        # class_kind est requis par prepare_dataset.py. En lab iteration on
        # force eurio_id (cf. iteration_runner._launch_training). Les runs
        # legacy hors-iteration tombent sur design_group (COALESCE historique).
        class_kind = row.config.get("class_kind", "design_group")
        cmd.extend(["--class-kind", class_kind])
        iter_dir = _iter_dir(row)
        if iter_dir is not None:
            dataset_dir = iter_dir / "dataset"
            cmd.extend([
                "--output-dir", str(dataset_dir),
                "--skip-train-split",
            ])
            self._run_subprocess(row.id, cmd)
            manifest_path = dataset_dir / "class_manifest.json"
        else:
            self._run_subprocess(row.id, cmd)
            manifest_path = EURIO_POC / "class_manifest.json"
        if manifest_path.exists():
            payload = json.loads(manifest_path.read_text())
            n = len(payload.get("classes", []))
            return f"{n} classes prepared"
        return "prepared"

    def _train(self, row: RunRow, version_str: str) -> str:
        cfg = row.config
        with self._lock:
            if self._active is not None:
                self._active.epoch = 0
                self._active.epochs_total = int(cfg.get("epochs", 40))
        iter_dir = _iter_dir(row)
        dataset_path = cfg.get("dataset_override") or str(EURIO_POC / "train")
        val_path = (
            str(iter_dir / "dataset" / "val") if iter_dir is not None
            else str(EURIO_POC / "val")
        )
        cmd: list[str] = [
            VENV_PYTHON,
            str(ML_DIR / "training" / "train_embedder.py"),
            "--mode",
            cfg.get("mode", "arcface"),
            "--dataset",
            dataset_path,
            "--val-dataset",
            val_path,
            "--epochs",
            str(cfg["epochs"]),
            "--batch-size",
            str(cfg["batch_size"]),
            "--m-per-class",
            str(cfg["m_per_class"]),
            "--device",
            self._device,
            "--model-version",
            version_str,
        ]
        if iter_dir is not None:
            cmd.extend(["--output", str(iter_dir / "checkpoints")])
        aug_recipe = cfg.get("aug_recipe") or row.aug_recipe_id
        prebaked = bool(cfg.get("prebaked_augmentations"))
        if prebaked:
            cmd.append("--prebaked-augmentations")
        elif aug_recipe:
            cmd.extend(["--aug-recipe", str(aug_recipe)])
        # Phase 5 — wire the iteration_id so train_embedder.py writes
        # ml/state/training_progress/<iid>.json that the Lab UI tails.
        iteration_id = cfg.get("iteration_id")
        if iteration_id:
            cmd.extend(["--iteration-id", str(iteration_id)])
        self._run_subprocess(row.id, cmd, parse_training_output=True)
        suffix = ""
        if prebaked:
            suffix = " + prebaked"
        elif aug_recipe:
            suffix = f" + recipe={aug_recipe}"
        return f"{cfg['epochs']} epochs ({version_str}){suffix}"

    def _compute_embeddings(self, row: RunRow, version_str: str) -> str:
        cmd = [
            VENV_PYTHON,
            str(ML_DIR / "training" / "compute_embeddings.py"),
            "--model-version",
            version_str,
        ]
        iter_dir = _iter_dir(row)
        if iter_dir is not None:
            cmd.extend([
                "--model", str(iter_dir / "checkpoints" / "best_model.pth"),
                "--dataset", str(iter_dir / "dataset"),
                "--output-dir", str(iter_dir / "embeddings"),
            ])
            emb_path = iter_dir / "embeddings" / "embeddings_v1.json"
        else:
            emb_path = OUTPUT_DIR / "embeddings_v1.json"
        self._run_subprocess(row.id, cmd)
        if emb_path.exists():
            n = len(json.loads(emb_path.read_text()).get("coins", {}))
            return f"{n} class embeddings"
        return "embeddings computed"

    def _seed(self, row: RunRow) -> str:
        # Phase 2 (lab-prod-refacto) : en mode iteration, on n'écrit plus
        # Supabase ici. Le push vers `coin_embeddings` / `model_classes`
        # devient l'effet exclusif de la promotion (phase 3).
        if _iter_dir(row) is not None:
            return "skipped (iter_dir = no Supabase write before promote)"
        self._run_subprocess(
            row.id, [VENV_PYTHON, str(ML_DIR / "bootstrap" / "seed_supabase.py")]
        )
        return "synced to Supabase"

    def _validate_per_class(self, row: RunRow) -> str:
        cmd = [VENV_PYTHON, str(ML_DIR / "training" / "validate_per_class.py")]
        iter_dir = _iter_dir(row)
        if iter_dir is not None:
            metrics_path = iter_dir / "metrics" / "per_class_metrics.json"
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            cmd.extend([
                "--model", str(iter_dir / "checkpoints" / "best_model.pth"),
                "--dataset", str(iter_dir / "dataset"),
                "--output", str(metrics_path),
            ])
        else:
            metrics_path = PER_CLASS_METRICS
        self._run_subprocess(row.id, cmd)
        if not metrics_path.exists():
            return "no metrics written"
        data = json.loads(metrics_path.read_text())
        classes = data.get("classes", [])
        rows = [
            ClassMetricRow(
                class_id=c["class_id"],
                class_kind=c.get("class_kind", "eurio_id"),
                recall_at_1=c.get("recall_at_1"),
                n_train_images=c.get("n_train_images"),
                n_val_images=c.get("n_val_images"),
            )
            for c in classes
        ]
        self._store.set_run_classes(row.id, rows)
        return f"{len(rows)} per-class metrics"

    # ─── Finalization ────────────────────────────────────────────────────

    def _finalize_run(self, run_id: str) -> None:
        row = self._store.get_run(run_id)
        iter_dir = _iter_dir(row) if row else None
        log_path = (
            iter_dir / "checkpoints" / "training_log.json" if iter_dir is not None
            else CHECKPOINTS_DIR / "training_log.json"
        )
        if not log_path.exists():
            return
        try:
            logs = json.loads(log_path.read_text())
        except json.JSONDecodeError:
            return
        if not isinstance(logs, list) or not logs:
            return
        for entry in logs:
            epoch = entry.get("epoch")
            if epoch is None:
                continue
            r1 = entry.get("recall@1") if "recall@1" in entry else entry.get("val_acc")
            r3 = entry.get("recall@3") if "recall@3" in entry else entry.get("val_top3_acc")
            self._store.append_epoch(
                run_id,
                EpochRow(
                    epoch=int(epoch),
                    train_loss=entry.get("train_loss"),
                    recall_at_1=r1,
                    recall_at_3=r3,
                    lr=entry.get("lr"),
                ),
            )
        durations = [
            e.duration_sec
            for e in self._store.list_epochs(run_id)
            if e.duration_sec is not None
        ]
        median = statistics.median(durations) if durations else None
        last = logs[-1]
        self._store.update_run_metrics(
            run_id,
            loss=last.get("train_loss"),
            recall_at_1=last.get("recall@1") or last.get("val_acc"),
            recall_at_3=last.get("recall@3") or last.get("val_top3_acc"),
            epoch_duration_median_sec=median,
        )

    # ─── Subprocess + streaming ──────────────────────────────────────────

    def _run_subprocess(
        self,
        run_id: str,
        cmd: list[str],
        *,
        parse_training_output: bool = False,
    ) -> None:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ML_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with self._lock:
            self._active_proc = proc
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                self._log(run_id, line)
                if parse_training_output:
                    self._parse_epoch_line(run_id, line)
            rc = proc.wait()
        finally:
            with self._lock:
                if self._active_proc is proc:
                    self._active_proc = None
        if rc != 0:
            # Exit code 2 is the cooperative stop sentinel from
            # train_embedder.py — treat it as a graceful abort, not a crash.
            if rc == 2:
                raise RuntimeError("Stopped by user (graceful)")
            raise RuntimeError(
                f"Command failed (exit {rc}): {' '.join(cmd)}"
            )

    def stop_active(self, *, graceful_timeout: float = 30.0) -> str:
        """Send SIGTERM to the active subprocess, escalate to SIGKILL on timeout.

        Returns ``'graceful'`` if the process exited within
        ``graceful_timeout`` seconds, ``'forced'`` if SIGKILL was needed, or
        ``'idle'`` if there was nothing to stop.
        """
        with self._lock:
            proc = self._active_proc
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

    def _log(self, run_id: str, line: str) -> None:
        with self._lock:
            if self._active is None or self._active.run_id != run_id:
                return
            self._active.log_lines.append(line)
            sink = self._active.log_sink
        # Call the sink outside the runner lock so a slow consumer can't
        # block the subprocess reader thread. Failures must NEVER propagate
        # — this is a logging side-channel, not the source of truth.
        if sink is not None:
            try:
                sink(line)
            except Exception:  # noqa: BLE001
                logger.exception("Training log_sink raised — ignoring")

    def _parse_epoch_line(self, run_id: str, line: str) -> None:
        if "Epoch" not in line or "loss:" not in line:
            return
        try:
            parts = line.strip().split()
            epoch_idx = parts.index("Epoch") + 1
            epoch = int(parts[epoch_idx])
        except (ValueError, IndexError):
            return

        loss: float | None = None
        r1: float | None = None
        r3: float | None = None
        for i, p in enumerate(parts):
            if p == "loss:":
                loss = _safe_float(parts[i + 1] if i + 1 < len(parts) else None)
            elif p == "R@1:":
                r1 = _safe_pct(parts[i + 1] if i + 1 < len(parts) else None)
            elif p == "R@3:":
                r3 = _safe_pct(parts[i + 1] if i + 1 < len(parts) else None)
            elif p == "val_acc:":
                r1 = _safe_pct(parts[i + 1] if i + 1 < len(parts) else None)
            elif p == "val_top3:":
                r3 = _safe_pct(parts[i + 1] if i + 1 < len(parts) else None)

        now = datetime.utcnow().timestamp()
        duration: float | None = None
        with self._lock:
            if self._active is not None and self._active.run_id == run_id:
                if self._active.epoch_start_ts is not None:
                    duration = now - self._active.epoch_start_ts
                self._active.epoch = epoch
                self._active.epoch_start_ts = now

        self._store.append_epoch(
            run_id,
            EpochRow(
                epoch=epoch,
                train_loss=loss,
                recall_at_1=r1,
                recall_at_3=r3,
                duration_sec=duration,
            ),
        )
        self._store.upsert_step(
            run_id,
            StepRow(
                step_index=STEP_INDEX["Entraînement"],
                name="Entraînement",
                status="running",
                detail=f"Epoch {epoch}",
            ),
        )


# ─── Module-level helpers ────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _safe_float(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_pct(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.rstrip("%")) / 100
    except ValueError:
        return None


def _iter_dir(row: RunRow | None) -> Path | None:
    """Resolve the per-iteration root, when this run is owned by an iteration.

    Set by :class:`IterationRunner` via ``config["iter_dir"]`` ; absent for
    legacy direct ``start_run`` callers (which keep the singleton paths under
    ``ml/datasets/eurio-poc`` and ``ml/checkpoints/``).
    """
    if row is None or not row.config:
        return None
    raw = row.config.get("iter_dir")
    return Path(raw) if raw else None


def _read_current_classes() -> list[ClassRef]:
    manifest = EURIO_POC / "class_manifest.json"
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text())
    return [
        ClassRef(class_id=c["class_id"], class_kind=c["class_kind"])
        for c in data.get("classes", [])
    ]


def _build_resolver():
    from eval.class_resolver import build_resolver

    return build_resolver()


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = ML_DIR.parent / ".env"
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def _purge_supabase(ref: ClassRef, eurio_ids: tuple[str, ...]) -> None:
    env = _load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    rest = url.rstrip("/") + "/rest/v1"
    with httpx.Client(headers=headers, timeout=30) as c:
        c.delete(f"{rest}/model_classes?class_id=eq.{ref.class_id}")
        if ref.class_kind == "eurio_id":
            c.delete(f"{rest}/coin_embeddings?eurio_id=eq.{ref.class_id}")
        elif eurio_ids:
            quoted = ",".join(f'"{eid}"' for eid in eurio_ids)
            c.delete(f"{rest}/coin_embeddings?eurio_id=in.({quoted})")
