"""Principal + RBAC scopes + dépendances FastAPI ``require_*``.

Cf. DESIGN.md §3, §5, §6. Le ``Principal`` est l'objet d'auth unifié exposé aux
routes, qu'il vienne d'un cookie de session OIDC (browser) ou d'un PAT (CLI).

Pour C2, le path PAT n'est **pas** encore branché (sera fait en C3). On résoud
uniquement OIDC ici, et on garde le bearer legacy compatible via le module
``auth.py`` existant (sera retiré en C3 quand les PAT prennent le relais).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import Cookie, HTTPException, Request
from jose import jwt
from jose.exceptions import JWTError

_LOG = logging.getLogger("eurio-api.auth_principal")

# Mapping rôle → scopes effectifs (cf. DESIGN.md §3.3).
# `audit:write` réservé aux services serveur (ingest, training) — non listé ici
# (sera attaché aux services via un mécanisme dédié si besoin).
ROLE_SCOPES: dict[str, set[str]] = {
    "owner": {
        "sources:read", "sources:write",
        "coins:read", "coins:write",
        "audit:read",
        "review:read", "review:write",
        "training:run",
        "ingest:run",
        "users:read", "users:manage",
        "tokens:manage_own",
    },
    "admin": {
        "sources:read", "sources:write",
        "coins:read", "coins:write",
        "audit:read",
        "review:read", "review:write",
        "training:run",
        "ingest:run",
        "users:read",
        "tokens:manage_own",
    },
    "reviewer": {
        "coins:read",
        "review:read", "review:write",
        "tokens:manage_own",
    },
}


def roles_to_scopes(roles: list[str]) -> set[str]:
    """Union des scopes des rôles. Rôles inconnus ignorés silencieusement."""
    out: set[str] = set()
    for r in roles:
        out |= ROLE_SCOPES.get(r, set())
    return out


@dataclass
class Principal:
    user_id: str
    email: str
    roles: list[str]
    scopes: set[str] = field(default_factory=set)
    auth_method: Literal["oidc", "api_token"] = "oidc"
    token_id: int | None = None  # populé en C3 quand on branche les PAT
    sid: str | None = None       # uuid du session, audit only


# ─── Cookie de session JWT HS256 ────────────────────────────────────────────


def _session_secret() -> str:
    sec = os.environ.get("EURIO_SESSION_SECRET", "").strip()
    if not sec:
        raise RuntimeError(
            "EURIO_SESSION_SECRET manquant — déploie via direnv ou sops exec-env"
        )
    return sec


SESSION_TTL_SEC = 8 * 3600  # cf. DESIGN.md §6.1


def sign_session_cookie(
    *,
    user_id: str,
    email: str,
    roles: list[str],
    scopes: set[str],
    sid: str | None = None,
) -> tuple[str, str]:
    """Émet un JWT de session signé HS256. Retourne ``(jwt_str, sid)``."""
    sid = sid or str(uuid.uuid4())
    now = int(time.time())
    payload = {
        "iss": "eurio-api",
        "sub": user_id,
        "email": email,
        "roles": roles,
        "scopes": sorted(scopes),
        "sid": sid,
        "iat": now,
        "exp": now + SESSION_TTL_SEC,
    }
    token = jwt.encode(payload, _session_secret(), algorithm="HS256")
    return token, sid


def verify_session_cookie(token: str) -> dict:
    """Vérifie un JWT de session HS256. Lève ``JWTError`` si invalide."""
    return jwt.decode(
        token,
        _session_secret(),
        algorithms=["HS256"],
        issuer="eurio-api",
        options={"verify_aud": False},
    )


def cookie_settings() -> dict:
    """Attrs pour ``Response.set_cookie`` — central pour cohérence partout."""
    return {
        "key": os.environ.get("EURIO_COOKIE_NAME", "eurio_session"),
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": "/",
        "max_age": SESSION_TTL_SEC,
        # Pas de domain : le cookie reste lié à eurio-api.musubi.dev.
        # Le panel (eurio-admin.musubi.dev) appelle eurio-api en CORS avec
        # credentials:'include' — le browser envoie le cookie sur eurio-api.
    }


# ─── Dépendances FastAPI ────────────────────────────────────────────────────


def require_principal(
    request: Request,
    eurio_session: str | None = Cookie(default=None),
) -> Principal:
    """Auth obligatoire — lit le cookie de session, valide, renvoie le Principal.

    Pour C2 : seul le cookie OIDC est supporté. En C3, on ajoute le path PAT
    via ``Authorization: Bearer eurio_…``.
    """
    if not eurio_session:
        # Fallback : header Cookie manuel (cas curl --cookie). FastAPI ne capture
        # pas tous les formats, donc on regarde la string brute.
        raw = request.cookies.get(os.environ.get("EURIO_COOKIE_NAME", "eurio_session"))
        eurio_session = raw or None
    if not eurio_session:
        raise HTTPException(status_code=401, detail="auth required (no session cookie)")
    try:
        payload = verify_session_cookie(eurio_session)
    except JWTError as e:
        _LOG.warning("session cookie invalid: %s", e)
        raise HTTPException(status_code=401, detail=f"session invalid: {e}") from e
    return Principal(
        user_id=payload["sub"],
        email=payload.get("email", ""),
        roles=list(payload.get("roles") or []),
        scopes=set(payload.get("scopes") or []),
        auth_method="oidc",
        sid=payload.get("sid"),
    )


def require_scope(scope: str):
    """Factory de dépendance — 403 si le scope est absent du Principal."""
    def _dep(principal: Principal = None):  # noqa: ANN001 — typed via Depends below
        if scope not in principal.scopes:
            raise HTTPException(
                status_code=403,
                detail=f"missing scope: {scope} (have: {sorted(principal.scopes)})",
            )
        return principal
    # FastAPI besoin de l'annotation : on la branche via Depends côté router
    # (cf. users_routes.py). Le wrapper ci-dessous est juste un closure.
    return _dep


def require_role(role: str):
    """Factory de dépendance — 403 si le rôle est absent du Principal."""
    def _dep(principal: Principal = None):  # noqa: ANN001
        if role not in principal.roles:
            raise HTTPException(
                status_code=403,
                detail=f"missing role: {role} (have: {principal.roles})",
            )
        return principal
    return _dep


# ─── Sync miroir users + user_roles depuis Authentik ────────────────────────


def upsert_user_and_sync_roles(
    db_path: Path | str,
    *,
    sub: str,
    email: str,
    name: str,
    roles: list[str],
) -> Principal:
    """Insère ou met à jour ``users``, puis remplace ``user_roles`` par les rôles
    dérivés des groupes Authentik. Renvoie un ``Principal`` prêt à signer."""
    now_ms = int(time.time() * 1000)
    conn = sqlite3.connect(str(db_path))
    try:
        # Upsert user.
        conn.execute(
            "INSERT INTO users(id, email, name, created_at, last_login_at, active) "
            "VALUES (?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(id) DO UPDATE SET email=excluded.email, name=excluded.name, "
            "last_login_at=excluded.last_login_at",
            (sub, email, name, now_ms, now_ms),
        )
        # Sync roles : delete + insert (idempotent, gère ajouts ET retraits).
        conn.execute("DELETE FROM user_roles WHERE user_id=?", (sub,))
        for r in roles:
            conn.execute(
                "INSERT OR IGNORE INTO user_roles(user_id, role) VALUES (?, ?)",
                (sub, r),
            )
        conn.commit()
    finally:
        conn.close()
    scopes = roles_to_scopes(roles)
    return Principal(
        user_id=sub,
        email=email,
        roles=roles,
        scopes=scopes,
        auth_method="oidc",
    )


def write_auth_audit(
    db_path: Path | str,
    *,
    actor_id: str | None,
    event: str,
    target: str | None = None,
    meta: dict | None = None,
) -> None:
    """Écrit une ligne dans ``auth_audit``. Fire-and-forget côté caller."""
    import json
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO auth_audit(ts, actor_id, event, target, meta_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                int(time.time() * 1000),
                actor_id,
                event,
                target,
                json.dumps(meta or {}, separators=(",", ":")),
            ),
        )
        conn.commit()
    finally:
        conn.close()
