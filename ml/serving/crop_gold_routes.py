"""Le jeu d'or du cadrage, servi par le canonique.

Une séance d'annotation ne se refait pas : elle doit atterrir dans `eurio.db`,
pas dans un `.jsonl` local. C'est la leçon de `denom-gold`, dont le verdict
humain vit dans `ml/state/denom_bench/human_validation.jsonl` — invisible du
front hébergé, hors sauvegarde, et perdu au premier `git clean -xdf`.

Depuis D12, le **tirage** (les images À annoter) vit ici aussi : la séance se
tient depuis le front HÉBERGÉ, donc le canonique doit savoir dire ce qu'il y a
à annoter, pas seulement ce qui a été annoté. Mêmes scopes, à dessein — le
tirage fixe la population mesurée, il est une pièce de la référence.

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
    enregistrer_tirage,
    geler,
    instantane,
    lire,
    lire_tirage,
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


class HintIn(BaseModel):
    """Le cercle de PRODUCTION — ce que le pipeline a cadré, en pixels natifs."""

    cx: float
    cy: float
    r: float


class PrefillIn(BaseModel):
    """L'ellipse proposée par `measure_tilt`, calculée AILLEURS.

    `measure_tilt` tire cv2 ; l'API lean ne l'importe pas et ne le calculera
    jamais. Le pré-remplissage est donc POUSSÉ, pas recalculé — d'où ce modèle
    plutôt qu'une route de calcul.
    """

    cx: float
    cy: float
    a: float
    b: float
    theta_deg: float = 0.0


class TirageImageIn(BaseModel):
    asset_id: str
    role: str = "tirage"
    rn: int | None = None
    strate_tiree: str
    width: int | None = None
    height: int | None = None
    hint: HintIn
    prefill: PrefillIn | None = None
    prefill_reason: str | None = None


class TirageIn(BaseModel):
    images: list[TirageImageIn]
    requete_sha256: str | None = None


def _url_raw(source: str | None, source_image_id: str, storage_path: str | None) -> str:
    """URL servable du raw. Même doctrine que `review_queue/repository._raw_url`.

    Import PARESSEUX de `shared.storage` : il tire boto3, et un import au niveau
    module ferait skipper ce routeur ENTIER dans l'image lean, en silence.

    ⚠️ L'URL est présignée avec `MINIO_PUBLIC_ENDPOINT`, pas avec l'endpoint du
    réseau Docker — sinon l'API répond 200 avec une URL parfaitement formée que
    le navigateur ne résout pas, et seule l'image ne s'affiche pas.
    """
    if storage_path:
        try:
            from shared.storage import signed_url

            return signed_url("enrichment-raws", storage_path)
        except Exception:  # noqa: BLE001 — couche d'affichage, jamais fatale
            pass
    return f"/sources/{source}/raws/{source_image_id}/file"


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
    for ligne in lignes:
        ligne["raw_url"] = _url_raw(ligne.get("source"), ligne.get("source_image_id", ""),
                                    ligne.get("raw_path"))
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


@router.put("/{gold_version}/tirage")
def put_tirage(
    gold_version: str,
    payload: TirageIn,
    principal: Annotated[Principal, Depends(require_scope("review:arbitrate"))],
    conn=Depends(db_connection),
) -> dict[str, Any]:
    """Publie le tirage d'une version — les images À annoter. Idempotent.

    `review:arbitrate` comme les annotations : le tirage EST une pièce de la
    référence (il fixe la population mesurée), un ami invité ne le pose pas.

    Rend `ignorees` plutôt qu'un 404 global : un asset purgé ne doit pas faire
    tomber les 83 autres.
    """
    try:
        with conn:
            res = enregistrer_tirage(
                conn, [i.model_dump() for i in payload.images],
                gold_version=gold_version,
                requete_sha256=payload.requete_sha256)
    except OrGele as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        # Requête d'échantillonnage divergente : ce n'est pas une panne, c'est
        # une réponse. Le front doit pouvoir la lire et la dire.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("crop-gold %s : tirage n=%s ignorees=%s",
                gold_version, res["n"], len(res["ignorees"]))
    return {"ok": True, **res}


@router.get("/{gold_version}/tirage")
def get_tirage(
    gold_version: str,
    principal: Annotated[Principal, Depends(require_scope("lab:read"))],
    conn=Depends(db_connection),
    role: str | None = Query(None, pattern="^(tirage|reserve)$"),
) -> dict[str, Any]:
    """Le tirage à annoter, prêt à afficher — c'est ce que sert la séance (D12).

    Le contrat est FIGÉ : le front est écrit contre lui. `hint` et `prefill`
    sont rendus imbriqués (et `prefill` vaut `null` en bloc quand
    `measure_tilt` n'a rien proposé), pas à plat, pour que le client n'ait pas
    à reconstituer un groupe que la base tient déjà comme un tout.

    ⚠️ **`verdict` n'est PAS servi**, et ce n'est pas un oubli : l'annotateur
    qui verrait le verdict humain le confirmerait au lieu de tracer l'ellipse
    qu'il voit, et RE-4 ne mesurerait plus rien.
    """
    lignes = lire_tirage(conn, gold_version, role)
    images = []
    for l in lignes:
        prefill = None
        if l.get("prefill_cx") is not None:
            prefill = {"cx": l["prefill_cx"], "cy": l["prefill_cy"],
                       "a": l["prefill_a"], "b": l["prefill_b"],
                       "theta_deg": l["prefill_theta_deg"]}
        images.append({
            "asset_id": l["asset_id"],
            "role": l["role"],
            "rn": l["rn"],
            "strate_tiree": l["strate_tiree"],
            "width": l["width"],
            "height": l["height"],
            "hint": {"cx": l["hint_cx"], "cy": l["hint_cy"], "r": l["hint_r"]},
            "prefill": prefill,
            "prefill_reason": l.get("prefill_reason"),
            "source": l.get("source"),
            "source_image_id": l.get("source_image_id"),
            "raw_url": _url_raw(l.get("source"), l.get("source_image_id", ""),
                                l.get("raw_path")),
        })
    return {"gold_version": gold_version, "n": len(images), "images": images}
