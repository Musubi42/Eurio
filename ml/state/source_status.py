"""Helper d'écriture pour ``coin_source_status`` (disponibilité par source).

1 row par (eurio_id, source). La sémantique des 4 états (never/ok/
empty_upstream/error) vit dans ``schema.sql`` §coin_source_status. Ce module ne
sait qu'upserter/lire le statut ; le *verdict* (quel état) est décidé par les
appelants (backfill dérivé, refresh réseau, pipelines bulk).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

VALID_STATES = ("never", "ok", "empty_upstream", "error")


def upsert_source_status(
    conn: sqlite3.Connection,
    *,
    eurio_id: str,
    source: str,
    state: str,
    axes: dict[str, Any] | None = None,
    run_id: str | None = None,
    error: str | None = None,
    partial: bool = False,
    checked: bool = True,
) -> None:
    """UPSERT le statut (PK eurio_id, source).

    - ``checked=True`` (refresh/pipeline réseau) pose ``last_checked_at=now``.
    - ``checked=False`` (backfill dérivé localement) le laisse NULL et ne
      l'écrase pas s'il existait déjà (un verdict réseau prime).
    - ``detail_json`` = ``{axes, error, partial}``.
    ``run_id`` / ``last_checked_at`` existants sont préservés via COALESCE quand
    l'appel ne les fournit pas.
    """
    if state not in VALID_STATES:
        raise ValueError(f"invalid state: {state!r}")
    detail = json.dumps({"axes": axes or {}, "error": error, "partial": partial})
    conn.execute(
        """
        INSERT INTO coin_source_status
          (eurio_id, source, state, detail_json, last_run_id, last_checked_at, updated_at)
        VALUES (?, ?, ?, ?, ?,
                CASE WHEN ? THEN datetime('now') ELSE NULL END,
                datetime('now'))
        ON CONFLICT (eurio_id, source) DO UPDATE SET
          state           = excluded.state,
          detail_json     = excluded.detail_json,
          last_run_id     = COALESCE(excluded.last_run_id, coin_source_status.last_run_id),
          last_checked_at = COALESCE(excluded.last_checked_at, coin_source_status.last_checked_at),
          updated_at      = datetime('now')
        """,
        (eurio_id, source, state, detail, run_id, 1 if checked else 0),
    )


def get_network_verdicted_ids(conn: sqlite3.Connection, source: str) -> set[str]:
    """eurio_ids dont le statut pour ``source`` est un verdict réseau
    (``empty_upstream``/``error``) — que le backfill local ne doit pas écraser."""
    rows = conn.execute(
        "SELECT eurio_id FROM coin_source_status "
        "WHERE source = ? AND state IN ('empty_upstream','error')",
        (source,),
    ).fetchall()
    return {r[0] for r in rows}


# ── Dérivation d'axes par coin (source de vérité partagée) ──────────────────
# Utilisée par le refresh (verdict après fetch) ET l'instrumentation des runs
# bulk (upsert ok en continu). Une seule définition pour rester cohérent avec le
# backfill (dont les requêtes GROUP BY couvrent les mêmes axes).


def _exists(conn: sqlite3.Connection, sql: str, eurio_id: str) -> bool:
    return conn.execute(sql, (eurio_id,)).fetchone() is not None


def bce_axes(conn: sqlite3.Connection, eurio_id: str) -> dict:
    axes: dict = {}
    if _exists(conn, "SELECT 1 FROM coin_descriptions_i18n "
                     "WHERE eurio_id=? AND source='bce_official' LIMIT 1", eurio_id):
        axes["description"] = True
    if _exists(conn, "SELECT 1 FROM coin_observations WHERE eurio_id=? "
                     "AND source='bce_official' AND observation_type='mintage_official' LIMIT 1", eurio_id):
        axes["mintage"] = True
    if _exists(conn, "SELECT 1 FROM coin_observations WHERE eurio_id=? "
                     "AND source='bce_official' AND observation_type='issuing_date' LIMIT 1", eurio_id):
        axes["issuing_date"] = True
    if _exists(conn, "SELECT 1 FROM coin_canonical_images "
                     "WHERE eurio_id=? AND source='bce_official' LIMIT 1", eurio_id):
        axes["images"] = True
    return axes


def numista_axes(conn: sqlite3.Connection, eurio_id: str) -> dict:
    axes: dict = {}
    row = conn.execute("SELECT numista_id FROM coins WHERE eurio_id=?", (eurio_id,)).fetchone()
    if row and row[0] is not None:
        axes["identity"] = True
    if _exists(conn, "SELECT 1 FROM coin_mint_releases WHERE parent_type_id=? LIMIT 1", eurio_id):
        axes["mint_releases"] = True
    if _exists(conn, "SELECT 1 FROM coin_names_i18n WHERE eurio_id=? AND source='numista_api' LIMIT 1", eurio_id):
        axes["i18n"] = True
    if _exists(conn, "SELECT 1 FROM coin_observations WHERE eurio_id=? AND source='numista_api' LIMIT 1", eurio_id):
        axes["observations"] = True
    return axes


def jo_axes(conn: sqlite3.Connection, eurio_id: str) -> dict:
    """Axes JO/EUR-Lex : image côté national, date d'émission, fiche (CELEX+URL).

    Le JO ne porte volontairement ni mintage ni description (redondants BCE) —
    cf. memory ``project_eurlex_source``."""
    axes: dict = {}
    if _exists(conn, "SELECT 1 FROM coin_canonical_images "
                     "WHERE eurio_id=? AND source='eurlex_jo' LIMIT 1", eurio_id):
        axes["images"] = True
    if _exists(conn, "SELECT 1 FROM coin_observations WHERE eurio_id=? "
                     "AND source='eurlex_jo' AND observation_type='issuing_date' LIMIT 1", eurio_id):
        axes["issuing_date"] = True
    if _exists(conn, "SELECT 1 FROM coin_source_refs "
                     "WHERE target_kind='coin' AND target_id=? AND source='eurlex_jo' LIMIT 1", eurio_id):
        axes["notice"] = True
    return axes
