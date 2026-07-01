"""``GET /whoami`` — identité de l'appelant + **origine machine** du serveur.

Complète ``/me`` (qui exige un principal) : ``/whoami`` ne 401 **jamais** et
expose surtout ``machine`` (mac / pc / vps) — le front s'en sert pour gater les
actions lourdes sur la machine d'origine d'une itération (R3, Model B). Sur le ML
local ``:8042`` (auth souvent off) il renvoie ``machine`` + ``principal: null`` ;
sur le canonique il renvoie en plus le principal si un PAT/cookie est fourni.

Léger (aucun import lourd) → montable sur l'image lean comme sur le full app.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException, Request

from serving import auth as api_auth
from serving.auth_principal import require_principal
from shared.machine import machine_origin

router = APIRouter(tags=["whoami"])


@router.get("/whoami")
def whoami(
    request: Request,
    eurio_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    """Origine machine du serveur + principal appelant (ou ``null`` si non authentifié)."""
    principal_out: dict | None = None
    try:
        p = require_principal(
            request=request,
            eurio_session=eurio_session,
            authorization=authorization,
        )
        principal_out = {
            "user_id": p.user_id,
            "email": p.email,
            "roles": p.roles,
            "scopes": sorted(p.scopes),
            "auth_method": p.auth_method,
        }
    except HTTPException:
        # Pas de principal (auth off en local, ou credentials absents) — on
        # renvoie quand même la machine, c'est l'info clé pour le front.
        principal_out = None

    return {
        "machine": machine_origin(),
        "auth_required": api_auth.auth_required(),
        "principal": principal_out,
    }
