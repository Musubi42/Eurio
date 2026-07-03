"""Lecture funnel « Jeu d'entraînement » — image lean canonique (VPS).

Miroir LECTURE de ``serving/funnel_writes.py`` (C2a, les écritures funnel).
Sert l'ÉTAT-DB-PORTABLE autoritatif du funnel (crops/classes : statut,
éligibilité, routage) — SQL-pur, servie par ``store.funnel.list_training_crops``
(partagée avec la route full-server ``serving/lab_routes.cohort_training_crops``,
qui l'enrichit avec l'overlay dérivé GPU/FS avant de la renvoyer).

Chemin public identique à la route locale (``/lab/cohorts/{id}/training-crops``)
→ le reroutage front (C3) est un simple swap de base-URL (eurioApi au lieu de
ML_API), pas une réécriture de path.

⚠️ Monté UNIQUEMENT sur `server_serve.py` (lean/VPS). PAS sur `server.py` (full
local) — sinon collision de paths avec `lab_routes` (même raison que
`funnel_writes_router`, cf. server_serve.py).

Scope ``lab:read`` (lecture seule, aucune mutation). Cf.
docs/work-in-progress/local-sync/migration-direction-a.md (C3).
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from serving.lab_read_models import CohortTrainingCropsStateResponse
from store.decisions import DecisionError
from store.funnel import list_training_crops

router = APIRouter(tags=["lab"])

_require_read = require_scope("lab:read")
ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_read)]


@router.get(
    "/lab/cohorts/{cohort_id}/training-crops",
    response_model=CohortTrainingCropsStateResponse,
)
def cohort_training_crops_state(
    cohort_id: str, principal: PrincipalDep, conn: ConnDep,
) -> CohortTrainingCropsStateResponse:
    """État-DB-portable du funnel (read-only). L'overlay dérivé GPU/FS (R@1,
    intrus, refs Numista/BCE) se pose en LOCAL par-dessus, côté front."""
    try:
        result = list_training_crops(conn, cohort_id)
    except DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return CohortTrainingCropsStateResponse(**result)
