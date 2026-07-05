"""Écritures review_queue — sous-ensemble LEAN sans cv2 (Model B, TC2).

Porte les décisions humaines de review (decide / reject / skip / restore) sur le
serveur canonique `eurio-api` (lean). Ces handlers sont **SQL pur** : ils ne
touchent ni cv2/PIL ni torch — contrairement à `review.review_queue_routes` (le
module workstation lourd, skippé sur l'image lean à cause d'un `import cv2`
top-level). Les opérations de CROP (manual-crop / auto-crop) RESTENT sur l'API ML
locale (cv2 requis) et ne sont pas portées ici.

Atomicité « premier-écrit-gagne » conservée : l'UPDATE final de `review_queue`
porte `AND status='open'` → rowcount≠1 ⇒ rollback + 409 (une autre voie a tranché).

Connexion : dépendance `db_connection` (conn fraîche par requête, isolation par
défaut, fermée en finally SANS commit) → on `commit()`/`rollback()` explicitement,
PAS de `BEGIN` (l'isolation par défaut auto-ouvre la transaction au 1er DML).
`emit_state_event` ne fait ni BEGIN ni COMMIT (appelé dans la transaction du caller).

Cf. docs/work-in-progress/model-b/ (TC2) + review/review_queue_routes.py (source).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from store import emit_state_event

logger = logging.getLogger("eurio-api.review_writes")

router = APIRouter(tags=["review-queue"])

_require_write = require_scope("review:write")

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_write)]

_HUMAN_ENGINE_VERSION = "human@v1"
_VALID_FACES = ("obverse", "reverse", "unknown")
_VALID_TRASH_REASONS = ("not_a_coin", "too_low_quality")
_SKIP_PRIORITY_BUMP = 50
_RESTORE_PRIORITY = 5
_RESTORED_NOTE = "restored"


def _now_iso() -> str:
    """Timestamp UTC ISO-8601 avec suffixe Z (tri lexicographique cohérent)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class DecidePayload(BaseModel):
    eurio_id: str = Field(min_length=1)
    face: str
    variant_kind: str | None = None
    notes: str | None = None


class RejectPayload(BaseModel):
    # Optionnel : body absent → reject générique. Présent → trash qualité tracé.
    reason: str | None = None


class RestorePayload(BaseModel):
    review_ids: list[str] = Field(default_factory=list)


class RestoreResult(BaseModel):
    restored: int
    skipped: list[str]  # ids non restaurés (introuvables ou pas rejetés)


@router.post("/review-queue/{review_id}/decide", status_code=200)
def decide_review(
    review_id: str, payload: DecidePayload, principal: PrincipalDep, conn: ConnDep,
) -> dict[str, str]:
    if payload.face not in _VALID_FACES:
        raise HTTPException(status_code=422, detail=f"face must be one of {_VALID_FACES}")

    conn.execute("PRAGMA busy_timeout=5000")
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot decide twice.",
        )

    now_iso = _now_iso()
    asset_id = rq["image_asset_id"]
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET eurio_id = ?, face = ?,
                   variant_kind = COALESCE(?, variant_kind),
                   resolution_status = 'manual', resolution_confidence = 1.0,
                   training_eligible = 1, resolved_at = ?
             WHERE id = ?
            """,
            (payload.eurio_id, payload.face, payload.variant_kind, now_iso, asset_id),
        )
        metadata = json.dumps(
            {k: v for k, v in {"notes": payload.notes}.items() if v is not None}
        )
        cur = conn.execute(
            """
            UPDATE review_queue
               SET status = 'done', decided_eurio_id = ?, decided_face = ?,
                   decided_variant_kind = ?, decision_notes = ?, decided_at = ?,
                   decided_by = 'admin', decision_engine_version = ?,
                   decision_metadata_json = ?
             WHERE id = ? AND status = 'open'
            """,
            (payload.eurio_id, payload.face, payload.variant_kind, payload.notes,
             now_iso, _HUMAN_ENGINE_VERSION, metadata, review_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Review already decided concurrently by another voie.",
            )
        # variant_kind : COALESCE côté UPDATE → la valeur syncée est celle
        # réellement en base (relue), pas le payload potentiellement None.
        applied = conn.execute(
            "SELECT variant_kind FROM image_assets WHERE id = ?", (asset_id,),
        ).fetchone()
        emit_state_event(
            conn, asset_id=asset_id, to_state="resolved", actor="human",
            reason="human_decided", eurio_id=payload.eurio_id,
            detail_fields={
                "image_assets.eurio_id": payload.eurio_id,
                "image_assets.face": payload.face,
                "image_assets.variant_kind": applied["variant_kind"],
                "image_assets.resolution_status": "manual",
                "image_assets.resolution_confidence": 1.0,
                "image_assets.training_eligible": 1,
                "image_assets.resolved_at": now_iso,
                "review_queue.status": "done",
                "review_queue.decided_eurio_id": payload.eurio_id,
                "review_queue.decided_face": payload.face,
                "review_queue.decided_variant_kind": payload.variant_kind,
                "review_queue.decision_notes": payload.notes,
                "review_queue.decided_at": now_iso,
                "review_queue.decided_by": "admin",
                "review_queue.decision_engine_version": _HUMAN_ENGINE_VERSION,
                "review_queue.decision_metadata_json": metadata,
            },
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise

    logger.info("[review] decided id=%s eurio_id=%s face=%s",
                review_id, payload.eurio_id, payload.face)
    return {"status": "done", "id": review_id}


@router.post("/review-queue/{review_id}/reject", status_code=200)
def reject_review(
    review_id: str, principal: PrincipalDep, conn: ConnDep,
    payload: RejectPayload | None = None,
) -> dict[str, str]:
    """Marque l'IMAGE inutilisable. Avec `payload.reason` (not_a_coin /
    too_low_quality) = trash qualité tracé ; sans = reject générique."""
    reason = payload.reason if payload else None
    if reason is not None and reason not in _VALID_TRASH_REASONS:
        raise HTTPException(
            status_code=422, detail=f"reason must be one of {_VALID_TRASH_REASONS}")
    quality_reason = reason or "rejected_in_review"

    conn.execute("PRAGMA busy_timeout=5000")
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot reject twice.",
        )

    now_iso = _now_iso()
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET resolution_status = 'rejected', training_eligible = 0,
                   quality_reason = ?, resolved_at = ?
             WHERE id = ?
            """,
            (quality_reason, now_iso, rq["image_asset_id"]),
        )
        cur = conn.execute(
            """
            UPDATE review_queue
               SET status = 'done', decision_notes = ?, decided_at = ?,
                   decided_by = 'admin', decision_engine_version = ?,
                   decision_metadata_json = ?
             WHERE id = ? AND status = 'open'
            """,
            (reason or "rejected", now_iso, _HUMAN_ENGINE_VERSION,
             json.dumps({"reason": reason or "rejected"}), review_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Review already decided concurrently by another voie.",
            )
        emit_state_event(
            conn, asset_id=rq["image_asset_id"], to_state="rejected", actor="human",
            reason=(f"trash_{reason}" if reason else "rejected"),
            detail_fields={
                "image_assets.resolution_status": "rejected",
                "image_assets.training_eligible": 0,
                "image_assets.quality_reason": quality_reason,
                "image_assets.resolved_at": now_iso,
                "review_queue.status": "done",
                "review_queue.decision_notes": reason or "rejected",
                "review_queue.decided_at": now_iso,
                "review_queue.decided_by": "admin",
                "review_queue.decision_engine_version": _HUMAN_ENGINE_VERSION,
                "review_queue.decision_metadata_json":
                    json.dumps({"reason": reason or "rejected"}),
            },
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise

    logger.info("[review] rejected id=%s reason=%s", review_id, reason or "rejected")
    return {"status": "done", "id": review_id}


@router.post("/review-queue/{review_id}/skip", status_code=200)
def skip_review(
    review_id: str, principal: PrincipalDep, conn: ConnDep,
) -> dict[str, Any]:
    """Diffère l'item : bump `priority`, garde `status='open'`,
    `decision_notes='skipped'`. Aucune écriture sur image_assets."""
    conn.execute("PRAGMA busy_timeout=5000")
    rq = conn.execute(
        "SELECT id, image_asset_id, status, priority FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review is {rq['status']} — only open items can be skipped.",
        )
    try:
        cur = conn.execute(
            "UPDATE review_queue "
            "   SET priority = priority + ?, decision_notes = 'skipped' "
            " WHERE id = ? AND status = 'open'",
            (_SKIP_PRIORITY_BUMP, review_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(
                status_code=409, detail="Review is no longer open — cannot skip.")
        emit_state_event(
            conn, asset_id=rq["image_asset_id"], to_state="skipped", actor="human",
            reason="deferred",
            detail_fields={
                "review_queue.priority": rq["priority"] + _SKIP_PRIORITY_BUMP,
                "review_queue.decision_notes": "skipped",
            },
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise

    new_priority = rq["priority"] + _SKIP_PRIORITY_BUMP
    logger.info("[review] skipped id=%s new_priority=%d", review_id, new_priority)
    return {"status": "skipped", "id": review_id, "new_priority": new_priority}


@router.post("/review-queue/restore", response_model=RestoreResult)
def restore_rejected(
    payload: RestorePayload, principal: PrincipalDep, conn: ConnDep,
) -> RestoreResult:
    """Ré-ouvre des reviews rejetées (inverse de reject). Un id introuvable ou
    dont l'image n'est pas `rejected` est ignoré (listé dans `skipped`)."""
    if not payload.review_ids:
        return RestoreResult(restored=0, skipped=[])

    conn.execute("PRAGMA busy_timeout=5000")
    now_iso = _now_iso()
    restored = 0
    skipped: list[str] = []

    for review_id in payload.review_ids:
        rq = conn.execute(
            "SELECT rq.id, rq.image_asset_id, a.resolution_status "
            "  FROM review_queue rq "
            "  JOIN image_assets a ON a.id = rq.image_asset_id "
            " WHERE rq.id = ?",
            (review_id,),
        ).fetchone()
        if rq is None or rq["resolution_status"] != "rejected":
            skipped.append(review_id)
            continue
        try:
            conn.execute(
                """
                UPDATE image_assets
                   SET resolution_status = 'needs_review', training_eligible = 1,
                       quality_reason = NULL, resolved_at = NULL
                 WHERE id = ?
                """,
                (rq["image_asset_id"],),
            )
            conn.execute(
                """
                UPDATE review_queue
                   SET status = 'open', priority = ?, decided_at = NULL,
                       decided_by = NULL, decided_eurio_id = NULL, decided_face = NULL,
                       decided_variant_kind = NULL, decision_notes = ?,
                       decision_engine_version = NULL, decision_metadata_json = '{}'
                 WHERE id = ?
                """,
                (_RESTORE_PRIORITY, _RESTORED_NOTE, review_id),
            )
            emit_state_event(
                conn, asset_id=rq["image_asset_id"], to_state="queued", actor="human",
                reason="restored",
                detail_fields={
                    "image_assets.resolution_status": "needs_review",
                    "image_assets.training_eligible": 1,
                    "image_assets.quality_reason": None,
                    "image_assets.resolved_at": None,
                    "review_queue.status": "open",
                    "review_queue.priority": _RESTORE_PRIORITY,
                    "review_queue.decided_at": None,
                    "review_queue.decided_by": None,
                    "review_queue.decided_eurio_id": None,
                    "review_queue.decided_face": None,
                    "review_queue.decided_variant_kind": None,
                    "review_queue.decision_notes": _RESTORED_NOTE,
                    "review_queue.decision_engine_version": None,
                    "review_queue.decision_metadata_json": "{}",
                },
            )
            conn.commit()
            restored += 1
        except Exception:
            conn.rollback()
            raise

    logger.info("[review] restored %d rejected (skipped=%d)", restored, len(skipped))
    return RestoreResult(restored=restored, skipped=skipped)


# ── Corrections de routage review (SQL-pures, logique dans store.decisions) ───
# Jumeaux lean des routes lourdes `review/review_queue_routes.py` (skippées sur le
# VPS via `import cv2`). Chemins IDENTIQUES → le front (Direction A) les appelle
# sur le VPS via `eurioApi`. Même contrat que funnel_writes : `_commit` wrappe le
# apply_*, traduit DecisionError→HTTPException.


class CorrectListingPayload(BaseModel):
    listing_kind: str | None = None
    condition: str | None = None


def _commit(conn: sqlite3.Connection, work):
    """Exécute ``work()`` (un apply_* de store.decisions) dans la transaction de
    la requête : commit au succès, rollback + traduction HTTP sur DecisionError,
    rollback + propagation sinon."""
    from store.decisions import DecisionError

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


@router.post("/review-queue/{review_id}/correct-listing", status_code=200)
def correct_listing(
    review_id: str, payload: CorrectListingPayload,
    principal: PrincipalDep, conn: ConnDep,
) -> dict[str, Any]:
    from store.decisions import apply_correct_listing

    return _commit(conn, lambda: apply_correct_listing(
        conn, review_id, payload.listing_kind, payload.condition))


@router.post("/review-queue/{review_id}/requalify-lot", status_code=200)
def requalify_lot(
    review_id: str, principal: PrincipalDep, conn: ConnDep,
) -> dict[str, Any]:
    from store.decisions import apply_requalify_lot

    return _commit(conn, lambda: apply_requalify_lot(conn, review_id))


@router.post("/review-queue/lots/{listing_key}/requalify-single", status_code=200)
def requalify_single(
    listing_key: str, principal: PrincipalDep, conn: ConnDep,
) -> dict[str, Any]:
    from store.decisions import apply_requalify_single

    return _commit(conn, lambda: apply_requalify_single(conn, listing_key))


@router.post("/review-queue/{review_id}/move-lane", status_code=200)
def move_lane(
    review_id: str, principal: PrincipalDep, conn: ConnDep,
) -> dict[str, str]:
    from store.decisions import apply_move_lane

    return _commit(conn, lambda: apply_move_lane(conn, review_id))
