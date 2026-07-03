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
    """Verdict d'un crop : classement closed-set (P1) + face (P2).

    ``assigned_sim = max(anchor_sim, consensus_sim)`` — les deux composantes
    sont gardées pour l'audit/calibration (ancre canonique faible vs
    consensus des camarades de classe)."""

    asset_id: str
    assigned_class: str
    assigned_sim: float | None = None
    anchor_sim: float | None = None
    consensus_sim: float | None = None
    top1_class: str | None = None
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    margin: float | None = None
    is_intruder: bool = False
    # 'margin' (une autre classe de la cohorte le réclame) · 'outlier' (ne
    # ressemble pas à ses camarades de classe) · 'margin+outlier' · NULL.
    intruder_reason: str | None = None
    face_verdict: str | None = None
    face_written: bool = False
    # Phase 2 funnel — signaux + suggestion typée pour la worklist « À vérifier ».
    denom_score: float | None = None          # probe 2€-ness (NULL si probe absente)
    denom_verdict: str | None = None          # '2eur' | 'not_2eur' | NULL
    abs_max_sim: float | None = None          # max sim à TOUTE la banque
    suggestion: str | None = None             # 'reject' | 'reassign' | 'exclude' | NULL
    suggestion_reason: str | None = None      # 'denom'|'off_topic'|'reverse'|'margin'|'outlier+quality'


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
        "(scan_id, asset_id, assigned_class, assigned_sim, anchor_sim, "
        " consensus_sim, top1_class, top1_eurio_id, top1_sim, margin, "
        " is_intruder, intruder_reason, face_verdict, face_written, "
        " denom_score, denom_verdict, abs_max_sim, suggestion, suggestion_reason) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (scan_id, r.asset_id, r.assigned_class, r.assigned_sim,
             r.anchor_sim, r.consensus_sim,
             r.top1_class, r.top1_eurio_id, r.top1_sim, r.margin,
             1 if r.is_intruder else 0, r.intruder_reason, r.face_verdict,
             1 if r.face_written else 0,
             r.denom_score, r.denom_verdict, r.abs_max_sim,
             r.suggestion, r.suggestion_reason)
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


def training_scan_dismiss_intruder(
    conn: sqlite3.Connection, asset_id: str, *, cohort_id: str | None = None,
) -> int:
    """Override humain du verdict intrus : marque ``dismissed=1`` la row de cet
    asset. N'écrit PAS ``is_intruder`` → l'audit du scan reste intact ;
    ``training-crops`` filtre sur ``is_intruder AND NOT dismissed``. Un re-scan
    (REPLACE) remet ``dismissed=0`` et ré-évalue à neuf.

    ``cohort_id`` fourni (dismiss « faux positif » depuis le panneau) : cible le
    **dernier scan done de CETTE cohorte** — exactement celui que training-crops
    affiche (``latest_training_scan(cohort_id, done)``). Sans lui (réassignation :
    le crop a changé de classe, verdict périmé partout) : cible le dernier scan
    done qui contient l'asset, toutes cohortes confondues.
    Retourne le nombre de rows touchées (0 si l'asset n'a aucun verdict)."""
    if cohort_id is not None:
        cur = conn.execute(
            """
            UPDATE cohort_training_scan_results SET dismissed=1
             WHERE asset_id=? AND scan_id = (
               SELECT id FROM cohort_training_scans
                WHERE cohort_id=? AND status='done'
                ORDER BY started_at DESC, id DESC
                LIMIT 1
             )
            """,
            (asset_id, cohort_id),
        )
    else:
        cur = conn.execute(
            """
            UPDATE cohort_training_scan_results SET dismissed=1
             WHERE asset_id=? AND scan_id = (
               SELECT r.scan_id
                 FROM cohort_training_scan_results r
                 JOIN cohort_training_scans s ON s.id = r.scan_id
                WHERE r.asset_id=? AND s.status='done'
                ORDER BY s.started_at DESC, s.id DESC
                LIMIT 1
             )
            """,
            (asset_id, asset_id),
        )
    return cur.rowcount


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
