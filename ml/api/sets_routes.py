"""FastAPI router pour la feature Sets (P.8a, doctrine SQLite-only).

Endpoints CRUD pour `sets` et `set_members` rapatriés depuis Supabase
(cf. ROADMAP §3 + P.8 audit).

  GET    /sets                       → liste (optionnel filter actif)
  GET    /sets/{id}                  → single
  GET    /sets/{id}/members          → list (avec position + coin metadata)
  POST   /sets                       → create
  PUT    /sets/{id}                  → update
  DELETE /sets/{id}                  → delete
  POST   /sets/{id}/members          → replace members (bulk)
  PATCH  /sets/{id}/active           → toggle active
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from state import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sets", tags=["sets"])


_store: Store | None = None


def bind(store: Store) -> None:
    global _store
    _store = store


def _conn() -> sqlite3.Connection:
    if _store is None:
        raise RuntimeError("sets_routes not bound — call bind() first.")
    return _store._connection()  # noqa: SLF001


# ── Models ────────────────────────────────────────────────────────────────


class SetRow(BaseModel):
    id: str
    name_i18n: dict[str, str]
    description_i18n: dict[str, str] | None = None
    category: str
    kind: str
    param_key: str | None = None
    criteria: dict[str, Any] | None = None
    display_order: int = 0
    expected_count: int | None = None
    icon: str | None = None
    reward: dict[str, Any] | None = None
    active: bool = True


class SetMember(BaseModel):
    eurio_id: str
    position: int | None = None
    # Le frontend (SetEditDrawer) attend aussi le payload coin pour
    # l'affichage de la grille. On joint coins en read-only.
    country: str | None = None
    year: int | None = None
    face_value: float | None = None
    theme: str | None = None
    is_commemorative: bool | None = None


class SetMembersPayload(BaseModel):
    members: list[SetMember]


class SetActivePayload(BaseModel):
    active: bool


# ── Helpers ───────────────────────────────────────────────────────────────


def _loads(s: str | None) -> Any:
    return json.loads(s) if s else None


def _dumps(v: Any | None) -> str | None:
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _row_to_set(row: sqlite3.Row) -> SetRow:
    d = dict(row)
    return SetRow(
        id=d["id"],
        name_i18n=_loads(d["name_i18n"]) or {},
        description_i18n=_loads(d.get("description_i18n")),
        category=d["category"],
        kind=d["kind"],
        param_key=d.get("param_key"),
        criteria=_loads(d.get("criteria")),
        display_order=d.get("display_order", 0),
        expected_count=d.get("expected_count"),
        icon=d.get("icon"),
        reward=_loads(d.get("reward")),
        active=bool(d.get("active", 1)),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("", response_model=list[SetRow])
def list_sets(active_only: bool = Query(default=False)) -> list[SetRow]:
    sql = "SELECT * FROM sets"
    params: tuple = ()
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY display_order, id"
    rows = _conn().execute(sql, params).fetchall()
    return [_row_to_set(r) for r in rows]


@router.get("/{set_id}", response_model=SetRow)
def get_set(set_id: str) -> SetRow:
    row = _conn().execute("SELECT * FROM sets WHERE id = ?", (set_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"set {set_id} not found")
    return _row_to_set(row)


@router.get("/{set_id}/members", response_model=list[SetMember])
def get_set_members(set_id: str) -> list[SetMember]:
    rows = _conn().execute(
        """
        SELECT m.eurio_id, m.position, c.country, c.year, c.face_value,
               c.theme, c.is_commemorative
        FROM set_members m
        LEFT JOIN coins c ON c.eurio_id = m.eurio_id
        WHERE m.set_id = ?
        ORDER BY m.position NULLS LAST, m.eurio_id
        """,
        (set_id,),
    ).fetchall()
    return [
        SetMember(
            eurio_id=r["eurio_id"], position=r["position"],
            country=r["country"], year=r["year"],
            face_value=r["face_value"], theme=r["theme"],
            is_commemorative=bool(r["is_commemorative"]) if r["is_commemorative"] is not None else None,
        )
        for r in rows
    ]


@router.post("", response_model=SetRow, status_code=201)
def create_set(payload: SetRow) -> SetRow:
    conn = _conn()
    exists = conn.execute("SELECT 1 FROM sets WHERE id = ?", (payload.id,)).fetchone()
    if exists:
        raise HTTPException(status_code=409, detail=f"set {payload.id} already exists")
    conn.execute(
        """
        INSERT INTO sets
          (id, name_i18n, description_i18n, category, kind, param_key,
           criteria, display_order, expected_count, icon, reward, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.id, _dumps(payload.name_i18n), _dumps(payload.description_i18n),
            payload.category, payload.kind, payload.param_key,
            _dumps(payload.criteria), payload.display_order,
            payload.expected_count, payload.icon, _dumps(payload.reward),
            1 if payload.active else 0,
        ),
    )
    return get_set(payload.id)


@router.put("/{set_id}", response_model=SetRow)
def update_set(set_id: str, payload: SetRow) -> SetRow:
    conn = _conn()
    if payload.id != set_id:
        raise HTTPException(status_code=400, detail="payload.id mismatch")
    result = conn.execute(
        """
        UPDATE sets SET
          name_i18n = ?, description_i18n = ?, category = ?, kind = ?,
          param_key = ?, criteria = ?, display_order = ?, expected_count = ?,
          icon = ?, reward = ?, active = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            _dumps(payload.name_i18n), _dumps(payload.description_i18n),
            payload.category, payload.kind, payload.param_key,
            _dumps(payload.criteria), payload.display_order,
            payload.expected_count, payload.icon, _dumps(payload.reward),
            1 if payload.active else 0, set_id,
        ),
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"set {set_id} not found")
    return get_set(set_id)


@router.delete("/{set_id}", status_code=204)
def delete_set(set_id: str) -> None:
    conn = _conn()
    result = conn.execute("DELETE FROM sets WHERE id = ?", (set_id,))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"set {set_id} not found")


@router.post("/{set_id}/members", response_model=list[SetMember])
def replace_set_members(set_id: str, payload: SetMembersPayload) -> list[SetMember]:
    """Bulk : remplace tous les membres (DELETE puis INSERT). Pattern le
    plus utilisé côté SetEditDrawer."""
    conn = _conn()
    exists = conn.execute("SELECT 1 FROM sets WHERE id = ?", (set_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail=f"set {set_id} not found")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM set_members WHERE set_id = ?", (set_id,))
        if payload.members:
            conn.executemany(
                "INSERT INTO set_members (set_id, eurio_id, position) VALUES (?, ?, ?)",
                [(set_id, m.eurio_id, m.position) for m in payload.members],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_set_members(set_id)


@router.patch("/{set_id}/active", response_model=SetRow)
def patch_set_active(set_id: str, payload: SetActivePayload) -> SetRow:
    conn = _conn()
    result = conn.execute(
        "UPDATE sets SET active = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if payload.active else 0, set_id),
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"set {set_id} not found")
    return get_set(set_id)
