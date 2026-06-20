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

from . import repository, service
from .models import (
    LotDetail,
    LotListResponse,
    RejectedCrop,
    ReviewItem,
    ReviewStats,
    TextSignalsResponse,
    TriageStats,
)

router = APIRouter(tags=["review-queue"])

_require_read = require_scope("review:read")

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_read)]


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
) -> list[ReviewItem]:
    if order not in ("priority", "enqueued_at"):
        raise HTTPException(status_code=422, detail="order must be 'priority' or 'enqueued_at'")
    if kind not in repository.VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {repository.VALID_KINDS}",
        )
    if lane is not None and lane not in repository.VALID_LANES:
        raise HTTPException(
            status_code=422, detail=f"lane must be one of {repository.VALID_LANES}",
        )
    rids = [x for x in (review_ids or "").split(",") if x] or None
    if review_ids and not rids:
        return []
    try:
        return repository.list_queue(
            conn, status=status, limit=limit, order=order, kind=kind,
            lane=lane, cohort_id=cohort_id, eurio_id=eurio_id, review_ids=rids,
        )
    except repository.CohortNotFound:
        raise HTTPException(status_code=404, detail="Cohort introuvable")


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


# ─── Lots (déclarés AVANT /{review_id} pour ne pas être capturés) ──────────


@router.get("/review-queue/lots", response_model=LotListResponse)
def list_lots(
    principal: PrincipalDep,
    conn: ConnDep,
    limit: int = Query(default=24, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    cohort_id: str | None = Query(default=None),
    target_eurio_id: str | None = Query(default=None),
    design_group: str | None = Query(default=None),
) -> LotListResponse:
    items, total = repository.list_lots(
        conn, limit=limit, offset=offset, cohort_id=cohort_id,
        target_eurio_id=target_eurio_id, design_group=design_group,
    )
    return LotListResponse(items=items, total=total)


@router.get("/review-queue/lots/{listing_key}", response_model=LotDetail)
def get_lot(
    listing_key: str,
    principal: PrincipalDep,
    conn: ConnDep,
) -> LotDetail:
    try:
        return repository.get_lot_detail(conn, listing_key)
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
