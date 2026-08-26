"""Routes review absorbées dans eurio-api (auth-redesign C4).

Ports les endpoints de ``ml/review_service/routes_*.py`` sous le prefix
``/review/*`` avec la nouvelle auth (``Principal`` + scopes).

Routes :

* ``review:read``  : ``GET /review/me/items``, ``GET /review/me/stats``,
                     ``GET /review/flow``, ``GET /review/decisions``
* ``review:write`` : ``POST /review/claim``, ``POST /review/items/{id}/decide``,
                     ``POST /review/items/{id}/skip``,
                     ``POST /review/publish``, ``POST /review/decisions/ack``

L'identité reviewer = ``Principal.user_id`` (sub Authentik hashé).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth_principal import Principal, require_scope
from .review_db import ReviewDB, now_iso

router = APIRouter(prefix="/review", tags=["review"])

_CLAIM_WINDOW = int(os.environ.get("REVIEW_CLAIM_WINDOW", "10"))
_LEASE_TTL_SECONDS = int(os.environ.get("REVIEW_LEASE_TTL_SECONDS", str(30 * 60)))

# Singleton DB — bootstrap idempotent au boot du process.
_db: ReviewDB | None = None


def _get_db() -> ReviewDB:
    global _db
    if _db is None:
        _db = ReviewDB()
    return _db


_require_review_read = require_scope("review:read")
_require_review_write = require_scope("review:write")


# ─── Helpers ────────────────────────────────────────────────────────────────


def _cutoff_iso() -> str:
    dt = datetime.now(timezone.utc) - timedelta(seconds=_LEASE_TTL_SECONDS)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _crop_url(storage_path: str | None) -> str:
    if not storage_path:
        return ""
    try:
        from shared.storage import bucket_for_key, signed_url
        # Bucket dérivé de la clé (D9) — un crop d'éval reste affichable.
        return signed_url(bucket_for_key(storage_path), storage_path)
    except Exception:  # noqa: BLE001 — pas bloquant en dev
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


def _my_open_items(db: ReviewDB, user_id: str) -> list[dict]:
    rows = db.connection().execute(
        "SELECT * FROM review_items WHERE claimed_by = ? AND status = 'claimed' "
        "ORDER BY priority, published_at",
        (user_id,),
    ).fetchall()
    return [_item_to_dict(r) for r in rows]


# ─── Reviewer endpoints (review:read / review:write) ───────────────────────


@router.get("/me/items")
def my_items(principal: Principal = Depends(_require_review_read)) -> dict:
    return {
        "items": _my_open_items(_get_db(), principal.user_id),
        "window": _CLAIM_WINDOW,
    }


@router.post("/claim")
def claim(principal: Principal = Depends(_require_review_write)) -> dict:
    """Complète le working set du reviewer jusqu'à _CLAIM_WINDOW items."""
    db = _get_db()
    user_id = principal.user_id
    held = db.connection().execute(
        "SELECT count(*) AS n FROM review_items WHERE claimed_by = ? AND status = 'claimed'",
        (user_id,),
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
                (user_id, now_iso(), _cutoff_iso(), need),
            )
    return {"items": _my_open_items(db, user_id), "window": _CLAIM_WINDOW}


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
    principal: Principal = Depends(_require_review_write),
) -> dict:
    db = _get_db()
    user_id = principal.user_id
    if payload.action not in ("accept", "reject"):
        raise HTTPException(status_code=422, detail="action must be accept|reject")
    if payload.action == "accept" and not payload.eurio_id:
        raise HTTPException(status_code=422, detail="accept requires eurio_id")

    with db.writing() as conn:
        cur = conn.execute(
            "UPDATE review_items SET status = 'decided' "
            "WHERE id = ? AND claimed_by = ? AND status = 'claimed'",
            (item_id, user_id),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=409,
                detail="Item plus disponible (claim expiré ou déjà décidé).",
            )
        conn.execute(
            """
            INSERT INTO decisions
              (id, review_item_id, reviewer_user_id, action, decided_eurio_id,
               decided_face, decided_variant_kind, quality_reason, notes, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex, item_id, user_id, payload.action,
                payload.eurio_id, payload.face, payload.variant_kind,
                payload.quality_reason, payload.notes, now_iso(),
            ),
        )
    return {"status": "decided", "id": item_id}


@router.post("/items/{item_id}/skip")
def skip(
    item_id: str,
    principal: Principal = Depends(_require_review_write),
) -> dict:
    db = _get_db()
    with db.writing() as conn:
        conn.execute(
            "UPDATE review_items "
            "SET status = 'open', claimed_by = NULL, claimed_at = NULL, "
            "    priority = priority + 50 "
            "WHERE id = ? AND claimed_by = ?",
            (item_id, principal.user_id),
        )
    return {"status": "skipped", "id": item_id}


@router.get("/me/stats")
def stats(principal: Principal = Depends(_require_review_read)) -> dict:
    db = _get_db()
    user_id = principal.user_id
    total = db.connection().execute(
        "SELECT count(*) AS n FROM decisions WHERE reviewer_user_id = ?",
        (user_id,),
    ).fetchone()["n"]
    today = db.connection().execute(
        "SELECT count(*) AS n FROM decisions "
        "WHERE reviewer_user_id = ? AND substr(decided_at, 1, 10) = substr(?, 1, 10)",
        (user_id, now_iso()),
    ).fetchone()["n"]
    return {"total": total, "today": today, "user_id": user_id}


# ─── Admin endpoints (publish + decisions/ack + flow) ──────────────────────


class PublishItem(BaseModel):
    id: str
    image_asset_id: str
    storage_path: str | None = None
    source: str | None = None
    listing_title: str | None = None
    candidates_json: str | None = None
    target_eurio_id: str | None = None
    dino_top1_json: str | None = None
    priority: int = 100


class PublishPayload(BaseModel):
    items: list[PublishItem]


@router.post("/publish")
def publish(
    payload: PublishPayload,
    principal: Principal = Depends(_require_review_write),
) -> dict:
    """UPSERT idempotent par image_asset_id. Ne réécrase pas un item décidé."""
    db = _get_db()
    published = 0
    skipped = 0
    with db.writing() as conn:
        for it in payload.items:
            existing = conn.execute(
                "SELECT status FROM review_items WHERE image_asset_id = ?",
                (it.image_asset_id,),
            ).fetchone()
            if existing is not None and existing["status"] in ("claimed", "decided"):
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO review_items
                  (id, image_asset_id, storage_path, source, listing_title,
                   candidates_json, target_eurio_id, dino_top1_json, priority,
                   status, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                ON CONFLICT(image_asset_id) DO UPDATE SET
                  id = excluded.id,
                  storage_path = excluded.storage_path,
                  source = excluded.source,
                  listing_title = excluded.listing_title,
                  candidates_json = excluded.candidates_json,
                  target_eurio_id = excluded.target_eurio_id,
                  dino_top1_json = excluded.dino_top1_json,
                  priority = excluded.priority,
                  status = 'open'
                """,
                (
                    it.id, it.image_asset_id, it.storage_path, it.source,
                    it.listing_title, it.candidates_json, it.target_eurio_id,
                    it.dino_top1_json, it.priority, now_iso(),
                ),
            )
            published += 1
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_publish_at', ?)",
            (now_iso(),),
        )
    return {"published": published, "skipped": skipped}


@router.get("/decisions")
def list_decisions(
    unreconciled: int = 1,
    principal: Principal = Depends(_require_review_read),
) -> dict:
    db = _get_db()
    where = "WHERE d.reconciled_at IS NULL" if unreconciled else ""
    rows = db.connection().execute(
        f"""
        SELECT d.*,
               i.image_asset_id AS item_image_asset_id
          FROM decisions d
          JOIN review_items i ON i.id = d.review_item_id
          {where}
         ORDER BY d.decided_at
        """,
    ).fetchall()
    return {"decisions": [dict(r) for r in rows]}


class AckPayload(BaseModel):
    ids: list[str]


@router.post("/decisions/ack")
def ack_decisions(
    payload: AckPayload,
    principal: Principal = Depends(_require_review_write),
) -> dict:
    db = _get_db()
    if not payload.ids:
        return {"acked": 0}
    with db.writing() as conn:
        marks = ",".join("?" * len(payload.ids))
        conn.execute(
            f"UPDATE decisions SET reconciled_at = ? "
            f"WHERE id IN ({marks}) AND reconciled_at IS NULL",
            [now_iso(), *payload.ids],
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_reconcile_at', ?)",
            (now_iso(),),
        )
    return {"acked": len(payload.ids)}


@router.get("/flow")
def flow(principal: Principal = Depends(_require_review_read)) -> dict:
    """Compteurs par status + horodatages last_publish / last_reconcile."""
    db = _get_db()
    counts = {
        r["status"]: r["n"]
        for r in db.connection().execute(
            "SELECT status, count(*) AS n FROM review_items GROUP BY status"
        ).fetchall()
    }
    meta = {
        r["key"]: r["value"]
        for r in db.connection().execute("SELECT key, value FROM meta").fetchall()
    }
    return {
        "counts": {
            "open": counts.get("open", 0),
            "claimed": counts.get("claimed", 0),
            "decided": counts.get("decided", 0),
            "skipped": counts.get("skipped", 0),
        },
        "last_publish_at": meta.get("last_publish_at"),
        "last_reconcile_at": meta.get("last_reconcile_at"),
    }
