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
