"""Routes ``/me`` + gestion users (admin-only).

Cf. DESIGN.md §5.3 et C2-HANDOFF-API-RBAC.md §3.4. Pour C2 :

* ``GET /me`` — renvoie le Principal courant (lit le cookie de session).
* ``GET /users`` — liste les users miroir + rôles. Scope ``users:read``.
* ``PUT /users/{id}/roles`` — réassigne les rôles côté miroir. Scope
  ``users:manage``. **Cap'd** par les groupes Authentik réels (à venir : pour
  C2 on ne re-checke pas Authentik, on fait confiance au panel — le sync rôles
  réel se fait au prochain login OIDC).

Les PAT (``/me/tokens`` POST/GET/DELETE) sont **C3**, pas ici.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth_principal import (
    Principal,
    require_principal,
    require_scope,
    write_auth_audit,
)

router = APIRouter(tags=["users"])


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


@router.get("/me")
def me(principal: Principal = Depends(require_principal)) -> dict:
    # Lire le `name` depuis la DB (pas porté dans le JWT pour rester compact).
    conn = sqlite3.connect(str(_db_path()))
    try:
        row = conn.execute(
            "SELECT name FROM users WHERE id = ?", (principal.user_id,)
        ).fetchone()
    finally:
        conn.close()
    return {
        "user_id": principal.user_id,
        "email": principal.email,
        "name": row[0] if row else principal.email,
        "roles": principal.roles,
        "scopes": sorted(principal.scopes),
        "auth_method": principal.auth_method,
    }


# ─── /users ───────────────────────────────────────────────────────────────


@router.get("/users")
def list_users(
    principal: Principal = Depends(require_scope("users:read")),
) -> list[dict]:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT u.id, u.email, u.name, u.created_at, u.last_login_at, u.active, "
            "COALESCE(GROUP_CONCAT(ur.role, ','), '') AS roles "
            "FROM users u LEFT JOIN user_roles ur ON ur.user_id = u.id "
            "GROUP BY u.id ORDER BY u.email"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"],
            "email": r["email"],
            "name": r["name"],
            "created_at": r["created_at"],
            "last_login_at": r["last_login_at"],
            "active": bool(r["active"]),
            "roles": [x for x in (r["roles"] or "").split(",") if x],
        }
        for r in rows
    ]


class RolesPayload(BaseModel):
    roles: list[str]


_VALID_ROLES = {"owner", "admin", "reviewer"}


@router.put("/users/{user_id}/roles")
def set_user_roles(
    user_id: str,
    payload: RolesPayload,
    principal: Principal = Depends(require_scope("users:manage")),
) -> dict:
    requested = [r for r in payload.roles if r in _VALID_ROLES]
    invalid = sorted(set(payload.roles) - _VALID_ROLES)
    if invalid:
        raise HTTPException(status_code=400, detail=f"unknown roles: {invalid}")

    conn = sqlite3.connect(str(_db_path()))
    try:
        # Vérifier que l'utilisateur cible existe.
        row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"user {user_id} not found")
        # Anti-lockout : refuse de retirer le dernier owner.
        if "owner" not in requested:
            other_owners = conn.execute(
                "SELECT COUNT(*) FROM user_roles WHERE role='owner' AND user_id != ?",
                (user_id,),
            ).fetchone()[0]
            currently_owner = conn.execute(
                "SELECT 1 FROM user_roles WHERE role='owner' AND user_id = ?",
                (user_id,),
            ).fetchone()
            if currently_owner and other_owners == 0:
                raise HTTPException(
                    status_code=400,
                    detail="cannot remove last owner — grant another user owner first",
                )
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for r in requested:
            conn.execute(
                "INSERT OR IGNORE INTO user_roles(user_id, role) VALUES (?, ?)",
                (user_id, r),
            )
        conn.commit()
    finally:
        conn.close()

    write_auth_audit(
        _db_path(),
        actor_id=principal.user_id,
        event="role.set",
        target=user_id,
        meta={"roles": requested},
    )
    return {"user_id": user_id, "roles": requested}
