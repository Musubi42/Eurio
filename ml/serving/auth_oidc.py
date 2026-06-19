"""Vérif JWT OIDC (Authentik) — JWKS cache + signature RS256 + claims.

Cf. DESIGN.md §5.1 et C2-HANDOFF-API-RBAC.md. Module **stateless** côté domaine
metier : il vérifie un id_token brut Authentik et renvoie le payload validé.

Le mapping groups Authentik → rôles applicatifs est ici aussi (court, pas la
peine d'un module dédié).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import JWTError

_LOG = logging.getLogger("eurio-api.auth_oidc")

_JWKS_TTL_SEC = 3600       # refresh proactif après 1h
_JWKS_REFRESH_MIN_SEC = 60  # rate-limit refresh sur kid inconnu (1/min max)

_GROUP_TO_ROLE = {
    "eurio-owner": "owner",
    "eurio-admin": "admin",
    "eurio-reviewer": "reviewer",
}


class _JWKSCache:
    """Cache mémoire des JWKS Authentik. Refresh sur kid inconnu (rate-limited)."""

    def __init__(self) -> None:
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0
        self._last_refresh_attempt: float = 0.0

    def get_key(self, kid: str, jwks_url: str) -> dict[str, Any]:
        # Refresh proactif si TTL expiré ou cache vide.
        now = time.time()
        if not self._keys or (now - self._fetched_at) > _JWKS_TTL_SEC:
            self._refresh(jwks_url, now)
        if kid in self._keys:
            return self._keys[kid]
        # kid inconnu → refresh forcé (rate-limited).
        if (now - self._last_refresh_attempt) > _JWKS_REFRESH_MIN_SEC:
            self._refresh(jwks_url, now)
        if kid in self._keys:
            return self._keys[kid]
        raise JWTError(f"unknown kid {kid!r} (not in JWKS after refresh)")

    def _refresh(self, jwks_url: str, now: float) -> None:
        self._last_refresh_attempt = now
        try:
            resp = httpx.get(jwks_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            _LOG.exception("JWKS refresh failed (%s)", jwks_url)
            return
        keys = {k["kid"]: k for k in data.get("keys", []) if "kid" in k}
        if keys:
            self._keys = keys
            self._fetched_at = now
            _LOG.info("JWKS refreshed: %d key(s) [%s]", len(keys), ", ".join(keys))


_JWKS = _JWKSCache()


def verify_oidc_jwt(token: str) -> dict[str, Any]:
    """Vérifie signature RS256 + iss + aud + exp d'un id_token Authentik.

    Lit ``EURIO_OIDC_ISSUER``, ``EURIO_OIDC_JWKS_URL``, ``EURIO_OIDC_CLIENT_ID``
    depuis l'env. Retourne le payload décodé. Lève ``JWTError`` si invalide.
    """
    issuer = os.environ["EURIO_OIDC_ISSUER"]
    jwks_url = os.environ["EURIO_OIDC_JWKS_URL"]
    audience = os.environ["EURIO_OIDC_CLIENT_ID"]
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    if not kid:
        raise JWTError("id_token missing 'kid' header")
    key = _JWKS.get_key(kid, jwks_url)
    payload = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"verify_at_hash": False},  # pas d'access_token associé ici
    )
    return payload


def authentik_groups_to_roles(groups: list[str]) -> list[str]:
    """Filtre ``groups`` Authentik vers les 3 rôles applicatifs (owner/admin/reviewer).

    Les groupes Authentik qui ne sont pas dans ``_GROUP_TO_ROLE`` sont ignorés.
    Ordre déterministe (owner, admin, reviewer) pour des logs stables.
    """
    roles = {_GROUP_TO_ROLE[g] for g in groups if g in _GROUP_TO_ROLE}
    return [r for r in ("owner", "admin", "reviewer") if r in roles]
