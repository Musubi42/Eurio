"""Routes admin du service review : publish (in) + decisions/ack (out).

Protégées par header X-Admin-Token (REVIEW_ADMIN_TOKEN). Appelées par le CLI
ml/review/publish_cli.py depuis le Mac (quand le lease eurio.db est détenu).
cf. 07-reconciliation.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from review_service.auth import require_admin
from review_service.db import ReviewDB, now_iso
from review_service.meta import LAST_PUBLISH_AT, LAST_RECONCILE_AT, set_meta

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _db(request: Request) -> ReviewDB:
    return request.app.state.db


class PublishItem(BaseModel):
    id: str
    image_asset_id: str
    storage_path: str | None = None
    source: str | None = None
    listing_title: str | None = None
    candidates_json: str | None = None     # déjà sérialisé (thumbs absolus résolus)
    target_eurio_id: str | None = None
    dino_top1_json: str | None = None
    priority: int = 100


class PublishPayload(BaseModel):
    items: list[PublishItem]


@router.post("/publish")
def publish(payload: PublishPayload, request: Request) -> dict:
    """UPSERT idempotent par image_asset_id. Ne réécrase pas un item déjà décidé."""
    db: ReviewDB = request.app.state.db
    published = 0
    skipped = 0
    with db.writing() as conn:
        for it in payload.items:
            existing = conn.execute(
                "SELECT status FROM review_items WHERE image_asset_id = ?",
                (it.image_asset_id,),
            ).fetchone()
            if existing is not None and existing["status"] in ("claimed", "decided"):
                skipped += 1  # en cours / déjà fait → ne pas perturber
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
        set_meta(conn, LAST_PUBLISH_AT, now_iso())
    return {"published": published, "skipped": skipped}


@router.get("/decisions")
def list_decisions(request: Request, unreconciled: int = 1) -> dict:
    """Décisions à tirer dans eurio.db, enrichies du nom du reviewer + de l'item."""
    db: ReviewDB = request.app.state.db
    where = "WHERE d.reconciled_at IS NULL" if unreconciled else ""
    rows = db.connection().execute(
        f"""
        SELECT d.*, r.display_name AS reviewer_name,
               i.image_asset_id AS item_image_asset_id
          FROM decisions d
          JOIN reviewers r ON r.token = d.reviewer_token
          JOIN review_items i ON i.id = d.review_item_id
          {where}
         ORDER BY d.decided_at
        """,
    ).fetchall()
    return {"decisions": [dict(r) for r in rows]}


class AckPayload(BaseModel):
    ids: list[str]


@router.post("/decisions/ack")
def ack_decisions(payload: AckPayload, request: Request) -> dict:
    db: ReviewDB = request.app.state.db
    if not payload.ids:
        return {"acked": 0}
    with db.writing() as conn:
        marks = ",".join("?" * len(payload.ids))
        conn.execute(
            f"UPDATE decisions SET reconciled_at = ? "
            f"WHERE id IN ({marks}) AND reconciled_at IS NULL",
            [now_iso(), *payload.ids],
        )
        set_meta(conn, LAST_RECONCILE_AT, now_iso())
    return {"acked": len(payload.ids)}
