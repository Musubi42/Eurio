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
import logging
import sqlite3
import traceback
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Logs de run persistés (BUG-3 : « voir les logs des scraps »). Un FileHandler
# par run capte le logger `sources.*` (pipeline discover→…→price_aggregate)
# pendant toute sa durée → source_runs.log_path pointe le fichier, lisible via
# GET /sources/{src}/runs/{id}/log. Chemin relatif à ml/state (portable).
_RUN_LOGS_DIR = Path(__file__).resolve().parents[2] / "state" / "run_logs"
_RUN_LOG_FORMAT = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s — %(message)s"
)


def _attach_run_log(run_id: str) -> tuple[str, logging.Handler]:
    """Crée un FileHandler scopé au run, branché sur le logger `sources`.
    Retourne ``(log_path_relatif_à_ml/state, handler)``."""
    _RUN_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_RUN_LOGS_DIR / f"{run_id}.log", encoding="utf-8")
    handler.setFormatter(_RUN_LOG_FORMAT)
    handler.setLevel(logging.INFO)
    src_logger = logging.getLogger("sources")
    # Garantit que les records INFO du pipeline atteignent le handler, sans
    # dépendre de la config logging ambiante (en test isolé le défaut = WARNING
    # filtrerait tout). On ne descend pas un éventuel DEBUG déjà posé.
    if src_logger.level == logging.NOTSET or src_logger.level > logging.INFO:
        src_logger.setLevel(logging.INFO)
    src_logger.addHandler(handler)
    return f"run_logs/{run_id}.log", handler


_VALID_KINDS = ("run", "dry", "limit", "reset")
PIPELINE_STEPS: tuple[str, ...] = (
    "discover", "persist", "text_signal", "download", "detect",
    "resolve", "auto_validate", "enqueue", "price_aggregate",
)
_VALID_END_STATUSES = ("success", "failed", "partial")


class RunAlreadyRunning(RuntimeError):
    """Raised when a non-forced run starts while another is still running."""


@dataclass
class RunHandle:
    run_id: str
    source: str
    _conn: sqlite3.Connection

    def set_step(self, step: str) -> None:
        if step not in PIPELINE_STEPS:
            raise ValueError(f"Unknown step '{step}', expected one of {PIPELINE_STEPS}")
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
    def __init__(
        self, handle: RunHandle, log_handler: logging.Handler | None = None
    ) -> None:
        self._handle = handle
        self._log_handler = log_handler

    def __enter__(self) -> RunHandle:
        return self._handle

    def _detach_log(self) -> None:
        if self._log_handler is not None:
            logging.getLogger("sources").removeHandler(self._log_handler)
            self._log_handler.close()
            self._log_handler = None

    def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        try:
            return self._exit_inner(exc_type, exc, tb)
        finally:
            self._detach_log()

    def _exit_inner(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
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
    # Branche le log fichier du run (BUG-3). log_path explicite respecté ;
    # sinon auto `run_logs/<run_id>.log`. Le handler est retiré au __exit__.
    log_handler: logging.Handler | None = None
    if log_path is None:
        try:
            log_path, log_handler = _attach_run_log(run_id)
        except OSError:  # pas de log fichier ne doit jamais bloquer un run
            log_path, log_handler = None, None
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
    return _RunContext(
        RunHandle(run_id=run_id, source=source, _conn=conn), log_handler=log_handler
    )
