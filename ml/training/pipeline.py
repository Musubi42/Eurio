"""Pipeline d'entraînement ArcFace — cœur d'orchestration (refacto-ml chunk 2a).

Extrait à l'identique de `api/training_runner.TrainingRunner._execute` & co. Le
but de l'extraction : rendre le pipeline exécutable **synchroniquement** dans un
process quelconque (thread API aujourd'hui, subprocess détaché au chunk 2b), sans
dépendre de l'état en mémoire du runner.

Le couplage à l'état live (buffer de logs, epoch courante, proc actif pour le
stop) passe par des **hooks** optionnels (`PipelineHooks`) :

  - en in-process (TrainingRunner), les hooks pointent sur `ActiveState` → la tail
    live et le `stop` de l'API continuent de marcher à l'identique ;
  - en détaché (chunk 2b), les hooks sont absents : l'état se lit depuis le fichier
    de log + la table `training_runs` + la row `jobs`.

Étapes (inchangées) :
  0. Suppression · 1. Préparation · 2. Entraînement · 3. Embeddings
  4. Synchronisation · 5. Validation per-class
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

from state import ClassMetricRow, ClassRef, EpochRow, RunRow, StepRow, Store

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).parent.parent
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
DATASETS_DIR = ML_DIR / "datasets"
CHECKPOINTS_DIR = ML_DIR / "checkpoints"
OUTPUT_DIR = ML_DIR / "output"
EURIO_POC = DATASETS_DIR / "eurio-poc"
PER_CLASS_METRICS = OUTPUT_DIR / "per_class_metrics.json"

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
class PipelineHooks:
    """Hooks optionnels vers l'état live du runner (in-process). Tous None en détaché."""

    on_log: Callable[[str], None] | None = None
    on_epoch: Callable[[int], None] | None = None
    on_epochs_total: Callable[[int], None] | None = None
    register_proc: Callable[[object | None], None] | None = None


class TrainingPipeline:
    """Exécute le pipeline d'un run synchroniquement. `run()` est bloquant.

    L'appelant a déjà créé la `RunRow` (status='queued') + les 6 steps 'pending'.
    """

    def __init__(
        self,
        store: Store,
        run_id: str,
        *,
        device: str = "auto",
        hooks: PipelineHooks | None = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._device = device
        self._hooks = hooks or PipelineHooks()
        self._log_lines: list[str] = []
        self._epoch_start_ts: float | None = None

    # ─── Boucle principale ───────────────────────────────────────────────

    def run(self) -> None:
        run_id = self._run_id
        version_str = self._version_string(run_id)
        try:
            self._store.update_run_status(run_id, "running", started_at=_now_iso())
            self._run_step(run_id, 0, lambda row: self._delete(row))
            self._run_step(run_id, 1, lambda row: self._prepare(row))
            self._run_step(run_id, 2, lambda row: self._train(row, version_str))
            self._run_step(run_id, 3, lambda row: self._compute_embeddings(row, version_str))
            self._run_step(run_id, 4, lambda row: self._seed(row))
            self._run_step(run_id, 5, lambda row: self._validate_per_class(row))
            self._finalize_run(run_id)
            self._store.update_run_status(run_id, "completed", finished_at=_now_iso())
        except Exception as exc:  # noqa: BLE001 — top-level run failure
            self._store.update_run_status(
                run_id, "failed", error=str(exc), finished_at=_now_iso()
            )
            raise
        finally:
            self._store.save_logs(run_id, self._log_lines)

    # ─── Hooks / logs ────────────────────────────────────────────────────

    def _emit_log(self, line: str) -> None:
        """Imprime (→ capté dans le fichier de log en détaché), bufferise pour
        l'archive `save_logs`, et mirroir live via le hook."""
        print(line, flush=True)
        self._log_lines.append(line)
        if self._hooks.on_log is not None:
            try:
                self._hooks.on_log(line)
            except Exception:  # noqa: BLE001 — side-channel de log, jamais bloquant
                logger.exception("Training on_log hook raised — ignoring")

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
                    step_index=idx, name=name, status=status,
                    started_at=started, finished_at=_now_iso(), detail=detail,
                ),
            )
        except Exception as exc:
            self._store.upsert_step(
                run_id,
                StepRow(
                    step_index=idx, name=name, status="failed",
                    started_at=started, finished_at=_now_iso(), detail=str(exc),
                ),
            )
            raise

    # ─── Étapes ──────────────────────────────────────────────────────────

    def _delete(self, row: RunRow) -> str:
        if _iter_dir(row) is not None:
            return "skipped (iter_dir self-contained)"
        if not row.classes_removed:
            return "skipped (no removed classes)"
        added_ids = {ref.class_id for ref in row.classes_added}
        resolver = _build_resolver()
        removed_count = 0
        for ref in row.classes_removed:
            if ref.class_id in added_ids:
                self._emit_log(f"  {ref.class_id}: also in classes_added, skipping removal")
                continue
            descriptor = resolver.for_class(ref.class_id)
            for split in ("train", "val", "test"):
                split_dir = EURIO_POC / split / ref.class_id
                if split_dir.exists():
                    shutil.rmtree(split_dir)
                    self._emit_log(f"  removed {split_dir}")
            _purge_supabase(ref, descriptor.eurio_ids if descriptor else ())
            removed_count += 1
        return f"{removed_count} class(es) removed"

    def _prepare(self, row: RunRow) -> str:
        cmd = [VENV_PYTHON, str(ML_DIR / "training" / "prepare_dataset.py")]
        iter_dir = _iter_dir(row)
        prepare_classes = (
            row.classes_added if iter_dir is not None else row.classes_after
        )
        if prepare_classes:
            only = ",".join(sorted({c.class_id for c in prepare_classes}))
            cmd.extend(["--only-classes", only])
        class_kind = row.config.get("class_kind", "design_group")
        cmd.extend(["--class-kind", class_kind])
        if iter_dir is not None:
            dataset_dir = iter_dir / "dataset"
            cmd.extend(["--output-dir", str(dataset_dir), "--skip-train-split"])
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
        self._epoch_start_ts = None
        if self._hooks.on_epoch is not None:
            self._hooks.on_epoch(0)
        if self._hooks.on_epochs_total is not None:
            self._hooks.on_epochs_total(int(cfg.get("epochs", 40)))
        iter_dir = _iter_dir(row)
        dataset_path = cfg.get("dataset_override") or str(EURIO_POC / "train")
        val_path = (
            str(iter_dir / "dataset" / "val") if iter_dir is not None
            else str(EURIO_POC / "val")
        )
        cmd: list[str] = [
            VENV_PYTHON,
            str(ML_DIR / "training" / "train_embedder.py"),
            "--mode", cfg.get("mode", "arcface"),
            "--dataset", dataset_path,
            "--val-dataset", val_path,
            "--epochs", str(cfg["epochs"]),
            "--batch-size", str(cfg["batch_size"]),
            "--m-per-class", str(cfg["m_per_class"]),
            "--device", self._device,
            "--model-version", version_str,
        ]
        if iter_dir is not None:
            cmd.extend(["--output", str(iter_dir / "checkpoints")])
        aug_recipe = cfg.get("aug_recipe") or row.aug_recipe_id
        prebaked = bool(cfg.get("prebaked_augmentations"))
        if prebaked:
            cmd.append("--prebaked-augmentations")
        elif aug_recipe:
            cmd.extend(["--aug-recipe", str(aug_recipe)])
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
            "--model-version", version_str,
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

    # ─── Finalisation ────────────────────────────────────────────────────

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
        self, run_id: str, cmd: list[str], *, parse_training_output: bool = False,
    ) -> None:
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(ML_DIR) + (os.pathsep + existing if existing else "")
        proc = subprocess.Popen(
            cmd, cwd=str(ML_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env,
        )
        if self._hooks.register_proc is not None:
            self._hooks.register_proc(proc)
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                self._emit_log(line)
                if parse_training_output:
                    self._parse_epoch_line(run_id, line)
            rc = proc.wait()
        finally:
            if self._hooks.register_proc is not None:
                self._hooks.register_proc(None)
        if rc != 0:
            if rc == 2:  # sentinelle d'arrêt coopératif de train_embedder.py
                raise RuntimeError("Stopped by user (graceful)")
            raise RuntimeError(f"Command failed (exit {rc}): {' '.join(cmd)}")

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
        if self._epoch_start_ts is not None:
            duration = now - self._epoch_start_ts
        self._epoch_start_ts = now
        if self._hooks.on_epoch is not None:
            self._hooks.on_epoch(epoch)

        self._store.append_epoch(
            run_id,
            EpochRow(
                epoch=epoch, train_loss=loss,
                recall_at_1=r1, recall_at_3=r3, duration_sec=duration,
            ),
        )
        self._store.upsert_step(
            run_id,
            StepRow(
                step_index=STEP_INDEX["Entraînement"], name="Entraînement",
                status="running", detail=f"Epoch {epoch}",
            ),
        )


# ─── Helpers module-level (partagés avec le runner) ──────────────────────


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
    """Racine per-iteration quand le run appartient à une itération
    (`config["iter_dir"]`, posé par IterationRunner). Absent → chemins singleton."""
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
