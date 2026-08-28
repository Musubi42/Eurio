"""Le jeu d'or du cadrage, servi par le canonique.

Une séance d'annotation ne se refait pas : elle doit atterrir dans `eurio.db`,
pas dans un `.jsonl` local. C'est la leçon de `denom-gold`, dont le verdict
humain vit dans `ml/state/denom_bench/human_validation.jsonl` — invisible du
front hébergé, hors sauvegarde, et perdu au premier `git clean -xdf`.

**Les scopes, et pourquoi ceux-là** :

* écrire → `review:arbitrate`. Ni `review:write` (que porte un ami invité :
  l'or est la RÉFÉRENCE contre laquelle on juge, un ami ne la fixe pas), ni un
  scope neuf `bench:write` — les PAT en circulation portent une liste figée à
  leur création, un scope neuf les ferait tous tomber en 403 jusqu'à réémission ;
* lire → `lab:read`, que portent `owner`, `admin` **et** `reviewer`. La planche
  doit être regardable depuis le front hébergé, donc depuis un téléphone.

Module LEAN : stdlib + `store.*` + FastAPI. Aucun `cv2`, aucun `torch` — un
import lourd au niveau module fait skipper le routeur ENTIER, en silence.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from store.crop_gold import (
    OrGele,
    enregistrer_lot,
    geler,
    instantane,
    lire,
)

logger = logging.getLogger("eurio-api.crop_gold")
router = APIRouter(prefix="/crop-gold", tags=["crop-gold"])


class EllipseIn(BaseModel):
    cx: float
    cy: float
    a: float
    b: float
    theta: float = 0.0


class AnnotationIn(BaseModel):
    asset_id: str
    ellipse: EllipseIn | None = None
    indecidable: bool = False
    passe: int = Field(1, ge=1)
    strate_tiree: str | None = None
    strate_confirmee: str | None = None
    secondes: float | None = None
    prefill_modifie: bool | None = None
    editor_version: str | None = None


class LotIn(BaseModel):
    annotations: list[AnnotationIn]
    requete_sha256: str | None = None


class GelIn(BaseModel):
    snapshot_key: str | None = None


@router.get("/{gold_version}")
def get_or(
    gold_version: str,
    principal: Annotated[Principal, Depends(require_scope("lab:read"))],
    conn=Depends(db_connection),
    passe: int | None = Query(None, ge=1),
) -> dict[str, Any]:
    """L'or d'une version, joint à ce que le banc et la planche doivent savoir."""
    version = conn.execute(
        "SELECT gold_version, created_at, requete_sha256, frozen_at,"
        "       snapshot_sha256, snapshot_key, note"
        "  FROM crop_gold_versions WHERE gold_version = ?",
        (gold_version,)).fetchone()
    lignes = lire(conn, gold_version, passe)
    return {
        "gold_version": gold_version,
        "version": dict(version) if version is not None else None,
        "n": len(lignes),
        "annotations": lignes,
    }


@router.put("/{gold_version}/annotations")
def put_annotations(
    gold_version: str,
    payload: LotIn,
    principal: Annotated[Principal, Depends(require_scope("review:arbitrate"))],
    conn=Depends(db_connection),
) -> dict[str, Any]:
    """Écrit un lot d'annotations. Idempotent par (version, asset, passe).

    Rend le compte PAR STATUT et le détail de ce qui n'est pas passé. Un « ok »
    global masquerait la seule chose qu'on veut savoir.
    """
    try:
        with conn:
            res = enregistrer_lot(
                conn, [a.model_dump() for a in payload.annotations],
                actor=principal.user_id, gold_version=gold_version,
                requete_sha256=payload.requete_sha256)
    except OrGele as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("crop-gold %s : %s", gold_version, res["comptes"])
    return res


@router.post("/{gold_version}/geler")
def post_geler(
    gold_version: str,
    payload: GelIn,
    principal: Annotated[Principal, Depends(require_scope("review:arbitrate"))],
    conn=Depends(db_connection),
) -> dict[str, Any]:
    """Gèle une version : plus une écriture n'entre (RE-5).

    Le `sha256` est calculé ICI sur l'instantané canonique, jamais reçu du
    client : un gel dont le client fournit l'empreinte ne prouve rien.
    """
    contenu = instantane(conn, gold_version)
    sha = hashlib.sha256(contenu.encode()).hexdigest()
    try:
        with conn:
            res = geler(conn, gold_version, snapshot_sha256=sha,
                        snapshot_key=payload.snapshot_key)
    except OrGele as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**res, "snapshot_sha256": sha, "octets": len(contenu)}


@router.get("/{gold_version}/instantane")
def get_instantane(
    gold_version: str,
    principal: Annotated[Principal, Depends(require_scope("lab:read"))],
    conn=Depends(db_connection),
) -> dict[str, Any]:
    """L'instantané canonique et son sha256 — c'est lui qui part dans
    `model-artifacts` (bucket DÉJÀ miroité par la sauvegarde)."""
    contenu = instantane(conn, gold_version)
    return {"gold_version": gold_version,
            "sha256": hashlib.sha256(contenu.encode()).hexdigest(),
            "octets": len(contenu), "contenu": contenu}
