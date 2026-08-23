"""FastAPI router `/peer-arbitration` — arbitrage admin des décisions amis.

Un ami sans le scope `review:arbitrate` voit sa décision atterrir en QUARANTAINE
dans `peer_review_decisions` au lieu d'écrire le canonique (D7,
`serving/review_queue/writes.py`). Ce router est l'autre moitié de la boucle :
  - approve → applique la décision au canonique (même chemin que decide_review,
    mais provenance peer@v1 / actor=human, `review_queue.decided_by` = l'ami).
  - reject  → laisse le canonique intact, marque la décision rejetée — et le crop
    RETOURNE dans la file, puisque la file n'exclut que les décisions `pending`.
  - approve-batch → la même chose sur une sélection (lot 8, la vue bulk).

⚠️ Il n'y a plus de « staging tiré par `ml:review:reconcile` » : le pont
publish/reconcile et `review.db` sont morts avec D1 — les amis écrivent
directement le canonique via `eurio-api`.

Écritures gardées par `review:arbitrate` via `require_scope_by_method` (lot 4b,
`serving/router_scopes.py`) : un ami ne peut PAS approuver sa propre décision.

cf. docs/work-in-progress/review-collaborative-v2/
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from serving._coin_helpers import canonical_obverse_url
from store import Store, emit_state_event
from shared.verdict_scope import (
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/peer-arbitration", tags=["peer-arbitration"])

_PEER_ENGINE_VERSION = "peer@v1"
_VALID_FACES = ("obverse", "reverse", "unknown")


def _store() -> Store:
    # Lean-image safe : import depuis server_serve (no training deps) ;
    # fallback sur server.py pour les workstations full.
    try:
        from serving.server_serve import _store as shared_store
    except ImportError:
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


def _crop_url(source: str | None, asset_id: str, storage_path: str | None) -> str | None:
    """URL servable du crop — **absolue** dès qu'on connaît sa clé MinIO.

    Même doctrine, même raison qu'au lot 1 (`serving/review_queue/repository.py`) :
    le chemin relatif `/sources/…/assets/…/file` n'est servi que par l'app full de
    la workstation, et le front le résolvait contre `:8042`. Sans ça, la vue
    d'arbitrage est aveugle partout ailleurs que sur le Mac — c'est-à-dire là où
    elle sert.
    """
    if storage_path:
        try:
            from shared.storage import signed_url

            return signed_url("enrichment-crops", storage_path)
        except Exception:  # noqa: BLE001 — couche d'affichage, jamais fatale
            pass
    return f"/sources/{source}/assets/{asset_id}/file" if source else None


def _decision_row_to_item(conn, r) -> dict:
    dino_top1 = r["dino_country"] or r["dino_global"]
    target = r["decided_eurio_id"]
    return {
        "id": r["id"],
        "image_asset_id": r["image_asset_id"],
        "crop_url": _crop_url(r["asset_source"], r["image_asset_id"], r["asset_storage_path"]),
        "canonical_url": canonical_obverse_url(conn, target) if target else None,
        "listing_title": r["listing_title"] or "",
        "listing_url": r["listing_url"],
        "source": r["asset_source"] or "—",
        "reviewer_name": r["reviewer_name"],
        "reviewer_token": r["reviewer_token"],
        "action": r["action"],
        "decided_eurio_id": target,
        "decided_label": _coin_label(conn, target),
        "decided_face": r["decided_face"],
        "quality_reason": r["quality_reason"],
        "notes": r["notes"],
        "decided_at": r["decided_at"],
        "dino_top1_eurio_id": dino_top1,
        "dino_top1_label": _coin_label(conn, dino_top1),
        "concords": bool(r["concords"]),
        # Trois états, pas deux : « la machine dit autre chose » et « la machine
        # ne dit rien » se rangent tous deux du côté non coché (ni l'un ni
        # l'autre n'est une confirmation), mais les confondre à l'écran ferait
        # lire un désaccord là où il n'y a qu'un silence.
        "dino_state": (
            "concords" if r["concords"]
            else ("absent" if not dino_top1 else "disagrees")
        ),
    }


# `concords` calculé en SQL et NON en Python : c'est la clé de TRI (D8 — les
# désaccords en tête et non cochés). Trié en Python, l'ordre ne survivrait pas à
# la pagination du scroll infini : la page 2 rejouerait des concordances déjà vues
# et laisserait des désaccords derrière.
_CONCORDS_SQL = """
    CASE WHEN pr.action = 'accept'
          AND pr.decided_eurio_id IS NOT NULL
          AND pr.decided_eurio_id = COALESCE(p.top1_country_eurio_id, p.top1_eurio_id)
         THEN 1 ELSE 0 END
"""

_LIST_FROM_SQL = f"""
      FROM peer_review_decisions pr
      LEFT JOIN image_assets a ON a.id = pr.image_asset_id
      LEFT JOIN source_images s ON s.id = a.source_image_id
      LEFT JOIN image_asset_dino_predictions p
             ON p.asset_id = pr.image_asset_id
            AND p.encoder_version = '{VERDICT_ENCODER_VERSION}'
            AND p.anchors_kind = '{VERDICT_ANCHORS_KIND}'
     WHERE pr.arbitration_status = 'pending'
"""


@router.get("")
def list_pending(
    limit: int = 60,
    offset: int = 0,
    reviewer: str | None = None,
) -> dict:
    """Décisions en attente d'arbitrage, enrichies pour la vue bulk.

    Tri (D8) : **désaccords avec DINO d'abord**, puis par ancienneté. « Tout
    validé par défaut » sur un scroll infini est un tampon en caoutchouc ; les
    deux tiers concordants peuvent défiler vite, le tiers où l'humain contredit
    la machine exige un geste positif — donc il passe devant.

    `reviewer` filtre sur `reviewer_token` (les onglets par personne).
    `limit`/`offset` paginent le scroll infini ; `total` dit quand s'arrêter.
    """
    conn = _store()._connection()  # noqa: SLF001
    params: list = []
    where_reviewer = ""
    if reviewer:
        where_reviewer = " AND pr.reviewer_token = ?"
        params.append(reviewer)

    total = conn.execute(
        f"SELECT count(*) {_LIST_FROM_SQL}{where_reviewer}", params
    ).fetchone()[0]

    rows = conn.execute(
        f"""
        SELECT pr.*, s.source AS asset_source, a.storage_path AS asset_storage_path,
               s.listing_title AS listing_title, s.source_url AS listing_url,
               p.top1_country_eurio_id AS dino_country, p.top1_eurio_id AS dino_global,
               {_CONCORDS_SQL} AS concords
        {_LIST_FROM_SQL}{where_reviewer}
         ORDER BY concords ASC, pr.decided_at ASC, pr.id ASC
         LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    items = [_decision_row_to_item(conn, r) for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


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


def _approve_one(conn, decision_id: str) -> dict:
    """Le corps de l'approbation, partagé par `/approve` et `/approve-batch`.

    Extrait tel quel du handler unitaire au lot 8 : la vue bulk devait boucler
    dessus, et une seconde implémentation de l'écriture canonique aurait été
    exactement le genre de divergence muette contre laquelle `eurio-verify`
    existe — deux chemins d'écriture qui dérivent sans que rien n'échoue.
    """
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


@router.post("/{decision_id}/approve")
def approve(decision_id: str) -> dict:
    """Applique la décision de l'ami au canonique (provenance peer)."""
    store = _store()
    return _approve_one(store._connection(), decision_id)  # noqa: SLF001


class ApproveBatchPayload(BaseModel):
    ids: list[str]


@router.post("/approve-batch")
def approve_batch(payload: ApproveBatchPayload) -> dict:
    """Approuve une sélection en un geste (lot 8 — la vue bulk).

    Chaque décision est traitée par `_approve_one`, dans SA propre transaction.
    Une décision qui échoue ne fait donc PAS tomber le lot : elle est rangée dans
    `failed` avec sa raison et les autres passent. C'est le comportement voulu
    ici — sur un lot de cent, un 409 « déjà arbitrée » (une voie locale est
    passée entre-temps) est un cas NORMAL, pas une panne, et perdre les
    quatre-vingt-dix-neuf autres pour lui serait absurde.

    `superseded` remonte tel quel : la ligne `review_queue` avait déjà été
    tranchée localement, le canonique n'est pas réécrit.
    """
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Aucun identifiant fourni.")
    # Borne franche plutôt qu'un lot d'une taille arbitraire : la vue bulk
    # pagine par 60, le garde-fou à 50 du front demande déjà un second clic.
    if len(payload.ids) > 500:
        raise HTTPException(
            status_code=400,
            detail=f"Lot trop grand ({len(payload.ids)} > 500) — pagine.",
        )

    store = _store()
    conn = store._connection()  # noqa: SLF001
    approved: list[str] = []
    superseded: list[str] = []
    failed: list[dict] = []

    for decision_id in payload.ids:
        try:
            res = _approve_one(conn, decision_id)
        except HTTPException as exc:
            failed.append({"id": decision_id, "detail": str(exc.detail), "status": exc.status_code})
            continue
        except Exception as exc:  # noqa: BLE001 — un lot ne tombe pas pour un item
            logger.exception("[peer-arbitration] approve-batch id=%s", decision_id)
            failed.append({"id": decision_id, "detail": str(exc), "status": 500})
            continue
        (superseded if res["status"] == "superseded" else approved).append(decision_id)

    logger.info(
        "[peer-arbitration] approve-batch demandées=%d approuvées=%d supersédées=%d échouées=%d",
        len(payload.ids), len(approved), len(superseded), len(failed),
    )
    return {
        "requested": len(payload.ids),
        "approved": approved,
        "superseded": superseded,
        "failed": failed,
    }


class RejectPayload(BaseModel):
    notes: str | None = None


class RejectBatchPayload(BaseModel):
    ids: list[str]
    notes: str | None = None


@router.post("/reject-batch")
def reject_batch(payload: RejectBatchPayload) -> dict:
    """Rejette une sélection — le canonique reste intact (lot 8).

    Le jumeau indispensable d'`approve-batch` : ce que l'arbitre écarte doit
    RETOURNER dans la file. Laisser la décision `pending` la garderait hors de
    la file indéfiniment (`NOT_QUARANTINED_SQL`), donc le crop disparaîtrait
    sans que personne ne l'ait tranché — une perte muette.
    """
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Aucun identifiant fourni.")
    if len(payload.ids) > 500:
        raise HTTPException(
            status_code=400,
            detail=f"Lot trop grand ({len(payload.ids)} > 500) — pagine.",
        )
    store = _store()
    conn = store._connection()  # noqa: SLF001
    rejected: list[str] = []
    failed: list[dict] = []
    for decision_id in payload.ids:
        try:
            _fetch_pending(conn, decision_id)
        except HTTPException as exc:
            failed.append({"id": decision_id, "detail": str(exc.detail), "status": exc.status_code})
            continue
        with store._writing() as wconn:  # noqa: SLF001
            wconn.execute(
                "UPDATE peer_review_decisions "
                "SET arbitration_status = 'rejected', arbitrated_at = ?, arbitration_notes = ? "
                "WHERE id = ? AND arbitration_status = 'pending'",
                (_now_iso(), payload.notes, decision_id),
            )
        rejected.append(decision_id)
    logger.info(
        "[peer-arbitration] reject-batch demandées=%d rejetées=%d échouées=%d",
        len(payload.ids), len(rejected), len(failed),
    )
    return {"requested": len(payload.ids), "rejected": rejected, "failed": failed}


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
