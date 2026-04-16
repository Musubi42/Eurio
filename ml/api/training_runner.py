"""Training runner — manages a queue of ML training jobs.

Each job trains one design (numista_id) through the full pipeline:
augment → prepare → train ArcFace → compute embeddings → export TFLite → seed Supabase.

Jobs are processed sequentially (or up to max_concurrent in parallel on GPU).
"""

from __future__ import annotations

import json
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
DATASETS_DIR = ML_DIR / "datasets"
CHECKPOINTS_DIR = ML_DIR / "checkpoints"
OUTPUT_DIR = ML_DIR / "output"

STEP_NAMES = [
    "Augmentation",
    "Préparation",
    "Entraînement",
    "Embeddings",
    "Synchronisation",
]


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StepInfo:
    name: str
    status: str = "pending"  # pending | running | done | failed
    started_at: str | None = None
    finished_at: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "detail": self.detail,
        }

    def start(self) -> None:
        self.status = "running"
        self.started_at = datetime.utcnow().isoformat()

    def done(self, detail: str | None = None) -> None:
        self.status = "done"
        self.finished_at = datetime.utcnow().isoformat()
        if detail:
            self.detail = detail

    def fail(self, detail: str | None = None) -> None:
        self.status = "failed"
        self.finished_at = datetime.utcnow().isoformat()
        if detail:
            self.detail = detail


@dataclass
class TrainingRun:
    id: str
    design_id: int
    design_name: str = ""
    design_country: str = ""
    status: RunStatus = RunStatus.QUEUED
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    # Steps
    steps: list[StepInfo] = field(default_factory=list)
    # Training metrics (populated during training step)
    epoch: int = 0
    epochs_total: int = 0
    loss: float | None = None
    recall_at_1: float | None = None
    recall_at_3: float | None = None
    # Config
    config: dict = field(default_factory=dict)
    # Logs
    log_lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.steps:
            self.steps = [StepInfo(name=n) for n in STEP_NAMES]

    @property
    def steps_completed(self) -> int:
        return sum(1 for s in self.steps if s.status == "done")

    def to_dict(self, include_logs: bool = False) -> dict:
        d = {
            "id": self.id,
            "design_id": self.design_id,
            "design_name": self.design_name,
            "design_country": self.design_country,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "steps": [s.to_dict() for s in self.steps],
            "steps_completed": self.steps_completed,
            "steps_total": len(self.steps),
            "epoch": self.epoch,
            "epochs_total": self.epochs_total,
            "loss": self.loss,
            "recall_at_1": self.recall_at_1,
            "recall_at_3": self.recall_at_3,
            "config": self.config,
        }
        if include_logs:
            d["log_lines"] = self.log_lines
        return d


class TrainingRunner:
    """Manages a queue of training jobs with configurable concurrency."""

    def __init__(self) -> None:
        self._queue: deque[TrainingRun] = deque()
        self._active: list[TrainingRun] = []
        self._history: list[TrainingRun] = []
        self._all_runs: dict[str, TrainingRun] = {}
        self._lock = threading.Lock()
        self._max_concurrent: int = 1
        self._device: str = "mps"

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @max_concurrent.setter
    def max_concurrent(self, value: int) -> None:
        self._max_concurrent = max(1, min(value, 4))

    @property
    def device(self) -> str:
        return self._device

    @device.setter
    def device(self, value: str) -> None:
        self._device = value

    @property
    def active(self) -> list[TrainingRun]:
        return list(self._active)

    @property
    def queue(self) -> list[TrainingRun]:
        return list(self._queue)

    @property
    def history(self) -> list[TrainingRun]:
        return list(reversed(self._history[-20:]))

    def get_run(self, run_id: str) -> TrainingRun | None:
        return self._all_runs.get(run_id)

    def enqueue(
        self,
        design_ids: list[int],
        *,
        design_names: dict[int, str] | None = None,
        design_countries: dict[int, str] | None = None,
        epochs: int = 40,
        batch_size: int = 64,
        m_per_class: int = 4,
        target_augmented: int = 50,
    ) -> list[TrainingRun]:
        """Create one run per design_id and add to queue."""
        names = design_names or {}
        countries = design_countries or {}
        runs: list[TrainingRun] = []

        config = {
            "epochs": epochs,
            "batch_size": batch_size,
            "m_per_class": m_per_class,
            "target_augmented": target_augmented,
            "mode": "arcface",
        }

        with self._lock:
            for did in design_ids:
                run = TrainingRun(
                    id=str(uuid.uuid4())[:8],
                    design_id=did,
                    design_name=names.get(did, f"Design {did}"),
                    design_country=countries.get(did, ""),
                    config=config,
                )
                self._queue.append(run)
                self._all_runs[run.id] = run
                runs.append(run)

        self._maybe_start_next()
        return runs

    def remove_from_queue(self, run_id: str) -> bool:
        """Remove a queued job. Returns True if found and removed."""
        with self._lock:
            for run in self._queue:
                if run.id == run_id:
                    self._queue.remove(run)
                    del self._all_runs[run.id]
                    return True
        return False

    def _maybe_start_next(self) -> None:
        """Start the next queued job if capacity allows."""
        with self._lock:
            while len(self._active) < self._max_concurrent and self._queue:
                run = self._queue.popleft()
                self._active.append(run)
                thread = threading.Thread(
                    target=self._execute_run,
                    args=(run,),
                    daemon=True,
                )
                thread.start()

    def _execute_run(self, run: TrainingRun) -> None:
        """Execute the full training pipeline for one design."""
        run.status = RunStatus.RUNNING
        run.started_at = datetime.utcnow().isoformat()
        design_id_str = str(run.design_id)

        try:
            # Step 0: Augmentation
            step = run.steps[0]
            step.start()
            self._run_script(
                run,
                [
                    VENV_PYTHON,
                    str(ML_DIR / "augment_synthetic.py"),
                    "--coin-ids",
                    design_id_str,
                    "--target-per-class",
                    str(run.config["target_augmented"]),
                ],
            )
            aug_dir = DATASETS_DIR / design_id_str / "augmented"
            aug_count = len(list(aug_dir.glob("aug_*.jpg"))) if aug_dir.exists() else 0
            step.done(f"{aug_count} images")

            # Step 1: Prepare dataset
            step = run.steps[1]
            step.start()
            self._run_script(
                run,
                [VENV_PYTHON, str(ML_DIR / "prepare_dataset.py")],
            )
            # Count classes and images in the prepared dataset
            train_dir = DATASETS_DIR / "eurio-poc" / "train"
            if train_dir.exists():
                classes = [d for d in train_dir.iterdir() if d.is_dir()]
                total_imgs = sum(len(list(c.iterdir())) for c in classes)
                step.done(f"{len(classes)} classes, {total_imgs} images")
            else:
                step.done()

            # Step 2: Train ArcFace
            step = run.steps[2]
            step.start()
            run.epochs_total = run.config["epochs"]
            self._run_script(
                run,
                [
                    VENV_PYTHON,
                    str(ML_DIR / "train_embedder.py"),
                    "--mode",
                    "arcface",
                    "--dataset",
                    str(DATASETS_DIR / "eurio-poc" / "train"),
                    "--val-dataset",
                    str(DATASETS_DIR / "eurio-poc" / "val"),
                    "--epochs",
                    str(run.config["epochs"]),
                    "--batch-size",
                    str(run.config["batch_size"]),
                    "--m-per-class",
                    str(run.config["m_per_class"]),
                ],
                parse_training_output=True,
            )
            self._read_final_metrics(run)
            r1 = f"{run.recall_at_1:.0%}" if run.recall_at_1 is not None else "?"
            step.done(f"R@1: {r1}")

            # Step 3: Compute embeddings
            step = run.steps[3]
            step.start()
            self._run_script(
                run,
                [VENV_PYTHON, str(ML_DIR / "compute_embeddings.py")],
            )
            emb_path = OUTPUT_DIR / "embeddings_v1.json"
            if emb_path.exists():
                emb_data = json.loads(emb_path.read_text())
                n_classes = len(emb_data.get("coins", {}))
                dim = emb_data.get("embedding_dim", 256)
                step.done(f"{n_classes} classes, {dim}-dim")
            else:
                step.done()

            # Step 4: Seed Supabase
            step = run.steps[4]
            step.start()
            self._run_script(
                run,
                [VENV_PYTHON, str(ML_DIR / "seed_supabase.py")],
            )
            step.done("Synchronisé")

            run.status = RunStatus.COMPLETED

        except Exception as e:
            run.status = RunStatus.FAILED
            run.error = str(e)
            # Mark current running step as failed
            for s in run.steps:
                if s.status == "running":
                    s.fail(str(e))
                    break

        finally:
            run.finished_at = datetime.utcnow().isoformat()
            with self._lock:
                if run in self._active:
                    self._active.remove(run)
                self._history.append(run)
            self._maybe_start_next()

    def _run_script(
        self,
        run: TrainingRun,
        cmd: list[str],
        *,
        parse_training_output: bool = False,
    ) -> None:
        """Run a subprocess and stream output to the run's log."""
        proc = subprocess.Popen(
            cmd,
            cwd=str(ML_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            run.log_lines.append(line)
            if len(run.log_lines) > 200:
                run.log_lines = run.log_lines[-200:]

            if parse_training_output:
                self._parse_epoch_line(run, line)

        returncode = proc.wait()
        if returncode != 0:
            raise RuntimeError(
                f"Script failed (exit {returncode}): {' '.join(cmd)}"
            )

    def _parse_epoch_line(self, run: TrainingRun, line: str) -> None:
        """Parse training output to extract epoch/metrics."""
        if "Epoch" not in line or "loss:" not in line:
            return
        try:
            parts = line.strip().split()
            epoch_idx = parts.index("Epoch") + 1
            run.epoch = int(parts[epoch_idx])

            # Update step detail with current epoch
            step = run.steps[2]
            step.detail = f"Epoch {run.epoch}/{run.epochs_total}"

            for i, p in enumerate(parts):
                if p == "loss:":
                    run.loss = float(parts[i + 1])
                elif p == "R@1:":
                    run.recall_at_1 = float(parts[i + 1].rstrip("%")) / 100
                elif p == "R@3:":
                    run.recall_at_3 = float(parts[i + 1].rstrip("%")) / 100
        except (ValueError, IndexError):
            pass

    def _read_final_metrics(self, run: TrainingRun) -> None:
        """Read final metrics from the training log JSON."""
        log_path = CHECKPOINTS_DIR / "training_log.json"
        if not log_path.exists():
            return
        try:
            logs = json.loads(log_path.read_text())
            if logs:
                last = logs[-1]
                run.recall_at_1 = last.get("recall@1", run.recall_at_1)
                run.recall_at_3 = last.get("recall@3", run.recall_at_3)
                run.loss = last.get("train_loss", run.loss)
                run.epoch = last.get("epoch", run.epoch)
        except (json.JSONDecodeError, KeyError):
            pass
