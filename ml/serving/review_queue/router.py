"""Routes HTTP du domaine `review_queue` — thin layer.

Phase 2c-b : list, detail, triage-stats, lots ajoutés.

Cf. ARCHITECTURE.md §2.4.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from shared.dino_scope import DINO_RANKS
from shared.verdict_scope import SUGGESTIONS_ANCHORS_KIND

from . import repository, service
from .models import (
    DinoCandidatesSummary,
    DinoSuggestionsResponse,
    LotDetail,
    LotListResponse,
    RejectedCrop,
    ReviewItem,
    ReviewStats,
    RunProgress,
    TextSignalsResponse,
    TriageStats,
)

router = APIRouter(tags=["review-queue"])

_require_read = require_scope("review:read")

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_read)]


def _split_ids(raw: str | None) -> list[str] | None:
    """`"a,b,,c"` → `["a","b","c"]` ; vide ou absent → `None`."""
    ids = [x for x in (raw or "").split(",") if x]
    return ids or None


@router.get("/review-queue/healthcheck")
def healthcheck(principal: PrincipalDep) -> dict:
    return {"ok": True, "domain": "review_queue", "user": principal.email}


# ─── List / detail ──────────────────────────────────────────────────────────


@router.get("/review-queue", response_model=list[ReviewItem])
def list_queue(
    principal: PrincipalDep,
    conn: ConnDep,
    status: str = Query(default="open"),
    limit: int = Query(default=20, ge=1, le=200),
    order: str = Query(default="priority"),
    kind: str = Query(default="single"),
    lane: str | None = Query(default=None),
    cohort_id: str | None = Query(default=None),
    eurio_id: str | None = Query(default=None),
    review_ids: str | None = Query(default=None),
    dino_min_spread: float | None = Query(default=None, ge=0.0, le=1.0),
    dino_top1_only: bool = Query(default=False),
    dino_class: str | None = Query(default=None),
    dino_rank: int = Query(default=1),
    dino_country_only: bool = Query(default=True),
    dino_era_only: bool = Query(default=True),
    dino_min_denom: float | None = Query(default=None, ge=0.0, le=1.0),
    run_id: str | None = Query(default=None),
    need_only: bool = Query(default=False),
) -> list[ReviewItem]:
    """`run_id` : liste séparée par des virgules de `source_runs.id` — ne
    servir que les crops créés par ces runs. Se combine aux autres filtres.

    `need_only` : ne servir que les crops dont le top-1 DINO tombe dans une
    classe encore en besoin ; les classes pleines sont parquées (D2/D3)."""
    if order not in ("priority", "enqueued_at", "dino"):
        raise HTTPException(
            status_code=422,
            detail="order must be 'priority', 'enqueued_at' or 'dino'",
        )
    if kind not in repository.VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {repository.VALID_KINDS}",
        )
    if lane is not None and lane not in repository.VALID_LANES:
        raise HTTPException(
            status_code=422, detail=f"lane must be one of {repository.VALID_LANES}",
        )
    if dino_rank not in DINO_RANKS:
        raise HTTPException(
            status_code=422, detail=f"dino_rank must be one of {DINO_RANKS}",
        )
    rids = _split_ids(review_ids)
    if review_ids and not rids:
        return []
    try:
        return repository.list_queue(
            conn, status=status, limit=limit, order=order, kind=kind,
            lane=lane, cohort_id=cohort_id, eurio_id=eurio_id, review_ids=rids,
            dino_min_spread=dino_min_spread, dino_top1_only=dino_top1_only,
            dino_class=dino_class, dino_rank=dino_rank,
            dino_country_only=dino_country_only,
            dino_era_only=dino_era_only, dino_min_denom=dino_min_denom,
            run_ids=_split_ids(run_id), need_only=need_only,
        )
    except repository.CohortNotFound:
        raise HTTPException(status_code=404, detail="Cohort introuvable")


@router.get("/review-queue/run-progress", response_model=RunProgress)
def run_progress(
    principal: PrincipalDep,
    conn: ConnDep,
    run_id: str = Query(..., description="source_runs.id, séparés par des virgules"),
    need_only: bool = Query(default=False),
) -> RunProgress:
    """Avancement de la review sur les crops produits par ces runs.

    C'est le compteur « n / N tranchés » du bandeau de review scopé par run.
    Il compte TOUTES les rows review_queue de ces assets, quel que soit leur
    statut — à la différence de `GET /review-queue`, qui ne sert que l'ouvert.

    `need_only` : `open` ne compte que ce que la file sert sous ce filtre, et
    `parked` dit combien de rows ouvertes il écarte (classe pleine / sans
    prédiction).
    """
    ids = _split_ids(run_id)
    if not ids:
        raise HTTPException(status_code=422, detail="run_id requis")
    return repository.run_progress(conn, ids, need_only=need_only)


@router.get("/review-queue/triage-stats", response_model=TriageStats)
def triage_stats(
    principal: PrincipalDep,
    conn: ConnDep,
    kind: str = Query(default="single"),
    cohort_id: str | None = Query(default=None),
) -> TriageStats:
    if kind not in repository.VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {repository.VALID_KINDS}",
        )
    return service.triage_stats(conn, kind=kind, cohort_id=cohort_id)


@router.get("/review-queue/stats", response_model=ReviewStats)
def stats(principal: PrincipalDep, conn: ConnDep) -> ReviewStats:
    return repository.queue_stats(conn)


@router.get("/review-queue/rejected", response_model=list[RejectedCrop])
def rejected(
    principal: PrincipalDep,
    conn: ConnDep,
    cohort_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[RejectedCrop]:
    return repository.list_rejected(conn, cohort_id=cohort_id, limit=limit)


# ─── Pêche & lots (déclarés AVANT /{review_id} pour ne pas être capturés) ──


@router.get(
    "/review-queue/dino-candidates/summary",
    response_model=DinoCandidatesSummary,
)
def dino_candidates_summary(
    principal: PrincipalDep,
    conn: ConnDep,
    dino_class: str = Query(...),
    dino_rank: int = Query(default=1),
    dino_min_spread: float | None = Query(default=None, ge=0.0, le=1.0),
    dino_country_only: bool = Query(default=True),
    dino_era_only: bool = Query(default=True),
    dino_min_denom: float | None = Query(default=None, ge=0.0, le=1.0),
    need_only: bool = Query(default=False),
) -> DinoCandidatesSummary:
    """Ce que la banque propose pour une classe — pour la porte d'entrée Coins.

    Lecture pure : les orphelins sont comptés et leurs ids rendus, mais rien
    n'est enfilé ici (l'enfilage est un POST explicite, cf. la docstring du
    repository).
    """
    if dino_rank not in DINO_RANKS:
        raise HTTPException(
            status_code=422, detail=f"dino_rank must be one of {DINO_RANKS}",
        )
    try:
        return repository.dino_candidates_summary(
            conn, dino_class=dino_class, dino_rank=dino_rank,
            dino_min_spread=dino_min_spread,
            dino_country_only=dino_country_only,
            dino_era_only=dino_era_only, dino_min_denom=dino_min_denom,
            need_only=need_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ─── Lots ─────────────────────────────────────────────────────────────────


@router.get("/review-queue/lots", response_model=LotListResponse)
def list_lots(
    principal: PrincipalDep,
    conn: ConnDep,
    limit: int = Query(default=24, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    cohort_id: str | None = Query(default=None),
    target_eurio_id: str | None = Query(default=None),
    design_group: str | None = Query(default=None),
    dino_class: str | None = Query(default=None),
    dino_rank: int = Query(default=1),
    dino_min_spread: float | None = Query(default=None, ge=0.0, le=1.0),
    dino_country_only: bool = Query(default=True),
    dino_era_only: bool = Query(default=True),
    dino_min_denom: float | None = Query(default=None, ge=0.0, le=1.0),
    run_id: str | None = Query(default=None),
    need_only: bool = Query(default=False),
) -> LotListResponse:
    if dino_rank not in DINO_RANKS:
        raise HTTPException(
            status_code=422, detail=f"dino_rank must be one of {DINO_RANKS}",
        )
    items, total = repository.list_lots(
        conn, limit=limit, offset=offset, cohort_id=cohort_id,
        target_eurio_id=target_eurio_id, design_group=design_group,
        dino_class=dino_class, dino_rank=dino_rank,
        dino_min_spread=dino_min_spread,
        dino_country_only=dino_country_only,
        dino_era_only=dino_era_only, dino_min_denom=dino_min_denom,
        run_ids=_split_ids(run_id), need_only=need_only,
    )
    return LotListResponse(items=items, total=total)


@router.get("/review-queue/lots/{listing_key}", response_model=LotDetail)
def get_lot(
    listing_key: str,
    principal: PrincipalDep,
    conn: ConnDep,
    cohort_id: str | None = Query(default=None),
    target_eurio_id: str | None = Query(default=None),
    design_group: str | None = Query(default=None),
    dino_class: str | None = Query(default=None),
    dino_rank: int = Query(default=1),
    dino_min_spread: float | None = Query(default=None, ge=0.0, le=1.0),
    dino_country_only: bool = Query(default=True),
    dino_era_only: bool = Query(default=True),
    dino_min_denom: float | None = Query(default=None, ge=0.0, le=1.0),
    run_id: str | None = Query(default=None),
    need_only: bool = Query(default=False),
) -> LotDetail:
    """Le lot, et ses voisins DANS LE PÉRIMÈTRE passé en query.

    Les paramètres de périmètre sont facultatifs et purement navigationnels :
    ils ne changent pas le contenu du lot, seulement `prev/next_listing_key`.
    Un appel sans eux déroule la file lot globale — l'ancien comportement.
    """
    if dino_rank not in DINO_RANKS:
        raise HTTPException(
            status_code=422, detail=f"dino_rank must be one of {DINO_RANKS}",
        )
    try:
        return repository.get_lot_detail(
            conn, listing_key,
            cohort_id=cohort_id, target_eurio_id=target_eurio_id,
            design_group=design_group, dino_class=dino_class,
            dino_rank=dino_rank, dino_min_spread=dino_min_spread,
            dino_country_only=dino_country_only,
            dino_era_only=dino_era_only, dino_min_denom=dino_min_denom,
            run_ids=_split_ids(run_id), need_only=need_only,
        )
    except repository.LotNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Listing '{listing_key}' introuvable",
        ) from exc


# ─── Text signals (déclarés AVANT /{review_id}) ────────────────────────────


@router.get(
    "/review-queue/asset/{asset_id}/text-signals",
    response_model=TextSignalsResponse,
)
def text_signals_by_asset(
    asset_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
) -> TextSignalsResponse:
    try:
        sid = repository.source_image_id_for_asset(conn, asset_id)
        return repository.text_signals_by_source_image(conn, sid)
    except repository.ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail=f"asset '{asset_id}' introuvable") from exc
    except repository.TextSignalsNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "No text signals for this source_image. The text_signal step "
                "may not have run yet — try `go-task ml:text-signals:backfill`."
            ),
        ) from exc


@router.get(
    "/review-queue/{review_id}/text-signals",
    response_model=TextSignalsResponse,
)
def text_signals_by_review(
    review_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
) -> TextSignalsResponse:
    try:
        sid = repository.source_image_id_for_review(conn, review_id)
        return repository.text_signals_by_source_image(conn, sid)
    except repository.ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail=f"review '{review_id}' introuvable") from exc
    except repository.TextSignalsNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "No text signals for this source_image. The text_signal step "
                "may not have run yet — try `go-task ml:text-signals:backfill`."
            ),
        ) from exc


# ─── Suggestions DINO — LECTURE PURE (lot 6a) ───────────────────────────────
#
# Jumeau lean de `review/review_queue_routes.py` : MÊME chemin, MÊME contrat,
# mais sans le fallback qui encode le crop à la demande (torch absent du VPS).
# Prédiction absente ⇒ 404, que le panneau front sait afficher — Dino est une
# aide, pas un prérequis pour reviewer.
#
# ⚠️ Doivent être déclarées AVANT `/review-queue/{review_id}`, sinon ce dernier
# avale `asset` comme un id de review et répond un 404 parfaitement crédible.


@router.get(
    "/review-queue/asset/{asset_id}/dino-suggestions",
    response_model=DinoSuggestionsResponse,
)
def dino_suggestions_by_asset(
    asset_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
    anchors_kind: str = Query(default=SUGGESTIONS_ANCHORS_KIND),
) -> DinoSuggestionsResponse:
    try:
        return service.dino_suggestions(conn, asset_id, anchors_kind=anchors_kind)
    except repository.DinoPredictionMissing as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Pas de prédiction Dino pour asset_id={asset_id} "
                f"(anchors_kind={anchors_kind}) : hors scope, ou backfill à faire "
                "(`go-task ml:dino-predictions:backfill`)."
            ),
        ) from exc


@router.get(
    "/review-queue/{review_id}/dino-suggestions",
    response_model=DinoSuggestionsResponse,
)
def dino_suggestions_by_review(
    review_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
    anchors_kind: str = Query(default=SUGGESTIONS_ANCHORS_KIND),
) -> DinoSuggestionsResponse:
    try:
        asset_id = repository.asset_id_for_review(conn, review_id)
        return service.dino_suggestions(conn, asset_id, anchors_kind=anchors_kind)
    except repository.ReviewItemNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"review '{review_id}' introuvable") from exc
    except repository.DinoPredictionMissing as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Pas de prédiction Dino pour review_id={review_id} "
                f"(anchors_kind={anchors_kind}) : hors scope, ou backfill à faire."
            ),
        ) from exc


# ─── Detail by id (DOIT être après les routes spécifiques sinon "stats" =
#     review_id) ─────────────────────────────────────────────────────────────


@router.get("/review-queue/{review_id}", response_model=ReviewItem)
def get_review_item(
    review_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
) -> ReviewItem:
    try:
        return repository.get_review_item(conn, review_id)
    except repository.ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail=f"review '{review_id}' introuvable") from exc
