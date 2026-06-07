"""Reaper boot des jobs orphelins (refacto-ml ADR D1).

Calqué sur `lab_routes.reap_orphan_cohort_jobs`, mais générique sur la table
`jobs`. Appelé par le hook startup de `serving` (`api/server.py`).

Précis (vs un reaper brutal qui tuerait tout `running`) : un job tourne en
subprocess DÉTACHÉ qui survit au `--reload` du worker → on ne clôt QUE les jobs
dont le PID n'existe plus (`os.kill(pid, 0)`), ou qui dépassent `max_runtime_min`
(garde anti-réutilisation de PID). Un job sans PID (subprocess pas encore
enregistré, ou crash avant `job_set_pid`) est traité comme mort.

`max_runtime_min` par défaut large (24 h) : un training peut tourner des heures —
le signal primaire reste la **liveness PID**, pas la durée.
"""

from __future__ import annotations

import os
import sqlite3

DEFAULT_MAX_RUNTIME_MIN = 24 * 60  # 24 h — borne haute anti-réutilisation de PID


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True  # existe mais pas à nous → vivant
    except (ProcessLookupError, OSError, ValueError):
        return False


def reap_orphans(
    conn: sqlite3.Connection,
    *,
    max_runtime_min: float = DEFAULT_MAX_RUNTIME_MIN,
) -> int:
    """Marque `failed` les jobs `running` dont le subprocess est mort. Retourne
    le nombre de jobs récupérés."""
    rows = conn.execute(
        "SELECT id, pid, "
        "  CAST((julianday('now') - julianday(started_at)) * 24 * 60 AS REAL) AS age_min "
        "FROM jobs WHERE status='running'"
    ).fetchall()
    reaped = 0
    for r in rows:
        pid = r["pid"] if isinstance(r, sqlite3.Row) else r[1]
        age_min = (r["age_min"] if isinstance(r, sqlite3.Row) else r[2]) or 0.0
        alive = _pid_alive(pid)
        if alive and age_min < max_runtime_min:
            continue
        reason = (
            "process restart — orphan job (reaped at boot)"
            if not alive
            else f"reaped at boot — running > {max_runtime_min:.0f}min (pid {pid} suspect)"
        )
        job_id = r["id"] if isinstance(r, sqlite3.Row) else r[0]
        conn.execute(
            "UPDATE jobs SET status='failed', "
            "finished_at=COALESCE(finished_at, datetime('now')), "
            "error=COALESCE(error, ?) WHERE id=?",
            (reason, job_id),
        )
        reaped += 1
    return reaped
