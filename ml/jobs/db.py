"""Accesseurs DB de la table `jobs` générique (refacto-ml ADR D1).

Fonctions pures sur une `sqlite3.Connection` (autocommit, `isolation_level=None`),
calquées sur les `cohort_job_*` de `state/store.py`. Domaine-agnostique : le
payload spécifique au job vit dans la colonne JSON `params`.

NB chunk 5 (split Store) : ce module est destiné à devenir `store/jobs.py`. Il est
volontairement sans dépendance sur `Store` pour que la relocalisation soit triviale.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any


def job_start(
    conn: sqlite3.Connection,
    *,
    kind: str,
    n_total: int | None = None,
    params: dict[str, Any] | None = None,
    log_path: str | None = None,
) -> str:
    """Ouvre un job (status='running'). Retourne son id (uuid hex)."""
    job_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO jobs (id, kind, status, n_total, params, log_path) "
        "VALUES (?,?, 'running', ?, ?, ?)",
        (job_id, kind, n_total, json.dumps(params) if params is not None else None, log_path),
    )
    return job_id


def job_set_pid(conn: sqlite3.Connection, job_id: str, pid: int) -> None:
    """Enregistre le PID du subprocess détaché. Lu par le reaper boot
    (`reap_orphans`) pour distinguer un job vivant (a traversé un `--reload`)
    d'un orphelin réel."""
    conn.execute("UPDATE jobs SET pid=? WHERE id=?", (pid, job_id))


def job_progress(conn: sqlite3.Connection, job_id: str, *, n_done: int) -> None:
    """Met à jour la progression au fil de l'eau (autocommit)."""
    conn.execute("UPDATE jobs SET n_done=? WHERE id=?", (n_done, job_id))


def job_finish(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: str,
    n_done: int | None = None,
    note: str | None = None,
    error: str | None = None,
) -> None:
    """Clôt un job (status='done'|'failed'|'skipped') + diag final."""
    if status not in ("done", "failed", "skipped"):
        raise ValueError(f"statut de clôture invalide: {status!r}")
    conn.execute(
        "UPDATE jobs SET status=?, "
        "n_done=COALESCE(?, n_done), "
        "note=COALESCE(?, note), error=COALESCE(?, error), "
        "finished_at=datetime('now') WHERE id=?",
        (status, n_done, note, error, job_id),
    )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    if d.get("params") is not None:
        try:
            d["params"] = json.loads(d["params"])
        except (json.JSONDecodeError, TypeError):
            pass  # garde la chaîne brute si non-JSON (ne masque pas un bug d'écriture)
    return d


def job_get(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    """Lit un job par id (params désérialisé). None si absent."""
    return _row_to_dict(
        conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    )


def job_latest(conn: sqlite3.Connection, kind: str) -> dict[str, Any] | None:
    """Dernier job d'un `kind` donné. None si aucun."""
    # rowid DESC départage les jobs créés dans la même seconde (datetime('now')
    # est à résolution seconde → started_at seul est ambigu).
    return _row_to_dict(
        conn.execute(
            "SELECT * FROM jobs WHERE kind=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (kind,),
        ).fetchone()
    )


def job_by_param(
    conn: sqlite3.Connection, key: str, value: str, *, kind: str | None = None
) -> dict[str, Any] | None:
    """Dernier job dont `params.<key> == value` (JSON1). Sert à relier un job
    détaché à son entité métier (ex. `run_id`, `iteration_id`).

    `kind` filtre par type : indispensable quand un même `iteration_id` est porté
    par plusieurs kinds (ex. la chaîne `iteration` ET le bake `augmentation`)."""
    sql = "SELECT * FROM jobs WHERE json_extract(params, '$.' || ?) = ?"
    args: list[Any] = [key, value]
    if kind is not None:
        sql += " AND kind = ?"
        args.append(kind)
    sql += " ORDER BY started_at DESC, rowid DESC LIMIT 1"
    return _row_to_dict(conn.execute(sql, args).fetchone())
