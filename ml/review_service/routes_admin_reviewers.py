"""Routes admin de régie des reviewers (cf. 10-admin-dashboard.md).

Gated par X-Admin-Token (require_admin), comme publish/reconcile. Servent la
page web `/admin` auto-hébergée. La logique métier vit dans
review_service.reviewers ; ces routes ne font que la traduction HTTP + l'URL
d'invitation à partager.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from review_service import reviewers
from review_service.auth import require_admin
from review_service.db import ReviewDB
from review_service.meta import LAST_PUBLISH_AT, LAST_RECONCILE_AT, get_meta

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _public_base_url() -> str:
    """Origine publique du front reviewer, pour bâtir le lien d'invitation."""
    return os.environ.get("REVIEW_PUBLIC_URL", "https://eurio-review.musubi.dev").rstrip("/")


def _invite_url(token: str) -> str:
    return f"{_public_base_url()}/?u={token}"


@router.get("/reviewers")
def list_reviewers(request: Request) -> dict:
    db: ReviewDB = request.app.state.db
    rows = reviewers.list_reviewers(db)
    for r in rows:
        r["invite_url"] = _invite_url(r["token"])
    return {"reviewers": rows}


class CreateReviewerPayload(BaseModel):
    token: str
    name: str


@router.post("/reviewers")
def create_reviewer(payload: CreateReviewerPayload, request: Request) -> dict:
    db: ReviewDB = request.app.state.db
    try:
        created = reviewers.create_reviewer(db, payload.token, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except reviewers.ReviewerExists as exc:
        raise HTTPException(status_code=409, detail="Ce code est déjà pris.") from exc
    return {
        "token": created["token"],
        "name": created["display_name"],
        "invite_url": _invite_url(created["token"]),
    }


@router.delete("/reviewers/{token}")
def revoke_reviewer(token: str, request: Request) -> dict:
    db: ReviewDB = request.app.state.db
    try:
        reviewers.revoke_reviewer(db, token)
    except reviewers.ReviewerNotFound as exc:
        raise HTTPException(status_code=404, detail="Reviewer introuvable.") from exc
    return {"token": token, "is_active": False}


@router.post("/reviewers/{token}/reactivate")
def reactivate_reviewer(token: str, request: Request) -> dict:
    db: ReviewDB = request.app.state.db
    try:
        reviewers.reactivate_reviewer(db, token)
    except reviewers.ReviewerNotFound as exc:
        raise HTTPException(status_code=404, detail="Reviewer introuvable.") from exc
    return {"token": token, "is_active": True}


@router.get("/flow")
def flow(request: Request) -> dict:
    """Vue agrégée du flux pour le bloc en tête de page régie."""
    db: ReviewDB = request.app.state.db
    conn = db.connection()
    pending = conn.execute(
        "SELECT count(*) AS n FROM review_items WHERE status IN ('open', 'claimed')"
    ).fetchone()["n"]
    awaiting_reconcile = conn.execute(
        "SELECT count(*) AS n FROM decisions WHERE reconciled_at IS NULL"
    ).fetchone()["n"]
    return {
        "pending": pending,
        "awaiting_reconcile": awaiting_reconcile,
        "last_publish_at": get_meta(db, LAST_PUBLISH_AT),
        "last_reconcile_at": get_meta(db, LAST_RECONCILE_AT),
    }
