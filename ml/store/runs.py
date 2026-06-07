"""Store — domaine runs (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations

import gzip
import json
import sqlite3
from dataclasses import dataclass, field

from .common import ClassRef, _dump_refs, _load_refs, _optional_column


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


class RunsMixin:

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
