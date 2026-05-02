"""Lifecycle of a `source_runs` row.

A run is opened with `start_run(...)`, returns a `RunHandle` that the
orchestrator uses to bump counters per step and to record the final
status. The handle is also a context manager so a crashing fetch leaves
the row in `'failed'` (with an `error_summary`) rather than dangling
on `'running'`.

Anti-double-run: opening a run while another one is `'running'` for
the same source raises `RunAlreadyRunning` unless `force=True`.
"""

from __future__ import annotations

import json
import sqlite3
import traceback
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

_VALID_KINDS = ("run", "dry", "limit", "reset")
_VALID_STEPS = ("discover", "persist", "download", "detect", "resolve", "enqueue")
_VALID_END_STATUSES = ("success", "failed", "partial")


class RunAlreadyRunning(RuntimeError):
    """Raised when a non-forced run starts while another is still running."""


@dataclass
class RunHandle:
    run_id: str
    source: str
    _conn: sqlite3.Connection

    def set_step(self, step: str) -> None:
        if step not in _VALID_STEPS:
            raise ValueError(f"Unknown step '{step}', expected one of {_VALID_STEPS}")
        self._conn.execute(
            "UPDATE source_runs SET current_step = ? WHERE id = ?",
            (step, self.run_id),
        )

    def bump(self, **counters: int) -> None:
        """Increment counters on the run row.

        Allowed kwargs: n_calls, n_raws_added, n_crops_added,
        n_quotes_added, n_pending_added, n_auto_resolved,
        n_review_enqueued, n_errors.
        """
        if not counters:
            return
        allowed = {
            "n_calls", "n_raws_added", "n_crops_added", "n_quotes_added",
            "n_pending_added", "n_auto_resolved", "n_review_enqueued", "n_errors",
        }
        unknown = set(counters) - allowed
        if unknown:
            raise ValueError(f"Unknown counter(s): {unknown}")
        sets = ", ".join(f"{k} = {k} + ?" for k in counters)
        self._conn.execute(
            f"UPDATE source_runs SET {sets} WHERE id = ?",
            (*counters.values(), self.run_id),
        )

    def end(self, status: str, error_summary: str | None = None) -> None:
        if status not in _VALID_END_STATUSES:
            raise ValueError(f"Invalid end status '{status}'")
        self._conn.execute(
            """
            UPDATE source_runs
               SET status = ?, ended_at = datetime('now'), error_summary = ?
             WHERE id = ?
            """,
            (status, error_summary, self.run_id),
        )


class _RunContext(AbstractContextManager[RunHandle]):
    def __init__(self, handle: RunHandle) -> None:
        self._handle = handle

    def __enter__(self) -> RunHandle:
        return self._handle

    def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        if exc is None:
            # Caller is expected to call `.end(...)` explicitly with a real status.
            # If they forgot, we mark partial so it doesn't stay 'running'.
            cur = self._handle._conn.execute(
                "SELECT status FROM source_runs WHERE id = ?", (self._handle.run_id,)
            ).fetchone()
            if cur and cur[0] == "running":
                self._handle.end("partial", error_summary="orchestrator returned without calling end()")
            return False
        summary = f"{exc_type.__name__}: {exc}\n{''.join(traceback.format_tb(tb))[:2000]}"
        self._handle.end("failed", error_summary=summary)
        return False  # don't swallow the exception


def start_run(
    conn: sqlite3.Connection,
    *,
    source: str,
    kind: str,
    filters: dict[str, Any] | None = None,
    log_path: str | None = None,
    force: bool = False,
) -> _RunContext:
    """Open a `source_runs` row and return a context-manager handle.

    Usage:

        with start_run(conn, source='ebay', kind='run', filters={...}) as run:
            run.set_step('discover')
            run.bump(n_calls=1)
            ...
            run.end('success')
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"Invalid kind '{kind}'")

    if not force:
        existing = conn.execute(
            "SELECT id FROM source_runs WHERE source = ? AND status = 'running' LIMIT 1",
            (source,),
        ).fetchone()
        if existing:
            raise RunAlreadyRunning(
                f"A run for source '{source}' is already running (id={existing[0]}). "
                "Pass force=True to override."
            )

    run_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO source_runs (id, source, kind, started_at, status, filters_json, log_path)
        VALUES (?, ?, ?, datetime('now'), 'running', ?, ?)
        """,
        (
            run_id,
            source,
            kind,
            json.dumps(filters or {}, ensure_ascii=False),
            log_path,
        ),
    )
    return _RunContext(RunHandle(run_id=run_id, source=source, _conn=conn))
