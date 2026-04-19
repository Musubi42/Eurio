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
            self._connection().executescript(schema)

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
                  epoch_duration_median_sec, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
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

    def stage_classes(self, items: list[ClassRef]) -> None:
        if not items:
            return
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO training_staging (class_id, class_kind)
                VALUES (?, ?)
                ON CONFLICT(class_id) DO UPDATE SET
                  class_kind = excluded.class_kind,
                  staged_at = datetime('now')
                """,
                [(i.class_id, i.class_kind) for i in items],
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
    )
