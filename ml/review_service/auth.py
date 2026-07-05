"""Auth minimale du service review (cf. 04-auth.md).

Le token est À LA FOIS l'identité et le mot de passe (low-security volontaire).
- Session = cookie HMAC-signé (dépendance-zéro, pas d'itsdangerous).
- Routes amis : dépendance `require_reviewer`.
- Routes admin (publish/reconcile) : header `X-Admin-Token` == REVIEW_ADMIN_TOKEN.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request, Response

from review_service.db import ReviewDB, now_iso

COOKIE_NAME = "er_session"
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 j — confort, pas sécurité forte


def _secret() -> bytes:
    """Clé de signature des cookies de session.

    Fail-hard si REVIEW_SESSION_SECRET est absent : sans ça, le service signerait
    silencieusement tous les cookies avec une constante publique ('dev-insecure-secret'),
    permettant à quiconque connaît cette valeur de forger une session valide pour
    n'importe quel reviewer. En dev local, poser REVIEW_ALLOW_INSECURE_SECRET=1 pour
    accepter explicitement le fallback (jamais en déploiement)."""
    secret = os.environ.get("REVIEW_SESSION_SECRET")
    if secret:
        return secret.encode()
    if os.environ.get("REVIEW_ALLOW_INSECURE_SECRET") == "1":
        return b"dev-insecure-secret"
    raise RuntimeError(
        "REVIEW_SESSION_SECRET absent. Poser le secret (SOPS) au déploiement, "
        "ou REVIEW_ALLOW_INSECURE_SECRET=1 pour un dev local explicite."
    )


def _sign(token: str) -> str:
    sig = hmac.new(_secret(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"


def _unsign(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    token, _, sig = value.rpartition(".")
    expected = hmac.new(_secret(), token.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _sign(token),
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("REVIEW_COOKIE_SECURE", "true").lower() == "true",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def authenticate_token(db: ReviewDB, token: str) -> dict | None:
    """Valide un token contre `reviewers` (actif). Met à jour last_seen_at."""
    row = db.connection().execute(
        "SELECT token, display_name, is_active FROM reviewers WHERE token = ?",
        (token,),
    ).fetchone()
    if row is None or not row["is_active"]:
        return None
    with db.writing() as conn:
        conn.execute(
            "UPDATE reviewers SET last_seen_at = ? WHERE token = ?",
            (now_iso(), token),
        )
    return {"token": row["token"], "display_name": row["display_name"]}


# ─── Dépendances FastAPI ────────────────────────────────────────────────────
# Le module app.py instancie un ReviewDB unique et l'injecte via app.state ;
# ces dépendances le récupèrent depuis la request.


def _db(request: Request) -> ReviewDB:
    return request.app.state.db


def require_reviewer(request: Request, db: ReviewDB = Depends(_db)) -> dict:
    token = _unsign(request.cookies.get(COOKIE_NAME))
    if token is None:
        raise HTTPException(status_code=401, detail="Non authentifié.")
    row = db.connection().execute(
        "SELECT token, display_name, is_active FROM reviewers WHERE token = ?",
        (token,),
    ).fetchone()
    if row is None or not row["is_active"]:
        raise HTTPException(status_code=401, detail="Reviewer inconnu ou désactivé.")
    return {"token": row["token"], "display_name": row["display_name"]}


def require_admin(request: Request) -> None:
    expected = os.environ.get("REVIEW_ADMIN_TOKEN")
    got = request.headers.get("X-Admin-Token")
    if not expected or not got or not hmac.compare_digest(got, expected):
        raise HTTPException(status_code=401, detail="Admin token invalide.")
