"""Routes OIDC eurio-api : login / callback / logout.

Cf. DESIGN.md §5.3 et C2-HANDOFF-API-RBAC.md §3.3. Flow Authorization Code +
PKCE :

1. ``GET /auth/oidc/login`` → génère ``state`` + ``code_verifier``, pose deux
   cookies courts (HttpOnly), redirige vers Authentik ``/authorize`` avec
   ``code_challenge``.
2. ``GET /auth/oidc/callback?code=…&state=…`` → vérifie state, échange code,
   vérifie id_token, upsert user + sync roles, signe cookie de session
   ``eurio_session``, redirige vers ``return_to`` (panel).
3. ``POST /auth/oidc/logout`` → clear cookie + best-effort revoke Authentik.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from .auth_oidc import authentik_groups_to_roles, verify_oidc_jwt
from .auth_principal import (
    cookie_settings,
    sign_session_cookie,
    upsert_user_and_sync_roles,
    write_auth_audit,
)

_LOG = logging.getLogger("eurio-api.auth_routes")

router = APIRouter(prefix="/auth/oidc", tags=["auth"])

_STATE_COOKIE = "eurio_oidc_state"
_VERIFIER_COOKIE = "eurio_oidc_verifier"
_RETURN_TO_COOKIE = "eurio_oidc_return_to"
_OIDC_FLOW_TTL_SEC = 300  # 5 min pour finir login


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


def _flow_cookie_kwargs() -> dict:
    return {
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": "/auth/oidc",  # scoped au flow OIDC uniquement
        "max_age": _OIDC_FLOW_TTL_SEC,
    }


def _pkce_pair() -> tuple[str, str]:
    """Renvoie (verifier, challenge S256). RFC 7636."""
    verifier = secrets.token_urlsafe(64)  # ~86 chars, >43 min
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def _panel_origin() -> str:
    return os.environ.get("EURIO_PANEL_ORIGIN", "https://eurio-admin.musubi.dev")


def _safe_return_to(value: str | None) -> str:
    """Restreint le ``return_to`` au panel pour éviter open redirect."""
    panel = _panel_origin().rstrip("/")
    if not value:
        return panel + "/"
    if value.startswith(panel + "/") or value == panel:
        return value
    return panel + "/"


@router.get("/login")
def login(
    request: Request,
    return_to: str | None = Query(default=None),
) -> Response:
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    safe_return = _safe_return_to(return_to)

    authorize_url = os.environ["EURIO_OIDC_AUTHORIZATION_ENDPOINT"]
    params = {
        "client_id": os.environ["EURIO_OIDC_CLIENT_ID"],
        "response_type": "code",
        "scope": "openid profile email eurio_groups",
        "redirect_uri": os.environ["EURIO_OIDC_REDIRECT_URI"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    target = f"{authorize_url}?{urllib.parse.urlencode(params)}"

    resp = RedirectResponse(url=target, status_code=302)
    resp.set_cookie(_STATE_COOKIE, state, **_flow_cookie_kwargs())
    resp.set_cookie(_VERIFIER_COOKIE, verifier, **_flow_cookie_kwargs())
    resp.set_cookie(_RETURN_TO_COOKIE, safe_return, **_flow_cookie_kwargs())
    return resp


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    eurio_oidc_state: str | None = Cookie(default=None),
    eurio_oidc_verifier: str | None = Cookie(default=None),
    eurio_oidc_return_to: str | None = Cookie(default=None),
) -> Response:
    if error:
        write_auth_audit(_db_path(), actor_id=None, event="login.fail",
                         meta={"error": error, "stage": "authentik"})
        raise HTTPException(status_code=400, detail=f"OIDC error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")
    if not eurio_oidc_state or not eurio_oidc_verifier:
        write_auth_audit(_db_path(), actor_id=None, event="login.fail",
                         meta={"stage": "flow_cookies", "reason": "missing flow cookies"})
        raise HTTPException(status_code=400, detail="flow cookies missing (session expired?)")
    if not secrets.compare_digest(state, eurio_oidc_state):
        write_auth_audit(_db_path(), actor_id=None, event="login.fail",
                         meta={"stage": "state_check", "reason": "mismatch"})
        raise HTTPException(status_code=400, detail="state mismatch (CSRF?)")

    # Exchange code → tokens
    token_url = os.environ["EURIO_OIDC_TOKEN_ENDPOINT"]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": os.environ["EURIO_OIDC_REDIRECT_URI"],
        "client_id": os.environ["EURIO_OIDC_CLIENT_ID"],
        "client_secret": os.environ["EURIO_OIDC_CLIENT_SECRET"],
        "code_verifier": eurio_oidc_verifier,
    }
    try:
        with httpx.Client(timeout=15) as cli:
            r = cli.post(token_url, data=data)
            r.raise_for_status()
            tok = r.json()
    except httpx.HTTPError as e:
        _LOG.exception("token exchange failed")
        write_auth_audit(_db_path(), actor_id=None, event="login.fail",
                         meta={"stage": "token_exchange", "error": str(e)})
        raise HTTPException(status_code=502, detail=f"token exchange failed: {e}") from e

    id_token = tok.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="no id_token in token response")

    try:
        payload = verify_oidc_jwt(id_token)
    except Exception as e:
        _LOG.exception("id_token verify failed")
        write_auth_audit(_db_path(), actor_id=None, event="login.fail",
                         meta={"stage": "id_token_verify", "error": str(e)})
        raise HTTPException(status_code=401, detail=f"id_token invalid: {e}") from e

    sub = payload.get("sub")
    email = payload.get("email", "")
    name = payload.get("name") or payload.get("preferred_username") or email or "?"
    groups = list(payload.get("groups") or [])
    roles = authentik_groups_to_roles(groups)

    if not roles:
        write_auth_audit(_db_path(), actor_id=sub, event="login.fail",
                         meta={"stage": "rbac", "reason": "no eurio role from groups",
                               "groups": groups})
        raise HTTPException(
            status_code=403,
            detail="no Eurio role : ton compte Authentik n'est dans aucun groupe eurio-*"
        )

    principal = upsert_user_and_sync_roles(
        _db_path(), sub=sub, email=email, name=name, roles=roles
    )
    session_jwt, sid = sign_session_cookie(
        user_id=principal.user_id,
        email=principal.email,
        roles=principal.roles,
        scopes=principal.scopes,
    )
    write_auth_audit(_db_path(), actor_id=sub, event="login.ok",
                     target=sid, meta={"roles": roles})

    return_to = _safe_return_to(eurio_oidc_return_to)
    resp = RedirectResponse(url=return_to, status_code=302)
    # Session cookie
    settings = cookie_settings()
    resp.set_cookie(value=session_jwt, **settings)
    # Cleanup flow cookies
    for c in (_STATE_COOKIE, _VERIFIER_COOKIE, _RETURN_TO_COOKIE):
        resp.delete_cookie(c, path="/auth/oidc")
    return resp


@router.post("/logout")
def logout(
    request: Request,
    eurio_session: str | None = Cookie(default=None),
) -> Response:
    # Best-effort audit (le cookie peut être déjà invalide)
    actor = None
    if eurio_session:
        try:
            from .auth_principal import verify_session_cookie
            payload = verify_session_cookie(eurio_session)
            actor = payload.get("sub")
            write_auth_audit(_db_path(), actor_id=actor, event="logout.ok",
                             target=payload.get("sid"))
        except Exception:
            pass

    resp = Response(status_code=204)
    settings = cookie_settings()
    # Pour supprimer un cookie, set max_age=0
    resp.set_cookie(value="", **{**settings, "max_age": 0})
    # Note : on n'appelle pas end_session_endpoint Authentik côté serveur
    # (nécessiterait id_token_hint qu'on n'a pas conservé). Le panel peut
    # déclencher la déconnexion globale côté browser si besoin.
    return resp
