"""Jobs cohorte observables (scrape/recrop) persistés dans cohort_jobs."""

from __future__ import annotations

import sqlite3
import uuid


# ─── Jobs cohorte observables (scrape/recrop) — corrige B2 ────────────────────
# Remplace le dict in-memory _recrop_jobs (perdu au restart). Le worker écrit sa
# progression en base (autocommit) → polling réel + survit aux restarts. Helpers
# applicatifs (pas de trigger) : start → progress* → finish. Cf. schema.sql.

def cohort_job_start(
    conn: sqlite3.Connection,
    *,
    kind: str,
    cohort_id: str,
    eurio_id: str | None = None,
    target_eurio_id: str | None = None,
    run_id: str | None = None,
    n_total: int | None = None,
    tau: float | None = None,
) -> str:
    """Ouvre un job (status='running'). Retourne son id."""
    job_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO cohort_jobs "
        "(id, kind, cohort_id, eurio_id, target_eurio_id, run_id, status, n_total, tau) "
        "VALUES (?,?,?,?,?,?, 'running', ?, ?)",
        (job_id, kind, cohort_id, eurio_id, target_eurio_id, run_id, n_total, tau),
    )
    return job_id


def cohort_job_progress(conn: sqlite3.Connection, job_id: str, *, n_done: int) -> None:
    """Met à jour la progression (au fil de l'eau, autocommit)."""
    conn.execute("UPDATE cohort_jobs SET n_done=? WHERE id=?", (n_done, job_id))


def cohort_job_set_pid(conn: sqlite3.Connection, job_id: str, pid: int) -> None:
    """Enregistre le PID du subprocess détaché qui exécute le job. Lu par le
    reaper boot (`reap_orphan_cohort_jobs`) pour distinguer un job encore vivant
    (subprocess qui a traversé un `--reload`) d'un orphelin réel."""
    conn.execute("UPDATE cohort_jobs SET pid=? WHERE id=?", (pid, job_id))


def cohort_job_finish(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: str,
    n_done: int | None = None,
    n_produced: int | None = None,
    n_attributed_target: int | None = None,
    note: str | None = None,
    error: str | None = None,
) -> None:
    """Clôt un job (status='done'|'failed'|'skipped') + compteurs/diag finals."""
    conn.execute(
        "UPDATE cohort_jobs SET status=?, "
        "n_done=COALESCE(?, n_done), "
        "n_produced=COALESCE(?, n_produced), "
        "n_attributed_target=COALESCE(?, n_attributed_target), "
        "note=COALESCE(?, note), error=COALESCE(?, error), "
        "finished_at=datetime('now') WHERE id=?",
        (status, n_done, n_produced, n_attributed_target, note, error, job_id),
    )
