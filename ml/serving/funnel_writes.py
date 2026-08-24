"""Écritures de décision funnel + lot — image lean canonique (VPS).

Frère de `serving/review_queue/writes.py` (qui porte decide/reject/skip/restore
single-item). Ici : les décisions du **Jeu d'entraînement** (accept-training,
reopen-review, training-eligible, reassign) + la **décision de lot** — SQL-pures,
servies sur l'image lean du VPS, scope ``review:write``.

Toute la logique SQL vit dans ``store.decisions`` (source UNIQUE partagée avec les
routes lourdes locales `lab_routes`/`review_queue_routes`). Ce module n'est qu'une
FAÇADE HTTP : dep `db_connection`, `conn.commit()` explicite (isolation par
défaut → transaction implicite au 1er DML), traduction `DecisionError→HTTPException`.

**Chemins publics identiques** aux routes locales (`/lab/assets/...`,
`/review-queue/lots/.../decide`) → le reroutage front (C3) est un simple swap de
base-URL, pas une réécriture de path.

⚠️ Monté UNIQUEMENT sur `server_serve.py` (lean/VPS). PAS sur `server.py` (full
local) — sinon collision de paths avec `lab_routes`/`review_queue_routes`. Même
raison que `review_writes_router` (cf. server_serve.py, commentaire du montage).

Idempotence (le write-behind C3 rejouera) : décisions idempotentes par état
terminal — un retry qui trouve la row déjà dans l'état visé no-op (garde
``review_queue … AND status='open'``) et renvoie 200. Cf. migration-direction-a.md §C2a.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from serving.auth_principal import Principal, require_scope
from serving.decision_models import (
    AcceptTrainingResult,
    LotDecidePayload,
    LotDecideResponse,
    ReassignAssetPayload,
    ReopenReviewResult,
    SetTrainingEligiblePayload,
)
from serving.deps import db_connection
from store.decisions import (
    DecisionError,
    apply_accept_training,
    apply_lot_decide,
    apply_reassign,
    apply_reopen_review,
    apply_set_training_eligible,
)

logger = logging.getLogger("eurio-api.funnel_writes")

router = APIRouter(tags=["review-queue"])

#: 🔴 `review:arbitrate`, et non `review:write` — CORRIGÉ LE 2026-08-24, trouvé
#: en revue adversariale.
#:
#: CE QUE C'ÉTAIT
#: --------------
#: Les cinq routes de ce module écrivent le canonique EN DIRECT :
#: `decide_lot` clôt des items et pose `training_eligible = 1`,
#: `/lab/assets/{id}/training-eligible` le pose sur n'importe quel asset. Elles
#: ont été écrites pour l'entonnoir (C2a, Direction A) **avant** la quarantaine
#: du lot 3, et personne n'est repassé dessus quand elle est arrivée : le mot
#: `arbitrate` n'apparaissait pas une fois dans ce fichier.
#:
#: `review:write` est le scope de TOUT ami (D7). D7 était donc contournable, et
#: pas seulement en théorie — le sélecteur « unité / lot » de la pêche, l'écran
#: où un ami travaille, n'était gaté par rien. Vérifié en conditions réelles
#: avec un jeton de reviewer le 2026-08-24 :
#:
#:     POST /review-queue/lots/{lot}/decide      → 200 {"done":1}
#:       review_queue.status        open → done
#:       image_assets.training_eligible 0 → 1
#:       decided_by                 = 'admin'   (la traçabilité ment)
#:       peer_review_decisions      18 → 18     (AUCUNE quarantaine)
#:
#:     POST /lab/assets/{id}/training-eligible   → 200
#:       training_eligible          0 → 1, sans quarantaine
#:
#: POURQUOI FERMER PAR LE SCOPE ET NON METTRE LES LOTS EN QUARANTAINE
#: ------------------------------------------------------------------
#: Tranché avec le PO le 2026-08-24. La quarantaine des lots est la réponse
#: juste sur le fond — le tri par lot est le geste le plus efficace sur une
#: annonce multi-pièces — mais c'est un LOT de travail (N lignes pendantes par
#: décision, l'index unique 0012 à tenir, la vue d'arbitrage à apprendre à
#: grouper). Fermer par le scope se déploie le jour même et se rouvre le jour où
#: on instruit le sujet. Le trou, lui, est ouvert en production maintenant.
#:
#: ⛔ Ne pas remettre `review:write` ici sans avoir posé la quarantaine dans
#: `decide_lot`. Ces routes n'ont pas de jumeau gardé ailleurs : ce `Depends`
#: est la seule chose qui les sépare du canonique.
_require_write = require_scope("review:arbitrate")
ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_write)]


def _commit(conn: sqlite3.Connection, work):
    """Exécute ``work()`` (un apply_* de store.decisions) dans la transaction de
    la requête : commit au succès, rollback + traduction HTTP sur DecisionError,
    rollback + propagation sur toute autre exception."""
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        result = work()
        conn.commit()
        return result
    except DecisionError as exc:
        conn.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except Exception:
        conn.rollback()
        raise


# ── Funnel « Jeu d'entraînement » ────────────────────────────────────────────


@router.post("/lab/assets/{asset_id}/accept-training",
             response_model=AcceptTrainingResult, status_code=200)
def accept_training(
    asset_id: str, principal: PrincipalDep, conn: ConnDep,
) -> AcceptTrainingResult:
    return AcceptTrainingResult(**_commit(conn, lambda: apply_accept_training(conn, asset_id)))


@router.post("/lab/assets/{asset_id}/reopen-review",
             response_model=ReopenReviewResult, status_code=200)
def reopen_review(
    asset_id: str, principal: PrincipalDep, conn: ConnDep,
) -> ReopenReviewResult:
    return ReopenReviewResult(**_commit(conn, lambda: apply_reopen_review(conn, asset_id)))


@router.post("/lab/assets/{asset_id}/training-eligible", status_code=200)
def set_training_eligible(
    asset_id: str, payload: SetTrainingEligiblePayload,
    principal: PrincipalDep, conn: ConnDep,
) -> dict:
    return _commit(conn, lambda: apply_set_training_eligible(conn, asset_id, payload.eligible))


@router.post("/lab/assets/{asset_id}/reassign", status_code=200)
def reassign(
    asset_id: str, payload: ReassignAssetPayload,
    principal: PrincipalDep, conn: ConnDep,
) -> dict:
    return _commit(conn, lambda: apply_reassign(conn, asset_id, payload.eurio_id))


# ── Décision de lot ──────────────────────────────────────────────────────────


@router.post("/review-queue/lots/{listing_key}/decide",
             response_model=LotDecideResponse, status_code=200)
def decide_lot(
    listing_key: str, payload: LotDecidePayload,
    principal: PrincipalDep, conn: ConnDep,
) -> LotDecideResponse:
    return LotDecideResponse(
        **_commit(conn, lambda: apply_lot_decide(conn, listing_key, payload.assignments))
    )
