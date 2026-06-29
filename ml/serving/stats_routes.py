"""Routes ``/stats/*`` — compteurs KPI pour le dashboard admin-vps (F9).

Lecture seule depuis SQLite. **Un seul** endpoint ``/stats/overview`` qui
agrège les sections que le principal a le droit de voir (scope vérifié *par
section*) → 1 round-trip au lieu de 6, et pas de 403 par carte côté front.

Déviation assumée vs la note « scope par endpoint » de
``admin-vps-FUTURE-WORK.md`` §F9 : les scopes restent strictement appliqués
(une section absente des scopes n'est pas calculée ni renvoyée), mais
regroupés dans une seule réponse. Justification : le dashboard affiche tout
d'un coup ; N endpoints = N requêtes + N 403 à gérer pour rien.

Chaque section est isolée dans un ``try/except`` : si une table manque sur une
DB donnée, la section est simplement omise (le reste du dashboard répond).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Callable

from fastapi import APIRouter, Depends

from .auth_principal import Principal, require_principal

log = logging.getLogger("eurio-api")

router = APIRouter(prefix="/stats", tags=["stats"])


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


def _safe(name: str, fn: Callable[[], dict]) -> dict | None:
    """Exécute une section ; omet (et log) si la table/colonne manque."""
    try:
        return fn()
    except sqlite3.Error as exc:  # table absente, colonne renommée…
        log.warning("stats: section '%s' échouée → %s", name, exc)
        return None


@router.get("/overview")
def overview(principal: Annotated[Principal, Depends(require_principal)]) -> dict:
    """KPI agrégés, filtrés par les scopes effectifs du principal."""
    out: dict = {}
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        scopes = principal.scopes

        if "coins:read" in scopes:
            out["coins"] = _safe(
                "coins",
                lambda: {
                    "total": _scalar(conn, "SELECT COUNT(*) FROM coins"),
                    "needs_review": _scalar(
                        conn, "SELECT COUNT(*) FROM coins WHERE needs_review = 1"
                    ),
                },
            )
            # Pas de scope `sets:read` dédié → les sets sont rattachés à
            # `coins:read` (lecture éditoriale).
            out["sets"] = _safe(
                "sets",
                lambda: {
                    "total": _scalar(conn, "SELECT COUNT(*) FROM sets"),
                    "active": _scalar(conn, "SELECT COUNT(*) FROM sets WHERE active = 1"),
                },
            )

        if "sources:read" in scopes:
            out["sources"] = _safe(
                "sources",
                lambda: {
                    "total": _scalar(conn, "SELECT COUNT(*) FROM source_registry"),
                    "runs_24h": _scalar(
                        conn,
                        "SELECT COUNT(*) FROM source_runs "
                        "WHERE started_at >= datetime('now', '-1 day')",
                    ),
                    "last_run_at": _scalar(
                        conn, "SELECT MAX(started_at) FROM source_runs"
                    ),
                },
            )

        if "review:read" in scopes:

            def _review() -> dict:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM review_queue GROUP BY status"
                ).fetchall()
                by_status = {r["status"]: r["n"] for r in rows}
                return {"total": sum(by_status.values()), "by_status": by_status}

            out["review"] = _safe("review", _review)

        if "users:read" in scopes:

            def _users() -> dict:
                rows = conn.execute(
                    "SELECT role, COUNT(*) AS n FROM user_roles GROUP BY role"
                ).fetchall()
                return {
                    "total": _scalar(conn, "SELECT COUNT(*) FROM users"),
                    "active": _scalar(conn, "SELECT COUNT(*) FROM users WHERE active = 1"),
                    "by_role": {r["role"]: r["n"] for r in rows},
                }

            out["users"] = _safe("users", _users)

        if "tokens:manage_own" in scopes:
            out["tokens"] = _safe(
                "tokens",
                lambda: {
                    "mine_total": _scalar(
                        conn,
                        "SELECT COUNT(*) FROM pat_tokens WHERE user_id = ?",
                        (principal.user_id,),
                    ),
                    "mine_active": _scalar(
                        conn,
                        "SELECT COUNT(*) FROM pat_tokens "
                        "WHERE user_id = ? AND revoked_at IS NULL",
                        (principal.user_id,),
                    ),
                },
            )
    finally:
        conn.close()

    # Retire les sections omises (None) pour ne pas polluer le front.
    return {k: v for k, v in out.items() if v is not None}
