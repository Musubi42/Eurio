"""Routes côté ami reviewer (auth, claim fenêtre 10, decide, skip, stats).

cf. 03-claim-queue-ux.md. Le claim atomique (UPDATE…WHERE id IN (SELECT…LIMIT))
garantit que deux reviewers n'obtiennent jamais les mêmes items (équivalent
SQLite de FOR UPDATE SKIP LOCKED), avec récupération des claims abandonnés (TTL).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from review_service.auth import (
    authenticate_token,
    require_reviewer,
    set_session_cookie,
)
from review_service.db import ReviewDB, now_iso

router = APIRouter(tags=["reviewer"])

_CLAIM_WINDOW = int(os.environ.get("REVIEW_CLAIM_WINDOW", "10"))
_LEASE_TTL_SECONDS = int(os.environ.get("REVIEW_LEASE_TTL_SECONDS", str(30 * 60)))


def _db(request: Request) -> ReviewDB:
    return request.app.state.db


def _cutoff_iso() -> str:
    """Borne du visibility timeout : claims plus vieux que TTL → réclamables."""
    from datetime import datetime, timezone

    dt = datetime.now(timezone.utc) - timedelta(seconds=_LEASE_TTL_SECONDS)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _crop_url(storage_path: str | None) -> str:
    if not storage_path:
        return ""
    try:
        from shared.storage import bucket_for_key, signed_url

        # Bucket dérivé de la clé (D9) — un crop d'éval reste affichable.
        return signed_url(bucket_for_key(storage_path), storage_path)
    except Exception:  # noqa: BLE001 — creds MinIO absents en dev pur : pas bloquant
        return ""


def _item_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "image_asset_id": row["image_asset_id"],
        "crop_url": _crop_url(row["storage_path"]),
        "source": row["source"],
        "listing_title": row["listing_title"],
        "candidates": json.loads(row["candidates_json"]) if row["candidates_json"] else [],
        "target_eurio_id": row["target_eurio_id"],
        "dino_top1": json.loads(row["dino_top1_json"]) if row["dino_top1_json"] else None,
    }


# ─── Auth ────────────────────────────────────────────────────────────────────


class AuthPayload(BaseModel):
    token: str


@router.post("/auth")
def auth(payload: AuthPayload, response: Response, db: ReviewDB = Depends(_db)) -> dict:
    reviewer = authenticate_token(db, payload.token.strip())
    if reviewer is None:
        raise HTTPException(status_code=401, detail="Code inconnu.")
    set_session_cookie(response, reviewer["token"])
    return {"name": reviewer["display_name"], "token": reviewer["token"]}


@router.get("/me")
def me(reviewer: dict = Depends(require_reviewer)) -> dict:
    return {"name": reviewer["display_name"], "token": reviewer["token"]}


# ─── Claim & working set ─────────────────────────────────────────────────────


def _my_open_items(db: ReviewDB, token: str) -> list[dict]:
    rows = db.connection().execute(
        """
        SELECT * FROM review_items
         WHERE claimed_by = ? AND status = 'claimed'
         ORDER BY priority, published_at
        """,
        (token,),
    ).fetchall()
    return [_item_to_dict(r) for r in rows]


@router.post("/claim")
def claim(request: Request, reviewer: dict = Depends(require_reviewer)) -> dict:
    """Complète le working set du reviewer jusqu'à _CLAIM_WINDOW items."""
    db: ReviewDB = request.app.state.db
    token = reviewer["token"]
    held = db.connection().execute(
        "SELECT count(*) AS n FROM review_items WHERE claimed_by = ? AND status = 'claimed'",
        (token,),
    ).fetchone()["n"]
    need = max(0, _CLAIM_WINDOW - held)
    if need > 0:
        with db.writing() as conn:
            conn.execute(
                """
                UPDATE review_items
                   SET status = 'claimed', claimed_by = ?, claimed_at = ?
                 WHERE id IN (
                   SELECT id FROM review_items
                    WHERE status = 'open'
                       OR (status = 'claimed'
                           AND (claimed_at IS NULL OR claimed_at < ?))
                    ORDER BY priority, published_at
                    LIMIT ?
                 )
                """,
                (token, now_iso(), _cutoff_iso(), need),
            )
    return {"items": _my_open_items(db, token), "window": _CLAIM_WINDOW}


@router.get("/me/items")
def my_items(request: Request, reviewer: dict = Depends(require_reviewer)) -> dict:
    db: ReviewDB = request.app.state.db
    return {"items": _my_open_items(db, reviewer["token"]), "window": _CLAIM_WINDOW}


# ─── Décision & skip ─────────────────────────────────────────────────────────


class DecidePayload(BaseModel):
    action: str  # accept | reject
    eurio_id: str | None = None
    face: str | None = None
    variant_kind: str | None = None
    quality_reason: str | None = None
    notes: str | None = None


@router.post("/items/{item_id}/decide")
def decide(
    item_id: str,
    payload: DecidePayload,
    request: Request,
    reviewer: dict = Depends(require_reviewer),
) -> dict:
    db: ReviewDB = request.app.state.db
    token = reviewer["token"]
    if payload.action not in ("accept", "reject"):
        raise HTTPException(status_code=422, detail="action must be accept|reject")
    if payload.action == "accept" and not payload.eurio_id:
        raise HTTPException(status_code=422, detail="accept requires eurio_id")

    with db.writing() as conn:
        # Guard de concurrence : l'item doit toujours m'appartenir et être ouvert.
        cur = conn.execute(
            "UPDATE review_items SET status = 'decided' "
            "WHERE id = ? AND claimed_by = ? AND status = 'claimed'",
            (item_id, token),
        )
        if cur.rowcount != 1:
            # Pas de ROLLBACK manuel ici : writing() l'exécute dans son except.
            # (Un double ROLLBACK lèverait OperationalError et masquerait ce 409 en 500.)
            raise HTTPException(
                status_code=409,
                detail="Item plus disponible (claim expiré ou déjà décidé).",
            )
        conn.execute(
            """
            INSERT INTO decisions
              (id, review_item_id, reviewer_token, action, decided_eurio_id,
               decided_face, decided_variant_kind, quality_reason, notes, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex, item_id, token, payload.action,
                payload.eurio_id, payload.face, payload.variant_kind,
                payload.quality_reason, payload.notes, now_iso(),
            ),
        )
    return {"status": "decided", "id": item_id}


@router.post("/items/{item_id}/skip")
def skip(item_id: str, request: Request, reviewer: dict = Depends(require_reviewer)) -> dict:
    """Relâche le claim et fait resombrer l'item (priorité abaissée)."""
    db: ReviewDB = request.app.state.db
    with db.writing() as conn:
        conn.execute(
            "UPDATE review_items "
            "SET status = 'open', claimed_by = NULL, claimed_at = NULL, "
            "    priority = priority + 50 "
            "WHERE id = ? AND claimed_by = ?",
            (item_id, reviewer["token"]),
        )
    return {"status": "skipped", "id": item_id}


@router.get("/me/stats")
def stats(request: Request, reviewer: dict = Depends(require_reviewer)) -> dict:
    db: ReviewDB = request.app.state.db
    token = reviewer["token"]
    total = db.connection().execute(
        "SELECT count(*) AS n FROM decisions WHERE reviewer_token = ?",
        (token,),
    ).fetchone()["n"]
    today = db.connection().execute(
        "SELECT count(*) AS n FROM decisions "
        "WHERE reviewer_token = ? AND substr(decided_at, 1, 10) = substr(?, 1, 10)",
        (token, now_iso()),
    ).fetchone()["n"]
    return {"total": total, "today": today, "name": reviewer["display_name"]}
