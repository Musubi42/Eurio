"""Décisions de review — logique SQL-pure partagée local ↔ VPS lean.

Une SEULE implémentation de chaque décision humaine (funnel « Jeu d'entraînement »
+ décision de lot), pour qu'elle soit servie à l'identique par :
- l'API ML locale lourde (`serving/lab_routes.py`, `review/review_queue_routes.py`),
- l'image lean canonique du VPS (`serving/funnel_writes.py`).

Ce module vit dans `store/` (sol cv2-free déjà importé des deux côtés) et
n'importe QUE `sqlite3/json/uuid/datetime` + `store.events` (emit_*) +
`store.training_scan`. **Aucun import `serving.*`/`review.*`** — sinon on
retraînerait cv2/torch sur l'image lean.

Contrat transactionnel (identique à `emit_state_event`) : chaque `apply_*` prend
`conn`, exécute ses SELECT/UPDATE/emit **SANS `BEGIN`/`COMMIT`/`rollback`**. Le
CALLER possède la transaction :
- local (Store, `isolation_level=None` autocommit) : les handlers funnel font un
  `conn.commit()` no-op ; le lot enveloppe explicitement `BEGIN`/`COMMIT`.
- lean (`serving/deps.py:db_connection`, isolation par défaut) : `conn.commit()`
  finalise la transaction implicite ouverte au 1er DML.

Erreurs métier levées en `DecisionError(status_code, detail)` (pas de dépendance
FastAPI ici) ; les routers la traduisent en `HTTPException`.

Cf. docs/work-in-progress/local-sync/migration-direction-a.md (C2a) +
serving/review_queue/writes.py (le split-frère decide/reject/restore).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from store.events import emit_field_event, emit_state_event


class DecisionError(Exception):
    """Erreur métier d'une décision (traduite en HTTPException par le routeur)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Constantes partagées (source unique — review_queue_routes.py les ré-importe) ─
_HUMAN_ENGINE_VERSION = "human@v1"
_VALID_FACES = ("obverse", "reverse", "unknown")
_VALID_REJECT_REASONS = (
    "not_a_coin", "out_of_scope", "duplicate_in_listing", "unreadable", "other",
)

# listing_key extraction — eBay : `ebay_<itemId>` via raw_payload_json ; sinon
# fallback `source_ref`. (alias source_images = si)
_LISTING_KEY_SQL = """
CASE
  WHEN si.source = 'ebay'
   AND json_extract(si.raw_payload_json, '$.ebay_item_id') IS NOT NULL
    THEN 'ebay_' || json_extract(si.raw_payload_json, '$.ebay_item_id')
  ELSE si.source_ref
END
"""


def _now_iso() -> str:
    """Timestamp UTC ISO-8601 avec suffixe Z (format des `decided_at`/`resolved_at`
    côté review — tri lexicographique cohérent). Ex : ``2026-05-25T14:30:00Z``."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _now_offset() -> str:
    """Timestamp UTC ISO-8601 forme ``+00:00`` (format historique des handlers
    funnel de lab_routes — conservé tel quel pour parité byte-à-byte)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LotAssignmentLike(Protocol):
    """Duck-type d'un assignment de lot (pydantic LotAssignment OU dataclass test)."""
    asset_id: str
    eurio_id: str | None
    face: str | None
    variant_kind: str | None
    reject_reason: str | None
    skip: bool


# ── Funnel « Jeu d'entraînement » ────────────────────────────────────────────


def apply_accept_training(conn, asset_id: str) -> dict:
    """« Accepter au train » : confirme le crop dans sa classe courante
    (``resolution_status='manual'`` + ``resolution_confidence=1.0`` +
    ``training_eligible=1`` + ``resolved_at``), ferme la row review ouverte, émet
    l'event 'resolved'. Miroir de la décision de review single-item."""
    row = conn.execute(
        "SELECT id, eurio_id, face FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        raise DecisionError(404, "Crop introuvable")
    now = _now_offset()
    conn.execute(
        "UPDATE image_assets SET resolution_status = 'manual', "
        "resolution_confidence = 1.0, training_eligible = 1, resolved_at = ? "
        "WHERE id = ?",
        (now, asset_id),
    )
    conn.execute(
        "UPDATE review_queue SET status = 'done', decided_eurio_id = ?, "
        "decided_face = ?, decided_at = ?, decided_by = 'human', "
        "decision_notes = 'accepté au train depuis le jeu d''entraînement' "
        "WHERE image_asset_id = ? AND status = 'open'",
        (row["eurio_id"], row["face"], now, asset_id),
    )
    emit_state_event(
        conn, asset_id=asset_id, to_state="resolved", actor="human",
        reason="accepted_from_training_set", eurio_id=row["eurio_id"],
        detail_fields={
            "image_assets.resolution_status": "manual",
            "image_assets.resolution_confidence": 1.0,
            "image_assets.training_eligible": 1,
            "image_assets.resolved_at": now,
            "review_queue.status": "done",
            "review_queue.decided_eurio_id": row["eurio_id"],
            "review_queue.decided_face": row["face"],
            "review_queue.decided_at": now,
            "review_queue.decided_by": "human",
            "review_queue.decision_notes":
                "accepté au train depuis le jeu d'entraînement",
        },
    )
    return {
        "asset_id": asset_id, "eurio_id": row["eurio_id"],
        "resolution_status": "manual", "training_eligible": True,
    }


def apply_reopen_review(conn, asset_id: str) -> dict:
    """« Repasser en reviewer » : ``needs_review`` + ``resolved_at=NULL`` +
    ``training_eligible=0``, puis UPSERT d'une row review OUVERTE (contrainte
    ``UNIQUE(image_asset_id)``). Retourne le review_id (relu dans la transaction)."""
    row = conn.execute(
        "SELECT id, eurio_id FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        raise DecisionError(404, "Crop introuvable")
    now = _now_offset()
    new_id = uuid.uuid4().hex
    note = "repassé en review depuis le jeu d'entraînement"
    conn.execute(
        "UPDATE image_assets SET resolution_status = 'needs_review', "
        "resolved_at = NULL, training_eligible = 0 WHERE id = ?",
        (asset_id,),
    )
    conn.execute(
        """
        INSERT INTO review_queue (
            id, image_asset_id, status, priority, enqueued_at, kind,
            decision_notes, lane, lane_source
        ) VALUES (?, ?, 'open', 100, ?, 'single', ?, 'manual', 'human')
        ON CONFLICT(image_asset_id) DO UPDATE SET
            status = 'open',
            priority = 100,
            enqueued_at = excluded.enqueued_at,
            kind = 'single',
            decision_notes = excluded.decision_notes,
            lane = 'manual',
            lane_source = 'human',
            decided_eurio_id = NULL,
            decided_face = NULL,
            decided_variant_kind = NULL,
            decided_at = NULL,
            decided_by = NULL
        """,
        (new_id, asset_id, now, note),
    )
    emit_state_event(
        conn, asset_id=asset_id, to_state="queued", actor="human",
        reason="reopened_from_training_set",
        detail_fields={
            "image_assets.resolution_status": "needs_review",
            "image_assets.resolved_at": None,
            "image_assets.training_eligible": 0,
            "review_queue.status": "open",
            "review_queue.priority": 100,
            "review_queue.enqueued_at": now,
            "review_queue.kind": "single",
            "review_queue.decision_notes": note,
            "review_queue.lane": "manual",
            "review_queue.lane_source": "human",
            "review_queue.decided_eurio_id": None,
            "review_queue.decided_face": None,
            "review_queue.decided_variant_kind": None,
            "review_queue.decided_at": None,
            "review_queue.decided_by": None,
        },
    )
    rid_row = conn.execute(
        "SELECT id FROM review_queue WHERE image_asset_id = ?", (asset_id,),
    ).fetchone()
    return {
        "asset_id": asset_id, "eurio_id": row["eurio_id"],
        "review_id": rid_row["id"],
    }


def apply_set_training_eligible(conn, asset_id: str, eligible: bool) -> dict:
    """Inclut/exclut un crop du train. Exclure pose
    ``quality_reason='manual_triage'`` ; ré-inclure l'efface conditionnellement."""
    row = conn.execute(
        "SELECT id, eurio_id FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        raise DecisionError(404, "Crop introuvable")
    if eligible:
        conn.execute(
            "UPDATE image_assets SET training_eligible = 1, "
            "quality_reason = CASE WHEN quality_reason = 'manual_triage' "
            "THEN NULL ELSE quality_reason END WHERE id = ?",
            (asset_id,),
        )
    else:
        conn.execute(
            "UPDATE image_assets SET training_eligible = 0, "
            "quality_reason = 'manual_triage' WHERE id = ?",
            (asset_id,),
        )
    new = conn.execute(
        "SELECT training_eligible, quality_reason FROM image_assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    emit_field_event(
        conn, asset_id=asset_id, reason="training_eligible",
        fields={
            "image_assets.training_eligible": int(new["training_eligible"]),
            "image_assets.quality_reason": new["quality_reason"],
        },
    )
    return {
        "asset_id": asset_id, "eurio_id": row["eurio_id"],
        "training_eligible": bool(new["training_eligible"]),
    }


def apply_reassign(conn, asset_id: str, target_eurio_id: str) -> dict:
    """Réassigne un crop à une autre pièce (``eurio_id`` seul) — écriture CANONIQUE
    pure.

    Le verdict intrus (périmé après changement de classe) N'est PAS dismissé ici :
    c'est un OVERLAY LOCAL (table ``cohort_training_scan_results``, absente du
    canonique VPS) → le dismisser sur la connexion VPS serait un no-op mort
    (C3/CodeReview). Le nettoyage de l'overlay est fait par le caller LOCAL
    (``lab_routes.reassign_asset`` en full-server) et par le FRONT en Direction A
    (fire ``dismissIntruder`` via l'API ML locale au succès du reassign)."""
    target = (target_eurio_id or "").strip()
    if not target:
        raise DecisionError(422, "eurio_id cible requis")
    row = conn.execute(
        "SELECT id, eurio_id FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        raise DecisionError(404, "Crop introuvable")
    coin = conn.execute(
        "SELECT eurio_id FROM coins WHERE eurio_id = ?", (target,),
    ).fetchone()
    if coin is None:
        raise DecisionError(404, f"Pièce cible inconnue : {target}")
    conn.execute(
        "UPDATE image_assets SET eurio_id = ? WHERE id = ?", (target, asset_id),
    )
    emit_field_event(
        conn, asset_id=asset_id, reason="reassign", eurio_id=target,
        fields={"image_assets.eurio_id": target},
        detail={"previous_eurio_id": row["eurio_id"]},
    )
    return {
        "asset_id": asset_id, "eurio_id": target,
        "previous_eurio_id": row["eurio_id"],
    }


# ── Décision de lot (bulk sur un listing) ────────────────────────────────────


@dataclass
class LotDecideOutcome:
    done: int
    rejected: int
    skipped: int
    errors: list


def apply_lot_decide(conn, listing_key: str, assignments) -> dict:
    """Décision bulk sur un listing entier. Pour chaque assignment : decide
    (eurio_id), reject (reject_reason) ou skip. Idempotent par état terminal :
    une row déjà non-'open' part dans ``errors`` sans casser. Valide que chaque
    asset appartient au listing. Lève DecisionError(404) si le lot est inconnu.

    ``assignments`` = itérable d'objets avec .asset_id/.eurio_id/.face/
    .variant_kind/.reject_reason/.skip (duck-typé : pydantic OU dataclass)."""
    assignments = list(assignments)
    if not assignments:
        return {"done": 0, "rejected": 0, "skipped": 0, "errors": []}

    listing_assets = {
        r["asset_id"]: r
        for r in conn.execute(
            f"""
            SELECT a.id AS asset_id,
                   rq.id AS review_id,
                   rq.status AS rq_status
              FROM source_images si
              JOIN image_assets a ON a.source_image_id = si.id
              LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
             WHERE {_LISTING_KEY_SQL} = ?
            """,
            (listing_key,),
        ).fetchall()
    }
    if not listing_assets:
        raise DecisionError(404, f"Lot '{listing_key}' not found.")

    now_iso = _now_iso()
    n_done = n_rejected = n_skipped = 0
    errors: list = []

    for asg in assignments:
        asset_row = listing_assets.get(asg.asset_id)
        if asset_row is None:
            errors.append(f"asset {asg.asset_id} does not belong to lot {listing_key}")
            continue
        review_id = asset_row["review_id"]
        rq_status = asset_row["rq_status"]
        if review_id is None:
            errors.append(f"asset {asg.asset_id} has no review_queue row")
            continue
        if rq_status != "open":
            errors.append(f"asset {asg.asset_id} already {rq_status}")
            continue

        # Decide path
        if asg.eurio_id:
            face = asg.face or "unknown"
            if face not in _VALID_FACES:
                errors.append(f"asset {asg.asset_id} invalid face '{face}'")
                continue
            conn.execute(
                """
                UPDATE image_assets
                   SET eurio_id = ?, face = ?,
                       variant_kind = COALESCE(?, variant_kind),
                       resolution_status = 'manual',
                       resolution_confidence = 1.0,
                       training_eligible = 1,
                       resolved_at = ?
                 WHERE id = ?
                """,
                (asg.eurio_id, face, asg.variant_kind, now_iso, asg.asset_id),
            )
            cur = conn.execute(
                """
                UPDATE review_queue
                   SET status = 'done',
                       decided_eurio_id = ?, decided_face = ?,
                       decided_variant_kind = ?, decided_at = ?,
                       decided_by = 'admin',
                       decision_engine_version = ?,
                       decision_metadata_json = ?
                 WHERE id = ? AND status = 'open'
                """,
                (asg.eurio_id, face, asg.variant_kind, now_iso,
                 _HUMAN_ENGINE_VERSION,
                 json.dumps({"context": "lot_bulk", "face_chosen": face}),
                 review_id),
            )
            if cur.rowcount != 1:
                errors.append(f"asset {asg.asset_id} decided concurrently — skipped")
                continue
            applied = conn.execute(
                "SELECT variant_kind FROM image_assets WHERE id = ?",
                (asg.asset_id,),
            ).fetchone()
            emit_state_event(
                conn, asset_id=asg.asset_id, to_state="resolved",
                actor="human", reason="human_decided_lot", eurio_id=asg.eurio_id,
                detail_fields={
                    "image_assets.eurio_id": asg.eurio_id,
                    "image_assets.face": face,
                    "image_assets.variant_kind": applied["variant_kind"],
                    "image_assets.resolution_status": "manual",
                    "image_assets.resolution_confidence": 1.0,
                    "image_assets.training_eligible": 1,
                    "image_assets.resolved_at": now_iso,
                    "review_queue.status": "done",
                    "review_queue.decided_eurio_id": asg.eurio_id,
                    "review_queue.decided_face": face,
                    "review_queue.decided_variant_kind": asg.variant_kind,
                    "review_queue.decided_at": now_iso,
                    "review_queue.decided_by": "admin",
                    "review_queue.decision_engine_version": _HUMAN_ENGINE_VERSION,
                    "review_queue.decision_metadata_json":
                        json.dumps({"context": "lot_bulk", "face_chosen": face}),
                },
            )
            n_done += 1

        # Reject path
        elif asg.reject_reason:
            if asg.reject_reason not in _VALID_REJECT_REASONS:
                errors.append(
                    f"asset {asg.asset_id} invalid reject_reason "
                    f"'{asg.reject_reason}' — accepted: {_VALID_REJECT_REASONS}"
                )
                continue
            conn.execute(
                """
                UPDATE image_assets
                   SET resolution_status = 'rejected',
                       training_eligible = 0,
                       quality_reason = 'rejected_in_review',
                       resolved_at = ?
                 WHERE id = ?
                """,
                (now_iso, asg.asset_id),
            )
            cur = conn.execute(
                """
                UPDATE review_queue
                   SET status = 'done',
                       decision_notes = ?, decided_at = ?, decided_by = 'admin',
                       decision_engine_version = ?,
                       decision_metadata_json = ?
                 WHERE id = ? AND status = 'open'
                """,
                (asg.reject_reason, now_iso, _HUMAN_ENGINE_VERSION,
                 json.dumps({"reason": asg.reject_reason, "context": "lot_bulk"}),
                 review_id),
            )
            if cur.rowcount != 1:
                errors.append(f"asset {asg.asset_id} decided concurrently — skipped")
                continue
            emit_state_event(
                conn, asset_id=asg.asset_id, to_state="rejected",
                actor="human", reason=f"trash_{asg.reject_reason}",
                detail_fields={
                    "image_assets.resolution_status": "rejected",
                    "image_assets.training_eligible": 0,
                    "image_assets.quality_reason": "rejected_in_review",
                    "image_assets.resolved_at": now_iso,
                    "review_queue.status": "done",
                    "review_queue.decision_notes": asg.reject_reason,
                    "review_queue.decided_at": now_iso,
                    "review_queue.decided_by": "admin",
                    "review_queue.decision_engine_version": _HUMAN_ENGINE_VERSION,
                    "review_queue.decision_metadata_json": json.dumps(
                        {"reason": asg.reject_reason, "context": "lot_bulk"}
                    ),
                },
            )
            n_rejected += 1

        # Skip path
        elif asg.skip:
            cur = conn.execute(
                "UPDATE review_queue SET status = 'skipped' "
                " WHERE id = ? AND status = 'open'",
                (review_id,),
            )
            if cur.rowcount != 1:
                errors.append(f"asset {asg.asset_id} decided concurrently — skipped")
                continue
            emit_state_event(
                conn, asset_id=asg.asset_id, to_state="skipped",
                actor="human", reason="deferred_lot",
                detail_fields={"review_queue.status": "skipped"},
            )
            n_skipped += 1

        else:
            errors.append(
                f"asset {asg.asset_id} has no action "
                "(provide eurio_id, reject_reason, or skip=true)"
            )

    return {
        "done": n_done, "rejected": n_rejected,
        "skipped": n_skipped, "errors": errors,
    }


# ── Corrections de routage review (requalif kind, lane, taxonomie listing) ────
# SQL-pures comme les décisions ci-dessus → servies à l'identique par la route
# lourde locale (`review/review_queue_routes.py`, skippée sur le VPS à cause d'un
# `import cv2`) ET le jumeau lean VPS (`serving/review_queue/writes.py`). Direction
# A : le front les appelle sur le VPS via `eurioApi` (chemins identiques).

_VALID_LISTING_KINDS = ("single", "lot", "coffret", "graded_slab")
_VALID_CONDITIONS = ("UNC", "TTB", "TB")


def apply_correct_listing(
    conn, review_id: str, listing_kind: str | None = None,
    condition: str | None = None,
) -> dict:
    """Corrige manuellement ``listing_kind`` et/ou ``condition`` d'un listing.
    Propage à TOUTES les source_images du listing (identité = ``source_url``) et
    pose ``extractor_version='manual'`` (le step C2 text_signal ne ré-écrasera
    plus). Indépendant de l'attribution — la review reste ``open``."""
    if listing_kind is None and condition is None:
        raise DecisionError(422, "Provide listing_kind and/or condition.")
    if listing_kind is not None and listing_kind not in _VALID_LISTING_KINDS:
        raise DecisionError(422, f"listing_kind must be one of {_VALID_LISTING_KINDS}")
    if condition is not None and condition not in _VALID_CONDITIONS:
        raise DecisionError(422, f"condition must be one of {_VALID_CONDITIONS}")

    si = conn.execute(
        """
        SELECT s.id AS sid, s.source, s.source_url
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if si is None:
        raise DecisionError(404, "Review item not found.")

    if si["source_url"]:
        sibling_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM source_images WHERE source = ? AND source_url = ?",
                (si["source"], si["source_url"]),
            ).fetchall()
        ]
    else:
        sibling_ids = [si["sid"]]

    sets = ["extractor_version = 'manual'", "computed_at = datetime('now')"]
    args: list = []
    if listing_kind is not None:
        sets.append("listing_kind = ?")
        sets.append("listing_kind_confidence = 1.0")
        args.append(listing_kind)
    if condition is not None:
        sets.append("condition_normalized = ?")
        sets.append("condition_confidence = 1.0")
        args.append(condition)

    placeholders = ",".join("?" * len(sibling_ids))
    conn.execute(
        f"UPDATE listing_text_signals SET {', '.join(sets)} "  # noqa: S608
        f"WHERE source_image_id IN ({placeholders})",
        (*args, *sibling_ids),
    )
    return {
        "status": "ok", "id": review_id, "n_images": len(sibling_ids),
        "listing_kind": listing_kind, "condition": condition,
    }


def _requalify_rows(conn, sids: list, target_kind: str) -> int:
    """Bascule les rows review ``open`` des source_images ``sids`` vers
    ``target_kind`` ('lot' | 'single') + event par row + taxonomie
    ``listing_text_signals.listing_kind``. Idempotent (filtre ``kind != target``).
    Retourne le nb de rows basculées."""
    ph = ",".join("?" * len(sids))
    affected = [
        r["image_asset_id"] for r in conn.execute(
            f"""
            SELECT image_asset_id FROM review_queue
             WHERE status = 'open' AND kind != ?
               AND image_asset_id IN (
                   SELECT a.id FROM image_assets a
                    WHERE a.source_image_id IN ({ph})
               )
            """,  # noqa: S608
            (target_kind, *sids),
        ).fetchall()
    ]
    cur = conn.execute(
        f"""
        UPDATE review_queue SET kind = ?
         WHERE status = 'open' AND kind != ?
           AND image_asset_id IN (
               SELECT a.id FROM image_assets a
                WHERE a.source_image_id IN ({ph})
           )
        """,  # noqa: S608
        (target_kind, target_kind, *sids),
    )
    for aid in affected:
        emit_field_event(
            conn, asset_id=aid, reason="requalify",
            fields={"review_queue.kind": target_kind},
        )
    conn.execute(
        f"""
        UPDATE listing_text_signals
           SET listing_kind = ?, listing_kind_confidence = 1.0,
               extractor_version = 'manual', computed_at = datetime('now')
         WHERE source_image_id IN ({ph})
        """,  # noqa: S608
        (target_kind, *sids),
    )
    return cur.rowcount or 0


def apply_requalify_lot(conn, review_id: str) -> dict:
    """« Ce single est en fait un lot » : bascule TOUT le listing du crop en
    ``kind='lot'`` (les rows quittent la queue single → flow lot)."""
    row = conn.execute(
        f"""
        SELECT {_LISTING_KEY_SQL} AS listing_key
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
         WHERE rq.id = ?
        """,  # noqa: S608
        (review_id,),
    ).fetchone()
    if row is None or not row["listing_key"]:
        raise DecisionError(404, "Review item not found.")
    listing_key = row["listing_key"]
    sids = [
        r["sid"] for r in conn.execute(
            f"SELECT si.id AS sid FROM source_images si "  # noqa: S608
            f"WHERE {_LISTING_KEY_SQL} = ?",
            (listing_key,),
        ).fetchall()
    ]
    if not sids:
        raise DecisionError(404, "Listing has no images.")
    n = _requalify_rows(conn, sids, "lot")
    return {
        "status": "ok", "listing_key": listing_key,
        "n_requalified": n, "n_images": len(sids),
    }


def apply_requalify_single(conn, listing_key: str) -> dict:
    """Inverse : ce listing n'est PAS un lot (faux positif v2) → rebascule ses
    rows ``open`` en ``kind='single'`` (repartent dans le flow single)."""
    sids = [
        r["sid"] for r in conn.execute(
            f"SELECT si.id AS sid FROM source_images si "  # noqa: S608
            f"WHERE {_LISTING_KEY_SQL} = ?",
            (listing_key,),
        ).fetchall()
    ]
    if not sids:
        raise DecisionError(404, f"Lot '{listing_key}' not found.")
    n = _requalify_rows(conn, sids, "single")
    return {
        "status": "ok", "listing_key": listing_key,
        "n_requalified": n, "n_images": len(sids),
    }


def apply_move_lane(conn, review_id: str) -> dict:
    """Déplace un item ``open`` vers la lane MANUELLE (sticky ``lane_source=
    'human'`` → aucun recalcul Dino ne le ré-routera). Sens utile : sortir un
    item de l'auto-accept pour le trancher à la main."""
    cur = conn.execute(
        "UPDATE review_queue SET lane = 'manual', lane_source = 'human' "
        "WHERE id = ? AND status = 'open'",
        (review_id,),
    )
    if cur.rowcount != 1:
        raise DecisionError(
            404, "Review item introuvable ou non-ouvert (déjà décidé ?).",
        )
    rq = conn.execute(
        "SELECT image_asset_id FROM review_queue WHERE id = ?", (review_id,),
    ).fetchone()
    emit_field_event(
        conn, asset_id=rq["image_asset_id"], reason="move_lane",
        fields={
            "review_queue.lane": "manual",
            "review_queue.lane_source": "human",
        },
    )
    return {"status": "ok", "id": review_id, "lane": "manual"}
