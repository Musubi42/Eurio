"""Routes PAT (Personal Access Tokens) — ``/me/tokens`` GET/POST/DELETE.

Cf. DESIGN.md §5.3 et C3-HANDOFF-TOKENS.md. Table cible : ``pat_tokens``
(cf. DESIGN.md §4, déviation `api_tokens` → `pat_tokens` actée en C2 pour
éviter la collision avec la table legacy).

Format du token : ``eurio_<43 base64url>`` (256 bits d'entropie). Le clair
est renvoyé **une seule fois** à la création, jamais re-affichable. Stockage
sha256-only.

Sécurité :
- Tous les endpoints sous le scope ``tokens:manage_own``.
- Un user ne peut **pas** créer/lister/révoquer les tokens d'un autre user
  (filtre WHERE user_id = principal.user_id partout).
- Scopes demandés à la création doivent être ⊆ scopes effectifs de l'user
  au moment de la requête (intersection re-vérifiée à chaque usage du PAT).
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth_principal import (
    PAT_PREFIX,
    Principal,
    hash_pat,
    require_principal,
    roles_to_scopes,
    write_auth_audit,
)

router = APIRouter(prefix="/me/tokens", tags=["tokens"])


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


# ─── Scope guard local (évite l'overhead d'un module séparé) ────────────────


def _require_tokens_manage_own(
    principal: Principal = Depends(require_principal),
) -> Principal:
    if "tokens:manage_own" not in principal.scopes:
        raise HTTPException(
            status_code=403,
            detail="missing scope: tokens:manage_own",
        )
    return principal


# ─── GET /me/tokens ─────────────────────────────────────────────────────────


@router.get("")
def list_tokens(
    principal: Annotated[Principal, Depends(_require_tokens_manage_own)],
) -> list[dict]:
    """Liste les tokens du user courant (jamais le clair)."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, name, scopes_json, created_at, last_used_at, "
            "       revoked_at, expires_at "
            "FROM pat_tokens WHERE user_id = ? ORDER BY created_at DESC",
            (principal.user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "scopes": json.loads(r["scopes_json"] or "[]"),
            "created_at": r["created_at"],
            "last_used_at": r["last_used_at"],
            "revoked_at": r["revoked_at"],
            "expires_at": r["expires_at"],
            "active": r["revoked_at"] is None,
        }
        for r in rows
    ]


# ─── POST /me/tokens ─────────────────────────────────────────────────────────


class CreateTokenPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    scopes: list[str] = Field(default_factory=list)
    expires_at: int | None = Field(
        default=None,
        description="epoch ms ; null = pas d'expiration",
    )


@router.post("")
def create_token(
    payload: CreateTokenPayload,
    principal: Annotated[Principal, Depends(_require_tokens_manage_own)],
) -> dict:
    """Crée un PAT. Retourne le clair UNE FOIS.

    Garde-fous :
    - Vérifie que ``scopes ⊆ scopes effectifs`` du user au moment de la création.
      Si l'user perd un rôle plus tard, le token n'est pas étendu (mais
      ``require_principal`` re-intersecte à chaque requête).
    - Refuse explicitement ``audit:write`` (réservé services serveur, cf.
      DESIGN.md §3.3) : un user ne peut pas se l'auto-attribuer via PAT.
    """
    # Filtre les scopes valides ET inclus dans les scopes effectifs actuels.
    requested = set(payload.scopes)
    if "audit:write" in requested:
        raise HTTPException(
            status_code=400,
            detail="audit:write is reserved for server services, not user PATs",
        )
    extra = requested - principal.scopes
    if extra:
        raise HTTPException(
            status_code=400,
            detail=f"scopes outside your effective set: {sorted(extra)}",
        )

    # Génération : 32 bytes → base64url 43 chars (RFC 4648 sans padding).
    raw = secrets.token_urlsafe(32)  # 43 chars exactement pour 32 bytes
    full = f"{PAT_PREFIX}{raw}"
    sha = hash_pat(full)
    now_ms = int(time.time() * 1000)

    conn = sqlite3.connect(str(_db_path()))
    try:
        cur = conn.execute(
            "INSERT INTO pat_tokens(user_id, name, token_sha, scopes_json, "
            "                       created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                principal.user_id,
                payload.name,
                sha,
                json.dumps(sorted(requested), separators=(",", ":")),
                now_ms,
                payload.expires_at,
            ),
        )
        token_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    write_auth_audit(
        _db_path(),
        actor_id=principal.user_id,
        event="token.create",
        target=str(token_id),
        meta={"name": payload.name, "scopes": sorted(requested)},
    )

    return {
        "id": token_id,
        "name": payload.name,
        "scopes": sorted(requested),
        "expires_at": payload.expires_at,
        "token": full,  # CLAIR — affiché une seule fois.
        "warning": "store this token now — it will never be shown again",
    }


# ─── DELETE /me/tokens/{id} ─────────────────────────────────────────────────


@router.delete("/{token_id}")
def revoke_token(
    token_id: int,
    principal: Annotated[Principal, Depends(_require_tokens_manage_own)],
) -> dict:
    """Soft delete : ``revoked_at = now()``. Audit conservé."""
    now_ms = int(time.time() * 1000)
    conn = sqlite3.connect(str(_db_path()))
    try:
        # Vérifier ownership + état actuel.
        row = conn.execute(
            "SELECT id, revoked_at FROM pat_tokens WHERE id = ? AND user_id = ?",
            (token_id, principal.user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"token {token_id} not found")
        if row[1] is not None:
            return {"id": token_id, "revoked_at": row[1], "already_revoked": True}
        conn.execute(
            "UPDATE pat_tokens SET revoked_at = ? WHERE id = ?",
            (now_ms, token_id),
        )
        conn.commit()
    finally:
        conn.close()

    write_auth_audit(
        _db_path(),
        actor_id=principal.user_id,
        event="token.revoke",
        target=str(token_id),
    )
    return {"id": token_id, "revoked_at": now_ms}
