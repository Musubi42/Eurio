"""Routes HTTP du domaine `review_queue` — thin layer.

Phase 2c scope : `/stats`, `/rejected`, `/{review_id}/text-signals`,
`/asset/{asset_id}/text-signals`. Les endpoints `list`, `detail`,
`triage-stats`, `lots` sont planifiés pour Phase 2c-bis (DECISIONS.md §D-10).

Cf. ARCHITECTURE.md §2.4.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection

from . import repository
from .models import RejectedCrop, ReviewStats, TextSignalsResponse

router = APIRouter(tags=["review-queue"])

_require_read = require_scope("review:read")

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_read)]


@router.get("/review-queue/healthcheck")
def healthcheck(principal: PrincipalDep) -> dict:
    return {"ok": True, "domain": "review_queue", "user": principal.email}


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


@router.get("/review-queue/asset/{asset_id}/text-signals", response_model=TextSignalsResponse)
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


@router.get("/review-queue/{review_id}/text-signals", response_model=TextSignalsResponse)
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
