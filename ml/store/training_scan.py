"""Scan du Jeu d'entraînement (improvement-loop P1+P2) — état persisté.

Mêmes conventions que ``cohort_jobs`` : helpers applicatifs start → progress →
finish sur une table dédiée (``cohort_training_scans``), le subprocess détaché
possède le cycle de vie du scan via sa propre connexion (autocommit). Les
verdicts par crop vivent dans ``cohort_training_scan_results`` (REPLACE au
re-scan). Cf. state/schema.sql §Scan du Jeu d'entraînement.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


@dataclass
class ScanResultRow:
    """Verdict d'un crop : classement closed-set (P1) + face (P2)."""

    asset_id: str
    assigned_class: str
    assigned_sim: float | None = None
    top1_class: str | None = None
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    margin: float | None = None
    is_intruder: bool = False
    face_verdict: str | None = None
    face_written: bool = False


def training_scan_start(
    conn: sqlite3.Connection,
    *,
    cohort_id: str,
    anchors_kind: str,
    encoder_version: str | None,
    intruder_margin: float,
    n_total: int | None = None,
) -> str:
    """Ouvre un scan (status='running'). Retourne son id."""
    scan_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO cohort_training_scans "
        "(id, cohort_id, status, anchors_kind, encoder_version, "
        " intruder_margin, n_total) "
        "VALUES (?,?, 'running', ?,?,?,?)",
        (scan_id, cohort_id, anchors_kind, encoder_version,
         intruder_margin, n_total),
    )
    return scan_id


def training_scan_progress(
    conn: sqlite3.Connection, scan_id: str, *, n_done: int,
) -> None:
    """Met à jour la progression (au fil de l'eau, autocommit)."""
    conn.execute(
        "UPDATE cohort_training_scans SET n_done=? WHERE id=?",
        (n_done, scan_id),
    )


def training_scan_set_pid(
    conn: sqlite3.Connection, scan_id: str, pid: int,
) -> None:
    """PID du subprocess détaché — lu par le reaper boot (orphelins)."""
    conn.execute(
        "UPDATE cohort_training_scans SET pid=? WHERE id=?", (pid, scan_id),
    )


def training_scan_finish(
    conn: sqlite3.Connection,
    scan_id: str,
    *,
    status: str,
    n_done: int | None = None,
    n_intruders: int | None = None,
    n_faces_written: int | None = None,
    n_skipped: int | None = None,
    error: str | None = None,
) -> None:
    """Clôt un scan (status='done'|'failed') + compteurs finals."""
    conn.execute(
        "UPDATE cohort_training_scans SET status=?, "
        "n_done=COALESCE(?, n_done), "
        "n_intruders=COALESCE(?, n_intruders), "
        "n_faces_written=COALESCE(?, n_faces_written), "
        "n_skipped=COALESCE(?, n_skipped), "
        "error=COALESCE(?, error), "
        "finished_at=datetime('now') WHERE id=?",
        (status, n_done, n_intruders, n_faces_written, n_skipped,
         error, scan_id),
    )


def training_scan_upsert_results(
    conn: sqlite3.Connection, scan_id: str, rows: list[ScanResultRow],
) -> None:
    """Persiste un batch de verdicts (REPLACE — idempotent au re-run)."""
    if not rows:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO cohort_training_scan_results "
        "(scan_id, asset_id, assigned_class, assigned_sim, top1_class, "
        " top1_eurio_id, top1_sim, margin, is_intruder, face_verdict, "
        " face_written) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (scan_id, r.asset_id, r.assigned_class, r.assigned_sim,
             r.top1_class, r.top1_eurio_id, r.top1_sim, r.margin,
             1 if r.is_intruder else 0, r.face_verdict,
             1 if r.face_written else 0)
            for r in rows
        ],
    )


def latest_training_scan(
    conn: sqlite3.Connection, cohort_id: str, *, status: str | None = None,
) -> sqlite3.Row | None:
    """Dernier scan de la cohorte (optionnellement filtré par status)."""
    where = "cohort_id=?"
    params: list = [cohort_id]
    if status is not None:
        where += " AND status=?"
        params.append(status)
    return conn.execute(
        f"SELECT * FROM cohort_training_scans WHERE {where} "
        f"ORDER BY started_at DESC, id DESC LIMIT 1",
        params,
    ).fetchone()


def training_scan_results(
    conn: sqlite3.Connection, scan_id: str,
) -> dict[str, sqlite3.Row]:
    """Verdicts du scan, keyés asset_id (pour enrichir training-crops)."""
    return {
        r["asset_id"]: r
        for r in conn.execute(
            "SELECT * FROM cohort_training_scan_results WHERE scan_id=?",
            (scan_id,),
        ).fetchall()
    }
