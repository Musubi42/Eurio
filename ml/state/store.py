"""SQLite store for local training state.

Single-writer, multi-reader via WAL. Thread-safe via per-thread connections
and a write lock. All reads return typed dataclass rows.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@dataclass(frozen=True)
class ClassRef:
    class_id: str
    class_kind: str

    def to_dict(self) -> dict:
        return {"class_id": self.class_id, "class_kind": self.class_kind}

    @classmethod
    def from_dict(cls, d: dict) -> "ClassRef":
        return cls(class_id=d["class_id"], class_kind=d["class_kind"])


@dataclass
class RunRow:
    id: str
    version: int
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    config: dict = field(default_factory=dict)
    classes_before: list[ClassRef] = field(default_factory=list)
    classes_after: list[ClassRef] = field(default_factory=list)
    classes_added: list[ClassRef] = field(default_factory=list)
    classes_removed: list[ClassRef] = field(default_factory=list)
    loss: float | None = None
    recall_at_1: float | None = None
    recall_at_3: float | None = None
    epoch_duration_median_sec: float | None = None
    error: str | None = None
    aug_recipe_id: str | None = None


@dataclass
class StepRow:
    step_index: int
    name: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    detail: str | None = None


@dataclass
class EpochRow:
    epoch: int
    train_loss: float | None = None
    recall_at_1: float | None = None
    recall_at_3: float | None = None
    lr: float | None = None
    duration_sec: float | None = None


@dataclass
class ClassMetricRow:
    class_id: str
    class_kind: str
    recall_at_1: float | None = None
    n_train_images: int | None = None
    n_val_images: int | None = None


@dataclass
class AugmentationRecipeRow:
    id: str
    name: str
    zone: str | None
    config: dict
    based_on_recipe_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "zone": self.zone,
            "config": self.config,
            "based_on_recipe_id": self.based_on_recipe_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class AugmentationRunRow:
    id: str
    recipe_id: str | None
    eurio_id: str | None
    design_group_id: str | None
    count: int
    seed: int | None
    output_dir: str
    status: str
    duration_ms: int | None = None
    error: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recipe_id": self.recipe_id,
            "eurio_id": self.eurio_id,
            "design_group_id": self.design_group_id,
            "count": self.count,
            "seed": self.seed,
            "output_dir": self.output_dir,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass
class BenchmarkRunRow:
    id: str
    model_path: str
    model_name: str
    training_run_id: str | None = None
    recipe_id: str | None = None
    eurio_ids: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    num_photos: int = 0
    num_coins: int = 0
    r_at_1: float | None = None
    r_at_3: float | None = None
    r_at_5: float | None = None
    mean_spread: float | None = None
    per_zone: dict = field(default_factory=dict)
    per_coin: list[dict] = field(default_factory=list)
    per_condition: dict = field(default_factory=dict)
    confusion: dict = field(default_factory=dict)
    top_confusions: list[dict] = field(default_factory=list)
    report_path: str = ""
    status: str = "running"
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "model_path": self.model_path,
            "model_name": self.model_name,
            "training_run_id": self.training_run_id,
            "recipe_id": self.recipe_id,
            "eurio_ids": self.eurio_ids,
            "zones": self.zones,
            "num_photos": self.num_photos,
            "num_coins": self.num_coins,
            "r_at_1": self.r_at_1,
            "r_at_3": self.r_at_3,
            "r_at_5": self.r_at_5,
            "mean_spread": self.mean_spread,
            "per_zone": self.per_zone,
            "per_coin": self.per_coin,
            "per_condition": self.per_condition,
            "confusion": self.confusion,
            "top_confusions": self.top_confusions,
            "report_path": self.report_path,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class ExperimentCohortRow:
    id: str
    name: str
    description: str | None = None
    zone: str | None = None
    eurio_ids: list[str] = field(default_factory=list)
    status: str = "draft"
    frozen_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "zone": self.zone,
            "eurio_ids": self.eurio_ids,
            "status": self.status,
            "frozen_at": self.frozen_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ExperimentIterationRow:
    id: str
    cohort_id: str
    name: str
    status: str = "pending"
    parent_iteration_id: str | None = None
    hypothesis: str | None = None
    recipe_id: str | None = None
    variant_count: int = 100
    training_config: dict = field(default_factory=dict)
    training_run_id: str | None = None
    benchmark_run_id: str | None = None
    verdict: str | None = None
    verdict_override: str | None = None
    delta_vs_parent: dict = field(default_factory=dict)
    diff_from_parent: dict = field(default_factory=dict)
    notes: str | None = None
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cohort_id": self.cohort_id,
            "parent_iteration_id": self.parent_iteration_id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "recipe_id": self.recipe_id,
            "variant_count": self.variant_count,
            "training_config": self.training_config,
            "status": self.status,
            "training_run_id": self.training_run_id,
            "benchmark_run_id": self.benchmark_run_id,
            "verdict": self.verdict,
            "verdict_override": self.verdict_override,
            "delta_vs_parent": self.delta_vs_parent,
            "diff_from_parent": self.diff_from_parent,
            "notes": self.notes,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class Store:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._local = threading.local()
        self._bootstrap()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _bootstrap(self) -> None:
        schema = _SCHEMA_PATH.read_text()
        with self._write_lock:
            conn = self._connection()
            conn.executescript(schema)
            self._ensure_column(
                conn,
                table="training_runs",
                column="aug_recipe_id",
                decl="TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL",
            )
            self._ensure_column(
                conn,
                table="training_staging",
                column="aug_recipe_id",
                decl="TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL",
            )
            self._ensure_column(
                conn,
                table="benchmark_runs",
                column="per_condition_json",
                decl="TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                conn,
                table="experiment_cohorts",
                column="status",
                decl="TEXT NOT NULL DEFAULT 'draft'",
            )
            self._ensure_column(
                conn,
                table="experiment_cohorts",
                column="frozen_at",
                decl="TEXT",
            )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        decl: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {r["name"] for r in rows}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    @contextmanager
    def _writing(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self._connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def wal_checkpoint(self) -> None:
        with self._write_lock:
            self._connection().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # ─── Runs ────────────────────────────────────────────────────────────

    def next_version(self) -> int:
        row = self._connection().execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM training_runs"
        ).fetchone()
        return int(row["v"])

    def create_run(self, run: RunRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO training_runs (
                  id, version, status, started_at, finished_at, config_json,
                  classes_before_json, classes_after_json,
                  classes_added_json, classes_removed_json,
                  loss, recall_at_1, recall_at_3,
                  epoch_duration_median_sec, error, aug_recipe_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.version,
                    run.status,
                    run.started_at,
                    run.finished_at,
                    json.dumps(run.config),
                    _dump_refs(run.classes_before),
                    _dump_refs(run.classes_after),
                    _dump_refs(run.classes_added),
                    _dump_refs(run.classes_removed),
                    run.loss,
                    run.recall_at_1,
                    run.recall_at_3,
                    run.epoch_duration_median_sec,
                    run.error,
                    run.aug_recipe_id,
                ),
            )

    def update_run_aug_recipe(self, run_id: str, aug_recipe_id: str | None) -> None:
        with self._writing() as c:
            c.execute(
                "UPDATE training_runs SET aug_recipe_id = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (aug_recipe_id, run_id),
            )

    def update_run_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        fields_sql = ["status = ?", "updated_at = datetime('now')"]
        params: list = [status]
        if error is not None:
            fields_sql.append("error = ?")
            params.append(error)
        if started_at is not None:
            fields_sql.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            fields_sql.append("finished_at = ?")
            params.append(finished_at)
        params.append(run_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE training_runs SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def update_run_metrics(
        self,
        run_id: str,
        *,
        loss: float | None = None,
        recall_at_1: float | None = None,
        recall_at_3: float | None = None,
        epoch_duration_median_sec: float | None = None,
    ) -> None:
        with self._writing() as c:
            c.execute(
                """
                UPDATE training_runs SET
                  loss = COALESCE(?, loss),
                  recall_at_1 = COALESCE(?, recall_at_1),
                  recall_at_3 = COALESCE(?, recall_at_3),
                  epoch_duration_median_sec = COALESCE(?, epoch_duration_median_sec),
                  updated_at = datetime('now')
                WHERE id = ?
                """,
                (loss, recall_at_1, recall_at_3, epoch_duration_median_sec, run_id),
            )

    def update_run_classes_after(self, run_id: str, classes: list[ClassRef]) -> None:
        with self._writing() as c:
            c.execute(
                "UPDATE training_runs SET classes_after_json = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (_dump_refs(classes), run_id),
            )

    def get_run(self, run_id: str) -> RunRow | None:
        row = self._connection().execute(
            "SELECT * FROM training_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[RunRow]:
        q = "SELECT * FROM training_runs"
        params: list = []
        if status is not None:
            q += " WHERE status = ?"
            params.append(status)
        q += " ORDER BY version DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [
            _row_to_run(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def count_runs(self, *, status: str | None = None) -> int:
        q = "SELECT COUNT(*) AS n FROM training_runs"
        params: list = []
        if status is not None:
            q += " WHERE status = ?"
            params.append(status)
        return int(self._connection().execute(q, params).fetchone()["n"])

    def delete_run(self, run_id: str) -> None:
        with self._writing() as c:
            c.execute("DELETE FROM training_runs WHERE id = ?", (run_id,))

    def prune_runs(self, *, keep_last: int) -> int:
        """Delete runs beyond the most recent N. Returns number deleted."""
        if keep_last < 0:
            raise ValueError("keep_last must be >= 0")
        with self._writing() as c:
            cur = c.execute(
                """
                DELETE FROM training_runs WHERE id IN (
                  SELECT id FROM training_runs
                  ORDER BY version DESC
                  LIMIT -1 OFFSET ?
                )
                """,
                (keep_last,),
            )
            return cur.rowcount

    # ─── Steps ───────────────────────────────────────────────────────────

    def upsert_step(self, run_id: str, step: StepRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO training_run_steps (
                  run_id, step_index, name, status, started_at, finished_at, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, step_index) DO UPDATE SET
                  name = excluded.name,
                  status = excluded.status,
                  started_at = COALESCE(excluded.started_at, training_run_steps.started_at),
                  finished_at = COALESCE(excluded.finished_at, training_run_steps.finished_at),
                  detail = excluded.detail
                """,
                (
                    run_id,
                    step.step_index,
                    step.name,
                    step.status,
                    step.started_at,
                    step.finished_at,
                    step.detail,
                ),
            )

    def list_steps(self, run_id: str) -> list[StepRow]:
        rows = self._connection().execute(
            "SELECT * FROM training_run_steps WHERE run_id = ? ORDER BY step_index",
            (run_id,),
        ).fetchall()
        return [
            StepRow(
                step_index=r["step_index"],
                name=r["name"],
                status=r["status"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                detail=r["detail"],
            )
            for r in rows
        ]

    # ─── Epochs ──────────────────────────────────────────────────────────

    def append_epoch(self, run_id: str, epoch: EpochRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO training_run_epochs (
                  run_id, epoch, train_loss, recall_at_1, recall_at_3, lr, duration_sec
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, epoch) DO UPDATE SET
                  train_loss = excluded.train_loss,
                  recall_at_1 = excluded.recall_at_1,
                  recall_at_3 = excluded.recall_at_3,
                  lr = excluded.lr,
                  duration_sec = excluded.duration_sec
                """,
                (
                    run_id,
                    epoch.epoch,
                    epoch.train_loss,
                    epoch.recall_at_1,
                    epoch.recall_at_3,
                    epoch.lr,
                    epoch.duration_sec,
                ),
            )

    def list_epochs(self, run_id: str) -> list[EpochRow]:
        rows = self._connection().execute(
            "SELECT * FROM training_run_epochs WHERE run_id = ? ORDER BY epoch",
            (run_id,),
        ).fetchall()
        return [
            EpochRow(
                epoch=r["epoch"],
                train_loss=r["train_loss"],
                recall_at_1=r["recall_at_1"],
                recall_at_3=r["recall_at_3"],
                lr=r["lr"],
                duration_sec=r["duration_sec"],
            )
            for r in rows
        ]

    # ─── Per-class metrics ───────────────────────────────────────────────

    def set_run_classes(self, run_id: str, classes: list[ClassMetricRow]) -> None:
        with self._writing() as c:
            c.execute("DELETE FROM training_run_classes WHERE run_id = ?", (run_id,))
            if classes:
                c.executemany(
                    """
                    INSERT INTO training_run_classes (
                      run_id, class_id, class_kind, recall_at_1,
                      n_train_images, n_val_images
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            m.class_id,
                            m.class_kind,
                            m.recall_at_1,
                            m.n_train_images,
                            m.n_val_images,
                        )
                        for m in classes
                    ],
                )

    def list_classes_for_run(self, run_id: str) -> list[ClassMetricRow]:
        rows = self._connection().execute(
            "SELECT * FROM training_run_classes WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return [
            ClassMetricRow(
                class_id=r["class_id"],
                class_kind=r["class_kind"],
                recall_at_1=r["recall_at_1"],
                n_train_images=r["n_train_images"],
                n_val_images=r["n_val_images"],
            )
            for r in rows
        ]

    def list_runs_for_class(self, class_id: str) -> list[tuple[RunRow, ClassMetricRow]]:
        rows = self._connection().execute(
            """
            SELECT r.*,
                   c.class_kind       AS c_class_kind,
                   c.recall_at_1      AS c_recall_at_1,
                   c.n_train_images   AS c_n_train,
                   c.n_val_images     AS c_n_val
            FROM training_run_classes c
            JOIN training_runs r ON r.id = c.run_id
            WHERE c.class_id = ?
            ORDER BY r.version DESC
            """,
            (class_id,),
        ).fetchall()
        return [
            (
                _row_to_run(r),
                ClassMetricRow(
                    class_id=class_id,
                    class_kind=r["c_class_kind"],
                    recall_at_1=r["c_recall_at_1"],
                    n_train_images=r["c_n_train"],
                    n_val_images=r["c_n_val"],
                ),
            )
            for r in rows
        ]

    # ─── Logs (compressed) ───────────────────────────────────────────────

    def save_logs(self, run_id: str, lines: list[str]) -> None:
        text = "\n".join(lines)
        blob = gzip.compress(text.encode("utf-8"))
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO training_run_logs (run_id, log_gz, line_count)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  log_gz = excluded.log_gz,
                  line_count = excluded.line_count
                """,
                (run_id, blob, len(lines)),
            )

    def load_logs(self, run_id: str) -> list[str]:
        row = self._connection().execute(
            "SELECT log_gz FROM training_run_logs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return []
        return gzip.decompress(row["log_gz"]).decode("utf-8").splitlines()

    # ─── Staging (add) ───────────────────────────────────────────────────

    def stage_classes(
        self,
        items: list[ClassRef],
        *,
        aug_recipe_ids: list[str | None] | None = None,
    ) -> None:
        """Stage classes for the next training run.

        ``aug_recipe_ids`` is an optional parallel list — same length as
        ``items`` — associating each class with a recipe id (or None).
        Backwards-compatible: callers that pass only ``items`` get the legacy
        behaviour (aug_recipe_id stays null).
        """
        if not items:
            return
        if aug_recipe_ids is None:
            aug_recipe_ids = [None] * len(items)
        if len(aug_recipe_ids) != len(items):
            raise ValueError(
                f"aug_recipe_ids length {len(aug_recipe_ids)} != items length {len(items)}"
            )
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO training_staging (class_id, class_kind, aug_recipe_id)
                VALUES (?, ?, ?)
                ON CONFLICT(class_id) DO UPDATE SET
                  class_kind = excluded.class_kind,
                  aug_recipe_id = excluded.aug_recipe_id,
                  staged_at = datetime('now')
                """,
                [
                    (item.class_id, item.class_kind, recipe_id)
                    for item, recipe_id in zip(items, aug_recipe_ids)
                ],
            )

    def unstage_class(self, class_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM training_staging WHERE class_id = ?",
                (class_id,),
            )
            return cur.rowcount > 0

    def list_staging(self) -> list[ClassRef]:
        rows = self._connection().execute(
            "SELECT class_id, class_kind FROM training_staging ORDER BY staged_at"
        ).fetchall()
        return [ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]) for r in rows]

    def list_staging_with_recipe(self) -> list[tuple[ClassRef, str | None]]:
        """Same as list_staging but also returns the aug_recipe_id per item."""
        rows = self._connection().execute(
            "SELECT class_id, class_kind, aug_recipe_id FROM training_staging "
            "ORDER BY staged_at"
        ).fetchall()
        return [
            (
                ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]),
                r["aug_recipe_id"],
            )
            for r in rows
        ]

    def clear_staging(self) -> list[ClassRef]:
        with self._writing() as c:
            rows = c.execute(
                "SELECT class_id, class_kind FROM training_staging"
            ).fetchall()
            c.execute("DELETE FROM training_staging")
            return [
                ClassRef(class_id=r["class_id"], class_kind=r["class_kind"])
                for r in rows
            ]

    def clear_staging_with_recipe(self) -> list[tuple[ClassRef, str | None]]:
        """Drain the staging table and also return the aug_recipe_id per item."""
        with self._writing() as c:
            rows = c.execute(
                "SELECT class_id, class_kind, aug_recipe_id FROM training_staging"
            ).fetchall()
            c.execute("DELETE FROM training_staging")
            return [
                (
                    ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]),
                    r["aug_recipe_id"],
                )
                for r in rows
            ]

    # ─── Staging (removal) ───────────────────────────────────────────────

    def stage_removal(self, items: list[ClassRef]) -> None:
        if not items:
            return
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO training_removal_staging (class_id, class_kind)
                VALUES (?, ?)
                ON CONFLICT(class_id) DO UPDATE SET
                  class_kind = excluded.class_kind,
                  staged_at = datetime('now')
                """,
                [(i.class_id, i.class_kind) for i in items],
            )

    def unstage_removal(self, class_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM training_removal_staging WHERE class_id = ?",
                (class_id,),
            )
            return cur.rowcount > 0

    def list_removal_staging(self) -> list[ClassRef]:
        rows = self._connection().execute(
            "SELECT class_id, class_kind FROM training_removal_staging "
            "ORDER BY staged_at"
        ).fetchall()
        return [ClassRef(class_id=r["class_id"], class_kind=r["class_kind"]) for r in rows]

    def clear_removal_staging(self) -> list[ClassRef]:
        with self._writing() as c:
            rows = c.execute(
                "SELECT class_id, class_kind FROM training_removal_staging"
            ).fetchall()
            c.execute("DELETE FROM training_removal_staging")
            return [
                ClassRef(class_id=r["class_id"], class_kind=r["class_kind"])
                for r in rows
            ]

    # ─── Augmentation recipes ────────────────────────────────────────────

    def create_recipe(self, recipe: AugmentationRecipeRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO augmentation_recipes (
                  id, name, zone, config_json, based_on_recipe_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    recipe.id,
                    recipe.name,
                    recipe.zone,
                    json.dumps(recipe.config),
                    recipe.based_on_recipe_id,
                ),
            )

    def update_recipe(
        self,
        recipe_id: str,
        *,
        name: str | None = None,
        zone: str | None = None,
        config: dict | None = None,
    ) -> None:
        fields_sql = ["updated_at = datetime('now')"]
        params: list = []
        if name is not None:
            fields_sql.append("name = ?")
            params.append(name)
        if zone is not None:
            fields_sql.append("zone = ?")
            params.append(zone)
        if config is not None:
            fields_sql.append("config_json = ?")
            params.append(json.dumps(config))
        if len(fields_sql) == 1:
            return
        params.append(recipe_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE augmentation_recipes SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_recipe(self, id_or_name: str) -> AugmentationRecipeRow | None:
        """Lookup by id first, then by name. Returns None if nothing matches."""
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM augmentation_recipes WHERE id = ?", (id_or_name,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM augmentation_recipes WHERE name = ?", (id_or_name,)
            ).fetchone()
        return _row_to_recipe(row) if row else None

    def list_recipes(self, *, zone: str | None = None) -> list[AugmentationRecipeRow]:
        q = "SELECT * FROM augmentation_recipes"
        params: list = []
        if zone is not None:
            q += " WHERE zone = ?"
            params.append(zone)
        q += " ORDER BY created_at DESC"
        return [
            _row_to_recipe(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def delete_recipe(self, recipe_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM augmentation_recipes WHERE id = ?", (recipe_id,)
            )
            return cur.rowcount > 0

    # ─── Augmentation runs (preview) ─────────────────────────────────────

    def create_aug_run(self, run: AugmentationRunRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO augmentation_runs (
                  id, recipe_id, eurio_id, design_group_id,
                  count, seed, output_dir, status, duration_ms, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.recipe_id,
                    run.eurio_id,
                    run.design_group_id,
                    run.count,
                    run.seed,
                    run.output_dir,
                    run.status,
                    run.duration_ms,
                    run.error,
                ),
            )

    def update_aug_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        fields_sql: list[str] = []
        params: list = []
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if duration_ms is not None:
            fields_sql.append("duration_ms = ?")
            params.append(duration_ms)
        if error is not None:
            fields_sql.append("error = ?")
            params.append(error)
        if not fields_sql:
            return
        params.append(run_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE augmentation_runs SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_aug_run(self, run_id: str) -> AugmentationRunRow | None:
        row = self._connection().execute(
            "SELECT * FROM augmentation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_aug_run(row) if row else None

    def prune_aug_runs_older_than(self, *, seconds: int) -> list[AugmentationRunRow]:
        """Return (and delete) aug_runs older than ``seconds`` — caller is
        responsible for deleting the on-disk output_dir.

        The comparison is inclusive (``<=``) so that ``seconds=0`` drains all
        existing rows, matching the "expire everything" intent.
        """
        cutoff_sql = f"datetime('now', '-{int(seconds)} seconds')"
        with self._writing() as c:
            rows = c.execute(
                f"SELECT * FROM augmentation_runs WHERE created_at <= {cutoff_sql}"
            ).fetchall()
            c.execute(
                f"DELETE FROM augmentation_runs WHERE created_at <= {cutoff_sql}"
            )
            return [_row_to_aug_run(r) for r in rows]

    # ─── Benchmark runs ──────────────────────────────────────────────────

    def create_benchmark_run(self, run: BenchmarkRunRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO benchmark_runs (
                  id, model_path, model_name, training_run_id, recipe_id,
                  eurio_ids_json, zones_json, num_photos, num_coins,
                  r_at_1, r_at_3, r_at_5, mean_spread,
                  per_zone_json, per_coin_json, per_condition_json,
                  confusion_json, top_confusions_json,
                  report_path, status, error, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?)
                """,
                (
                    run.id,
                    run.model_path,
                    run.model_name,
                    run.training_run_id,
                    run.recipe_id,
                    json.dumps(run.eurio_ids),
                    json.dumps(run.zones),
                    run.num_photos,
                    run.num_coins,
                    run.r_at_1,
                    run.r_at_3,
                    run.r_at_5,
                    run.mean_spread,
                    json.dumps(run.per_zone),
                    json.dumps(run.per_coin),
                    json.dumps(run.per_condition),
                    json.dumps(run.confusion),
                    json.dumps(run.top_confusions),
                    run.report_path,
                    run.status,
                    run.error,
                    run.started_at,
                    run.finished_at,
                ),
            )

    def update_benchmark_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        training_run_id: str | None = None,
        num_photos: int | None = None,
        num_coins: int | None = None,
        r_at_1: float | None = None,
        r_at_3: float | None = None,
        r_at_5: float | None = None,
        mean_spread: float | None = None,
        per_zone: dict | None = None,
        per_coin: list[dict] | None = None,
        per_condition: dict | None = None,
        confusion: dict | None = None,
        top_confusions: list[dict] | None = None,
        report_path: str | None = None,
        error: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        fields_sql: list[str] = []
        params: list = []
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if training_run_id is not None:
            fields_sql.append("training_run_id = ?")
            params.append(training_run_id)
        if num_photos is not None:
            fields_sql.append("num_photos = ?")
            params.append(num_photos)
        if num_coins is not None:
            fields_sql.append("num_coins = ?")
            params.append(num_coins)
        if r_at_1 is not None:
            fields_sql.append("r_at_1 = ?")
            params.append(r_at_1)
        if r_at_3 is not None:
            fields_sql.append("r_at_3 = ?")
            params.append(r_at_3)
        if r_at_5 is not None:
            fields_sql.append("r_at_5 = ?")
            params.append(r_at_5)
        if mean_spread is not None:
            fields_sql.append("mean_spread = ?")
            params.append(mean_spread)
        if per_zone is not None:
            fields_sql.append("per_zone_json = ?")
            params.append(json.dumps(per_zone))
        if per_coin is not None:
            fields_sql.append("per_coin_json = ?")
            params.append(json.dumps(per_coin))
        if per_condition is not None:
            fields_sql.append("per_condition_json = ?")
            params.append(json.dumps(per_condition))
        if confusion is not None:
            fields_sql.append("confusion_json = ?")
            params.append(json.dumps(confusion))
        if top_confusions is not None:
            fields_sql.append("top_confusions_json = ?")
            params.append(json.dumps(top_confusions))
        if report_path is not None:
            fields_sql.append("report_path = ?")
            params.append(report_path)
        if error is not None:
            fields_sql.append("error = ?")
            params.append(error)
        if finished_at is not None:
            fields_sql.append("finished_at = ?")
            params.append(finished_at)
        if not fields_sql:
            return
        params.append(run_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE benchmark_runs SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_benchmark_run(self, run_id: str) -> BenchmarkRunRow | None:
        row = self._connection().execute(
            "SELECT * FROM benchmark_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_benchmark_run(row) if row else None

    def list_benchmark_runs(
        self,
        *,
        model_name: str | None = None,
        recipe_id: str | None = None,
        zone: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BenchmarkRunRow]:
        clauses: list[str] = []
        params: list = []
        if model_name is not None:
            clauses.append("model_name = ?")
            params.append(model_name)
        if recipe_id is not None:
            clauses.append("recipe_id = ?")
            params.append(recipe_id)
        # `zone` filter matches runs whose zones_json contains the zone name;
        # SQLite JSON1 is not guaranteed — we do a LIKE on the serialized list.
        if zone is not None:
            clauses.append("zones_json LIKE ?")
            params.append(f'%"{zone}"%')
        q = "SELECT * FROM benchmark_runs"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [
            _row_to_benchmark_run(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def count_benchmark_runs(self) -> int:
        row = self._connection().execute(
            "SELECT COUNT(*) AS n FROM benchmark_runs"
        ).fetchone()
        return int(row["n"])

    def delete_benchmark_run(self, run_id: str) -> BenchmarkRunRow | None:
        with self._writing() as c:
            row = c.execute(
                "SELECT * FROM benchmark_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            c.execute("DELETE FROM benchmark_runs WHERE id = ?", (run_id,))
            return _row_to_benchmark_run(row)

    # ─── Experiment cohorts ──────────────────────────────────────────────

    def create_cohort(self, cohort: ExperimentCohortRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO experiment_cohorts (
                  id, name, description, zone, eurio_ids_json, status, frozen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cohort.id,
                    cohort.name,
                    cohort.description,
                    cohort.zone,
                    json.dumps(cohort.eurio_ids),
                    cohort.status,
                    cohort.frozen_at,
                ),
            )

    def update_cohort(
        self,
        cohort_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        zone: str | None = None,
        eurio_ids: list[str] | None = None,
        status: str | None = None,
        frozen_at: str | None = None,
    ) -> None:
        """Update mutable cohort fields.

        `eurio_ids` and `status` should only be touched while the cohort is
        ``draft``; the route layer enforces that — the store stays dumb.
        """
        fields_sql = ["updated_at = datetime('now')"]
        params: list = []
        if name is not None:
            fields_sql.append("name = ?")
            params.append(name)
        if description is not None:
            fields_sql.append("description = ?")
            params.append(description)
        if zone is not None:
            fields_sql.append("zone = ?")
            params.append(zone)
        if eurio_ids is not None:
            fields_sql.append("eurio_ids_json = ?")
            params.append(json.dumps(eurio_ids))
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if frozen_at is not None:
            fields_sql.append("frozen_at = ?")
            params.append(frozen_at)
        if len(fields_sql) == 1:
            return
        params.append(cohort_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE experiment_cohorts SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_cohort(self, id_or_name: str) -> ExperimentCohortRow | None:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM experiment_cohorts WHERE id = ?", (id_or_name,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM experiment_cohorts WHERE name = ?", (id_or_name,)
            ).fetchone()
        return _row_to_cohort(row) if row else None

    def list_cohorts(
        self,
        *,
        zone: str | None = None,
        status: str | None = None,
    ) -> list[ExperimentCohortRow]:
        q = "SELECT * FROM experiment_cohorts"
        clauses: list[str] = []
        params: list = []
        if zone is not None:
            clauses.append("zone = ?")
            params.append(zone)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_at DESC"
        return [
            _row_to_cohort(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def delete_cohort(self, cohort_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM experiment_cohorts WHERE id = ?", (cohort_id,)
            )
            return cur.rowcount > 0

    # ─── Experiment iterations ───────────────────────────────────────────

    def create_iteration(self, iteration: ExperimentIterationRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO experiment_iterations (
                  id, cohort_id, parent_iteration_id, name, hypothesis,
                  recipe_id, variant_count, training_config_json,
                  status, training_run_id, benchmark_run_id,
                  verdict, verdict_override,
                  delta_vs_parent_json, diff_from_parent_json,
                  notes, error, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iteration.id,
                    iteration.cohort_id,
                    iteration.parent_iteration_id,
                    iteration.name,
                    iteration.hypothesis,
                    iteration.recipe_id,
                    iteration.variant_count,
                    json.dumps(iteration.training_config),
                    iteration.status,
                    iteration.training_run_id,
                    iteration.benchmark_run_id,
                    iteration.verdict,
                    iteration.verdict_override,
                    json.dumps(iteration.delta_vs_parent),
                    json.dumps(iteration.diff_from_parent),
                    iteration.notes,
                    iteration.error,
                    iteration.started_at,
                    iteration.finished_at,
                ),
            )

    def update_iteration(
        self,
        iteration_id: str,
        *,
        status: str | None = None,
        training_run_id: str | None = None,
        benchmark_run_id: str | None = None,
        verdict: str | None = None,
        verdict_override: str | None = None,
        delta_vs_parent: dict | None = None,
        diff_from_parent: dict | None = None,
        notes: str | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        fields_sql: list[str] = []
        params: list = []
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if training_run_id is not None:
            fields_sql.append("training_run_id = ?")
            params.append(training_run_id)
        if benchmark_run_id is not None:
            fields_sql.append("benchmark_run_id = ?")
            params.append(benchmark_run_id)
        if verdict is not None:
            fields_sql.append("verdict = ?")
            params.append(verdict)
        if verdict_override is not None:
            fields_sql.append("verdict_override = ?")
            params.append(verdict_override)
        if delta_vs_parent is not None:
            fields_sql.append("delta_vs_parent_json = ?")
            params.append(json.dumps(delta_vs_parent))
        if diff_from_parent is not None:
            fields_sql.append("diff_from_parent_json = ?")
            params.append(json.dumps(diff_from_parent))
        if notes is not None:
            fields_sql.append("notes = ?")
            params.append(notes)
        if error is not None:
            fields_sql.append("error = ?")
            params.append(error)
        if started_at is not None:
            fields_sql.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            fields_sql.append("finished_at = ?")
            params.append(finished_at)
        if not fields_sql:
            return
        params.append(iteration_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE experiment_iterations SET {', '.join(fields_sql)} "
                f"WHERE id = ?",
                params,
            )

    def get_iteration(self, iteration_id: str) -> ExperimentIterationRow | None:
        row = self._connection().execute(
            "SELECT * FROM experiment_iterations WHERE id = ?", (iteration_id,)
        ).fetchone()
        return _row_to_iteration(row) if row else None

    def list_iterations(
        self,
        *,
        cohort_id: str | None = None,
        status: str | None = None,
    ) -> list[ExperimentIterationRow]:
        clauses: list[str] = []
        params: list = []
        if cohort_id is not None:
            clauses.append("cohort_id = ?")
            params.append(cohort_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        q = "SELECT * FROM experiment_iterations"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_at ASC"
        return [
            _row_to_iteration(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def delete_iteration(self, iteration_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM experiment_iterations WHERE id = ?", (iteration_id,)
            )
            return cur.rowcount > 0


def _dump_refs(refs: list[ClassRef]) -> str:
    return json.dumps([r.to_dict() for r in refs])


def _load_refs(raw: str) -> list[ClassRef]:
    return [ClassRef.from_dict(d) for d in json.loads(raw)]


def _row_to_run(r: sqlite3.Row) -> RunRow:
    return RunRow(
        id=r["id"],
        version=r["version"],
        status=r["status"],
        started_at=r["started_at"],
        finished_at=r["finished_at"],
        config=json.loads(r["config_json"]),
        classes_before=_load_refs(r["classes_before_json"]),
        classes_after=_load_refs(r["classes_after_json"]),
        classes_added=_load_refs(r["classes_added_json"]),
        classes_removed=_load_refs(r["classes_removed_json"]),
        loss=r["loss"],
        recall_at_1=r["recall_at_1"],
        recall_at_3=r["recall_at_3"],
        epoch_duration_median_sec=r["epoch_duration_median_sec"],
        error=r["error"],
        aug_recipe_id=_optional_column(r, "aug_recipe_id"),
    )


def _optional_column(row: sqlite3.Row, name: str) -> object | None:
    """Return ``row[name]`` if the column exists on the row, else None.

    SQLite rows fetched via older schemas may not expose new columns; we treat
    a missing column the same as NULL.
    """
    try:
        return row[name]
    except (IndexError, KeyError):
        return None


def _row_to_recipe(r: sqlite3.Row) -> AugmentationRecipeRow:
    return AugmentationRecipeRow(
        id=r["id"],
        name=r["name"],
        zone=r["zone"],
        config=json.loads(r["config_json"]),
        based_on_recipe_id=r["based_on_recipe_id"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_aug_run(r: sqlite3.Row) -> AugmentationRunRow:
    return AugmentationRunRow(
        id=r["id"],
        recipe_id=r["recipe_id"],
        eurio_id=r["eurio_id"],
        design_group_id=r["design_group_id"],
        count=r["count"],
        seed=r["seed"],
        output_dir=r["output_dir"],
        status=r["status"],
        duration_ms=r["duration_ms"],
        error=r["error"],
        created_at=r["created_at"],
    )


def _row_to_benchmark_run(r: sqlite3.Row) -> BenchmarkRunRow:
    per_cond_raw = _optional_column(r, "per_condition_json")
    per_condition = json.loads(per_cond_raw) if isinstance(per_cond_raw, str) else {}
    return BenchmarkRunRow(
        id=r["id"],
        model_path=r["model_path"],
        model_name=r["model_name"],
        training_run_id=r["training_run_id"],
        recipe_id=r["recipe_id"],
        eurio_ids=json.loads(r["eurio_ids_json"]),
        zones=json.loads(r["zones_json"]),
        num_photos=r["num_photos"],
        num_coins=r["num_coins"],
        r_at_1=r["r_at_1"],
        r_at_3=r["r_at_3"],
        r_at_5=r["r_at_5"],
        mean_spread=r["mean_spread"],
        per_zone=json.loads(r["per_zone_json"]),
        per_coin=json.loads(r["per_coin_json"]),
        per_condition=per_condition,
        confusion=json.loads(r["confusion_json"]),
        top_confusions=json.loads(r["top_confusions_json"]),
        report_path=r["report_path"],
        status=r["status"],
        error=r["error"],
        started_at=r["started_at"],
        finished_at=r["finished_at"],
    )


def _row_to_cohort(r: sqlite3.Row) -> ExperimentCohortRow:
    return ExperimentCohortRow(
        id=r["id"],
        name=r["name"],
        description=r["description"],
        zone=r["zone"],
        eurio_ids=json.loads(r["eurio_ids_json"]),
        status=r["status"] or "draft",
        frozen_at=r["frozen_at"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_iteration(r: sqlite3.Row) -> ExperimentIterationRow:
    return ExperimentIterationRow(
        id=r["id"],
        cohort_id=r["cohort_id"],
        parent_iteration_id=r["parent_iteration_id"],
        name=r["name"],
        hypothesis=r["hypothesis"],
        recipe_id=r["recipe_id"],
        variant_count=r["variant_count"],
        training_config=json.loads(r["training_config_json"]),
        status=r["status"],
        training_run_id=r["training_run_id"],
        benchmark_run_id=r["benchmark_run_id"],
        verdict=r["verdict"],
        verdict_override=r["verdict_override"],
        delta_vs_parent=json.loads(r["delta_vs_parent_json"]),
        diff_from_parent=json.loads(r["diff_from_parent_json"]),
        notes=r["notes"],
        error=r["error"],
        created_at=r["created_at"],
        started_at=r["started_at"],
        finished_at=r["finished_at"],
    )
