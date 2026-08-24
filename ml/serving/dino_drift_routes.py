"""L'écart de la banque d'ancres DINO, servi à l'accueil admin.

Répond à « est-ce que ça vaut le coup de relancer un rebuild maintenant ? ».
Façade HTTP de ``store.dino_drift`` : ce module ne calcule **rien**, ce qui est
la seule raison pour laquelle l'écran est vérifiable contre la base.

POURQUOI C'EST UNE ROUTE LÉGÈRE
--------------------------------
L'écart est du SQL pur : pas de ``:8042``, pas de torch. Elle est donc montée
sur l'image lean du VPS comme sur la workstation, et la carte de l'accueil
s'affiche même Mac éteint. **Seul le GESTE est lourd** — relancer le rebuild
exige torch et la banque, donc la machine de calcul ; c'est le bouton qui se
grise, jamais le chiffre qui disparaît. Même doctrine que ``/class-need`` :
savoir ce qui manque n'a pas à dépendre d'un Mac allumé.

CE QU'ELLE NE FAIT PAS
----------------------
Elle ne dit pas « tout va bien » quand elle ne sait pas. Une table absente rend
**409**, pas un écart de zéro : un « 0 » et un « je ne peux pas mesurer » se
liraient pareil à l'écran, et c'est exactement la panne muette que ce dépôt
collectionne (cf. ``store/dino_drift.DriftNotMeasurable``).
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from shared.verdict_scope import VERDICT_ANCHORS_KIND, VERDICT_ENCODER_VERSION
from store.dino_drift import DriftNotMeasurable, dino_drift

router = APIRouter(tags=["dino"])

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
ReadDep = Annotated[Principal, Depends(require_scope("lab:read"))]


class DinoDriftOut(BaseModel):
    """L'écart, décomposé — jamais agrégé en un seul score.

    Les quatre compteurs ne se réparent pas de la même façon :
    ``n_predictions_stale`` et ``n_assets_without_prediction`` par un backfill,
    ``n_classes_would_gain_anchor`` par un rebuild, ``n_crops_validated_since``
    par rien du tout (c'est du travail humain accumulé, pas une anomalie). Les
    additionner en une « santé sur 100 » ferait perdre ce qui est actionnable.
    """

    anchors_kind: str
    encoder_version: str
    build_id: str | None
    built_at: str | None
    n_classes: int | None
    n_rows: int | None
    #: Crops tranchés par un humain depuis le build servi — la matière que le
    #: prochain rebuild convertirait en ancres.
    n_crops_validated_since: int
    n_classes_touched_since: int
    #: Classes qui ont une photo validée mais AUCUN exemplaire en banque : elles
    #: n'y vivent que par leur rendu Numista. Le gain par exemplaire y est le
    #: plus fort (courbe références/classe, skill `eurio-banque`).
    n_classes_would_gain_anchor: int
    #: Prédictions calculées AVANT le build servi : elles répondent sur une
    #: banque qui n'existe plus.
    n_predictions_stale: int
    n_assets_without_prediction: int
    #: Vrai s'il y a quelque chose à gagner à relancer. « Jamais bâtie » compte.
    is_stale: bool


@router.get("/dino/drift", response_model=DinoDriftOut)
def get_dino_drift(
    principal: ReadDep,
    conn: ConnDep,
    anchors_kind: str = Query(default=VERDICT_ANCHORS_KIND),
    encoder_version: str = Query(default=VERDICT_ENCODER_VERSION),
) -> DinoDriftOut:
    """L'écart pour un couple (banque, encodeur).

    ⚠️ Le couple est indissociable : ``2eur_all`` n'existe qu'en
    ``dinov2-vitl14``. Un couple inexistant ne lève pas — il rend un écart dont
    ``built_at`` est nul et ``is_stale`` vrai, ce qui est la vérité : cette
    banque-là n'a jamais été bâtie.
    """
    try:
        drift = dino_drift(
            conn, anchors_kind=anchors_kind, encoder_version=encoder_version)
    except DriftNotMeasurable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DinoDriftOut(**drift.as_dict())
