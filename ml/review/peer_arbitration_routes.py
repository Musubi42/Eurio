"""FastAPI router `/peer-arbitration` — arbitrage admin des décisions amis.

Les décisions des amis reviewers sont tirées dans `eurio.db.peer_review_decisions`
(staging) par `go-task ml:review:reconcile`. Cette surface permet à Raphaël de les
arbitrer dans une vue rapide :
  - approve → applique la décision au canonique (même chemin que decide_review,
    mais provenance peer@v1 / actor=peer_admin, confiance peer_review).
  - reject  → laisse le canonique intact, marque la décision rejetée.

cf. docs/work-in-progress/collaborative-review/05-admin-arbitration.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from store import Store, emit_state_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/peer-arbitration", tags=["peer-arbitration"])

_PEER_ENGINE_VERSION = "peer@v1"
_VALID_FACES = ("obverse", "reverse", "unknown")


def _store() -> Store:
    from serving.server import _store as shared_store
    return shared_store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coin_label(conn, eurio_id: str | None) -> str | None:
    if not eurio_id:
        return None
    row = conn.execute(
        "SELECT country_name, year, theme FROM coins WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchone()
    if row is None:
        return eurio_id
    bits = [row["country_name"], str(row["year"]) if row["year"] else None, row["theme"]]
    return " · ".join(b for b in bits if b) or eurio_id


# ─── Liste ───────────────────────────────────────────────────────────────────


@router.get("")
def list_pending(limit: int = 200) -> dict:
    """Décisions en attente d'arbitrage, enrichies pour la vue rapide."""
    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        """
        SELECT pr.*, s.source AS asset_source,
               p.top1_country_eurio_id AS dino_country, p.top1_eurio_id AS dino_global
          FROM peer_review_decisions pr
          LEFT JOIN image_assets a ON a.id = pr.image_asset_id
          LEFT JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = pr.image_asset_id
                AND p.encoder_version = 'dinov2-vits14'
                AND p.anchors_kind = '2eur_commemo'
         WHERE pr.arbitration_status = 'pending'
         ORDER BY pr.decided_at
         LIMIT ?
        """,
        (limit,),
    ).fetchall()

    items = []
    for r in rows:
        dino_top1 = r["dino_country"] or r["dino_global"]
        concords = bool(
            r["action"] == "accept"
            and r["decided_eurio_id"]
            and dino_top1
            and r["decided_eurio_id"] == dino_top1
        )
        crop_url = (
            f"/sources/{r['asset_source']}/assets/{r['image_asset_id']}/file"
            if r["asset_source"] else None
        )
        items.append({
            "id": r["id"],
            "image_asset_id": r["image_asset_id"],
            "crop_url": crop_url,
            "reviewer_name": r["reviewer_name"],
            "reviewer_token": r["reviewer_token"],
            "action": r["action"],
            "decided_eurio_id": r["decided_eurio_id"],
            "decided_label": _coin_label(conn, r["decided_eurio_id"]),
            "decided_face": r["decided_face"],
            "quality_reason": r["quality_reason"],
            "notes": r["notes"],
            "decided_at": r["decided_at"],
            "dino_top1_eurio_id": dino_top1,
            "dino_top1_label": _coin_label(conn, dino_top1),
            "concords": concords,
        })
    return {"items": items}


@router.get("/reviewers")
def reviewer_stats() -> dict:
    """Qualité par reviewer : volume + taux d'approbation (juger les amis)."""
    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        """
        SELECT reviewer_name, reviewer_token,
               count(*) AS total,
               sum(CASE WHEN arbitration_status = 'approved'  THEN 1 ELSE 0 END) AS approved,
               sum(CASE WHEN arbitration_status = 'rejected'  THEN 1 ELSE 0 END) AS rejected,
               sum(CASE WHEN arbitration_status = 'pending'   THEN 1 ELSE 0 END) AS pending
          FROM peer_review_decisions
         GROUP BY reviewer_token
         ORDER BY total DESC
        """,
    ).fetchall()
    return {"reviewers": [dict(r) for r in rows]}


# ─── Arbitrage ───────────────────────────────────────────────────────────────


def _fetch_pending(conn, decision_id: str):
    row = conn.execute(
        "SELECT * FROM peer_review_decisions WHERE id = ?", (decision_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Décision introuvable.")
    if row["arbitration_status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Déjà arbitrée ({row['arbitration_status']}).",
        )
    return row


@router.post("/{decision_id}/approve")
def approve(decision_id: str) -> dict:
    """Applique la décision de l'ami au canonique (provenance peer)."""
    store = _store()
    conn = store._connection()  # noqa: SLF001
    pr = _fetch_pending(conn, decision_id)
    asset_id = pr["image_asset_id"]
    rq_id = pr["review_item_id"]
    now = _now_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        if pr["action"] == "accept":
            face = pr["decided_face"] if pr["decided_face"] in _VALID_FACES else "obverse"
            conn.execute(
                """
                UPDATE image_assets
                   SET eurio_id = ?, face = ?,
                       variant_kind = COALESCE(?, variant_kind),
                       resolution_status = 'manual', resolution_confidence = 1.0,
                       training_eligible = 1, resolved_at = ?
                 WHERE id = ?
                """,
                (pr["decided_eurio_id"], face, pr["decided_variant_kind"], now, asset_id),
            )
            to_state, reason = "resolved", "peer_approved"  # actor=human (arbitrage)
        else:  # reject
            conn.execute(
                """
                UPDATE image_assets
                   SET resolution_status = 'rejected', training_eligible = 0,
                       quality_reason = ?, resolved_at = ?
                 WHERE id = ?
                """,
                (pr["quality_reason"] or "rejected_in_peer_review", now, asset_id),
            )
            to_state, reason = "rejected", "peer_rejected"

        # Fermer la ligne review_queue d'origine si toujours ouverte. Si une
        # voie locale l'a déjà tranchée (rowcount=0) → on ne réécrase pas : on
        # marque la décision peer 'superseded' et on annule le reste.
        rq_closed = True
        if rq_id:
            meta = json.dumps({
                "peer_reviewer": pr["reviewer_token"],
                "peer_decision_id": pr["id"],
            })
            cur = conn.execute(
                """
                UPDATE review_queue
                   SET status = 'done', decided_eurio_id = ?, decided_face = ?,
                       decided_variant_kind = ?, decision_notes = ?, decided_at = ?,
                       decided_by = ?, decision_engine_version = ?,
                       decision_metadata_json = ?
                 WHERE id = ? AND status = 'open'
                """,
                (
                    pr["decided_eurio_id"], pr["decided_face"], pr["decided_variant_kind"],
                    pr["notes"], now, pr["reviewer_token"], _PEER_ENGINE_VERSION,
                    meta, rq_id,
                ),
            )
            rq_closed = cur.rowcount == 1

        if rq_id and not rq_closed:
            conn.execute(
                "UPDATE peer_review_decisions "
                "SET arbitration_status = 'superseded', arbitrated_at = ?, "
                "    arbitration_notes = 'review_queue déjà tranchée localement' "
                "WHERE id = ?",
                (now, decision_id),
            )
            conn.execute("COMMIT")
            return {"status": "superseded", "id": decision_id}

        # actor='human' : l'arbitrage est une action humaine (Raphaël). La
        # provenance pair est tracée ailleurs (review_queue.decided_by=<token>,
        # decision_engine_version='peer@v1', decision_metadata_json) — évite de
        # migrer le CHECK figé de image_state_events.actor.
        emit_state_event(
            conn, asset_id=asset_id, to_state=to_state, actor="human",
            reason=reason, eurio_id=pr["decided_eurio_id"],
        )
        conn.execute(
            "UPDATE peer_review_decisions SET arbitration_status = 'approved', "
            "arbitrated_at = ? WHERE id = ?",
            (now, decision_id),
        )
        conn.execute("COMMIT")
    except HTTPException:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("[peer-arbitration] approved id=%s action=%s eurio_id=%s by=%s",
                decision_id, pr["action"], pr["decided_eurio_id"], pr["reviewer_token"])
    return {"status": "approved", "id": decision_id}


class RejectPayload(BaseModel):
    notes: str | None = None


@router.post("/{decision_id}/reject")
def reject(decision_id: str, payload: RejectPayload | None = None) -> dict:
    """Rejette la décision de l'ami — le canonique reste intact."""
    store = _store()
    conn = store._connection()  # noqa: SLF001
    _fetch_pending(conn, decision_id)
    notes = payload.notes if payload else None
    with store._writing() as wconn:  # noqa: SLF001
        wconn.execute(
            "UPDATE peer_review_decisions "
            "SET arbitration_status = 'rejected', arbitrated_at = ?, arbitration_notes = ? "
            "WHERE id = ? AND arbitration_status = 'pending'",
            (_now_iso(), notes, decision_id),
        )
    return {"status": "rejected", "id": decision_id}
