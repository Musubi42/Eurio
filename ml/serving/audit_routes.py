"""Routes ``/audit/*`` — log audit (sets, future: coins, sources…).

Lecture seule depuis SQLite. Scope ``audit:read`` (owner + admin).

Cf. ``docs/work-in-progress/data-layer-unification/IMPLEMENTATION.md`` §1.4.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .auth_principal import Principal, require_scope

router = APIRouter(prefix="/audit", tags=["audit"])


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


_require_audit = require_scope("audit:read")


SetAuditAction = Literal[
    "create", "update", "delete", "activate", "deactivate", "publish"
]


class SetAuditEntry(BaseModel):
    id: int
    set_id: str
    action: SetAuditAction
    before: dict | list | None = None
    after: dict | list | None = None
    actor: str
    at: str


@router.get("/sets", response_model=list[SetAuditEntry])
def list_sets_audit(
    principal: Annotated[Principal, Depends(_require_audit)],
    limit: int = Query(default=100, ge=1, le=1000),
    set_id: str | None = Query(default=None),
    actor: str | None = Query(default=None),
) -> list[SetAuditEntry]:
    """Log audit `sets_audit` (append-only). Ordre antéchronologique."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT id, set_id, action, before, after, actor, at FROM sets_audit"
        clauses: list[str] = []
        params: list = []
        if set_id is not None:
            clauses.append("set_id = ?")
            params.append(set_id)
        if actor is not None:
            clauses.append("actor = ?")
            params.append(actor)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    def _parse(raw: str | None) -> dict | list | None:
        if raw is None or raw == "":
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    return [
        SetAuditEntry(
            id=r["id"],
            set_id=r["set_id"],
            action=r["action"],  # type: ignore[arg-type]
            before=_parse(r["before"]),
            after=_parse(r["after"]),
            actor=r["actor"],
            at=r["at"],
        )
        for r in rows
    ]
