"""Auto-acceptation — module LEAN, servi par le canonique.

POURQUOI CE MODULE EXISTE
--------------------------
La route vivait dans `review/review_queue_routes.py`, que l'image du VPS ne
peut pas charger (`import cv2`, puis `training`). Vérifié sur l'OpenAPI de
production le 2026-08-27 : `/review-queue/auto-accept/run` **n'y était pas**.
Le VPS étant le seul writer (Direction A), l'auto-acceptation n'était donc
**exécutable nulle part** — ni en prod (route absente), ni en local (réplique
en lecture seule). C'est la vraie raison du zéro auto-accept depuis le
2026-07-08, et ce n'était pas un choix.

CE QUI CHANGE AUSSI, ET C'EST LE FOND
--------------------------------------
L'ancienne requête filtrait `rq.lane = 'auto_accept'` — **la lane**, une
étiquette écrite UNE FOIS à l'enqueue. Le verdict, lui, se recalcule. Les deux
divergent donc par construction, et ils avaient divergé : mesuré le
2026-08-27, la lane disait `auto_accept` pour **960** crops quand le verdict du
jour en qualifiait **2 308** — 1 396 crops bons, invisibles de l'écran.

Ici la sélection SQL ne parle plus de lane. Elle sert tous les crops ouverts, et
c'est le **verdict recalculé** qui tranche, crop par crop. L'écran ne peut plus
être périmé, et il n'y a plus de passe de rafraîchissement à ne pas oublier.

CE QUE LA LANE GARDE COMME RÔLE
--------------------------------
Un seul, et il est humain : `lane='manual' AND lane_source='human'` veut dire
« un humain a tiré ce crop hors de l'auto ». C'est STICKY, et c'est le seul
usage de la lane dans ce module. Le geste humain reste souverain.

Même écriture que l'ancienne route, au caractère près : `decided_by='auto_dino'`
(le seul compteur qui distingue la machine de l'humain — la route `decide`
estampille l'appelant, elle ne peut donc pas servir à ça), atomicité
« premier-écrit-gagne » par `AND status='open'`, et snapshot des signaux Dino
dans `decision_metadata_json`.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from serving.review_queue.service import auto_validate_decision
from shared.verdict_scope import VERDICT_ANCHORS_KIND, VERDICT_ENCODER_VERSION
from store import emit_state_event

logger = logging.getLogger("eurio-api.auto_accept")

router = APIRouter(tags=["review-queue"])

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(require_scope("review:write"))]

_AUTO_DINO_ENGINE_VERSION = "auto_dino@s0.55-d0.05"
_RESTORED_NOTE = "restored"
_VALID_KINDS = ("single", "lot", "all")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AutoAcceptPreviewItem(BaseModel):
    review_id: str
    image_asset_id: str
    crop_url: str
    listing_title: str
    listing_url: str | None = None
    source: str
    target_eurio_id: str
    target_label: str
    sim: float | None = None
    spread: float | None = None
    face_detected: str | None = None
    reason: str


class AutoAcceptResult(BaseModel):
    processed: int
    accepted: int
    skipped_concurrent: int = 0
    by_category: dict[str, int]
    dry_run: bool
    preview: list[AutoAcceptPreviewItem] = []
    # Combien de crops le verdict qualifie AU TOTAL, indépendamment de `limit`.
    # Sans lui, un `limit` bas ferait croire que le gisement est épuisé.
    n_eligible_total: int = 0


class AutoAcceptRunBody(BaseModel):
    """`review_ids` fourni ⇒ on n'accepte que ceux-là, et les AUTRES items
    éligibles servis dans la même passe sont démotés en `manual` sticky : c'est
    le geste « j'ai décoché » de l'écran de preview."""

    review_ids: list[str] | None = None


_SQL = f"""
SELECT rq.id AS review_id, rq.image_asset_id,
       a.face,
       s.source, s.source_url AS listing_url, s.listing_title,
       s.target_eurio_id,
       c.country_name AS t_country_name, c.year AS t_year, c.theme AS t_theme,
       p.top1_eurio_id, p.top1_country_eurio_id,
       p.top1_sim, p.top1_country_sim, p.spread, p.country_spread,
       lts.vs_target_verdict
  FROM review_queue rq
  JOIN image_assets a  ON a.id = rq.image_asset_id
  JOIN source_images s ON s.id = a.source_image_id
  LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
  LEFT JOIN image_asset_dino_predictions p
         ON p.asset_id = a.id
        AND p.encoder_version = '{VERDICT_ENCODER_VERSION}'
        AND p.anchors_kind = '{VERDICT_ANCHORS_KIND}'
  LEFT JOIN listing_text_signals lts ON lts.source_image_id = s.id
 WHERE rq.status = 'open'
   AND (rq.decision_notes IS NULL OR rq.decision_notes != '{_RESTORED_NOTE}')
   -- Le SEUL usage de la lane ici : un humain a tiré ce crop hors de l'auto.
   AND NOT (rq.lane = 'manual' AND rq.lane_source = 'human')
"""


@router.post("/review-queue/auto-accept/run", response_model=AutoAcceptResult)
def run_auto_accept(
    conn: ConnDep,
    principal: PrincipalDep,
    body: AutoAcceptRunBody | None = None,
    limit: int = Query(default=2000, ge=1, le=20000),
    # ⚠️ Défaut à TRUE, contrairement à l'ancienne route. Une passe qui écrit
    # 2 000 décisions ne doit pas être ce qu'on obtient en oubliant un
    # paramètre.
    dry_run: bool = Query(default=True),
    kind: str = Query(default="all"),
) -> AutoAcceptResult:
    """Prévisualise (défaut) ou applique l'auto-acceptation.

    `limit` plafonne ce qui est PRÉVISUALISÉ / ACCEPTÉ — pas ce qui est examiné.
    Les catégories et `n_eligible_total` portent donc sur la file entière : un
    lot borné à 100 dit quand même combien il en reste.
    """
    if kind not in _VALID_KINDS:
        from fastapi import HTTPException
        raise HTTPException(422, f"kind must be one of {_VALID_KINDS}")

    selected_ids: set[str] | None = (
        set(body.review_ids) if body and body.review_ids is not None else None
    )

    sql, args = _SQL, []
    if kind != "all":
        sql += " AND rq.kind = ?"
        args.append(kind)
    sql += " ORDER BY rq.priority ASC, rq.enqueued_at ASC"
    rows = conn.execute(sql, args).fetchall()

    by_category: dict[str, int] = {
        "auto_candidate": 0, "partial": 0, "divergent": 0, "unknown": 0,
    }
    preview: list[AutoAcceptPreviewItem] = []
    accepted = skipped_concurrent = n_eligible = 0
    now_iso = _now_iso()

    for row in rows:
        d = auto_validate_decision(row)
        by_category[d.level] = by_category.get(d.level, 0) + 1
        if d.level != "auto_candidate" or d.decided_eurio_id is None:
            continue
        n_eligible += 1
        # Le plafond porte sur l'ACTION, pas sur l'examen : les compteurs
        # ci-dessus restent complets, donc un lot borné ne ment pas sur le reste.
        if (len(preview) if dry_run else accepted) >= limit:
            continue

        sim = row["top1_country_sim"] if row["top1_country_sim"] is not None \
            else row["top1_sim"]
        spread = row["country_spread"] if row["country_spread"] is not None \
            else row["spread"]

        if dry_run:
            label = " · ".join(
                b for b in (row["t_country_name"],
                            str(row["t_year"]) if row["t_year"] else None,
                            row["t_theme"]) if b
            ) or d.decided_eurio_id
            preview.append(AutoAcceptPreviewItem(
                review_id=row["review_id"],
                image_asset_id=row["image_asset_id"],
                crop_url=f"/sources/{row['source']}/assets/{row['image_asset_id']}/file",
                listing_title=row["listing_title"] or "",
                listing_url=row["listing_url"],
                source=row["source"],
                target_eurio_id=d.decided_eurio_id,
                target_label=label,
                sim=sim, spread=spread,
                face_detected=d.face, reason=d.reason,
            ))
            continue

        # Décoché par l'admin → démote en manual STICKY : il sera re-jugé à la
        # main, et la clause `NOT (manual AND human)` du SELECT l'exclura des
        # passes suivantes. C'est ce qui rend le décochage durable.
        if selected_ids is not None and row["review_id"] not in selected_ids:
            conn.execute(
                "UPDATE review_queue SET lane='manual', lane_source='human' "
                " WHERE id=? AND status='open'",
                (row["review_id"],),
            )
            # Commit ICI, et pas au tour suivant : `db_connection` rend une
            # connexion fraîche par requête, sans autocommit. Sans cette ligne
            # la démotion ne survivait que si une ACCEPTATION la suivait dans
            # la boucle — donc jamais pour le dernier item décoché, et jamais
            # du tout si l'admin décoche tout. Le geste humain se perdait en
            # silence. Attrapé par test_un_item_decoche_est_demote_en_manual_sticky.
            conn.commit()
            continue

        # G7 : pas de défaut `obverse` — l'incertitude s'écrit `unknown`.
        face = d.face or "unknown"
        try:
            conn.execute(
                """
                UPDATE image_assets
                   SET eurio_id = ?, face = ?, resolution_status = 'manual',
                       resolution_confidence = 1.0, training_eligible = 1,
                       resolved_at = ?
                 WHERE id = ? AND resolution_status NOT IN ('manual','rejected')
                """,
                (d.decided_eurio_id, face, now_iso, row["image_asset_id"]),
            )
            meta = json.dumps({
                "sim": sim, "spread": spread,
                "top1_eurio_id": row["top1_country_eurio_id"] or row["top1_eurio_id"],
                "text_verdict": row["vs_target_verdict"],
                "reason": d.reason,
            })
            cur = conn.execute(
                """
                UPDATE review_queue
                   SET status='done', decided_eurio_id=?, decided_face=?,
                       decision_notes=?, decided_at=?, decided_by='auto_dino',
                       decision_engine_version=?, decision_metadata_json=?
                 WHERE id=? AND status='open'
                """,
                (d.decided_eurio_id, face, d.reason, now_iso,
                 _AUTO_DINO_ENGINE_VERSION, meta, row["review_id"]),
            )
            if cur.rowcount != 1:
                conn.rollback()
                skipped_concurrent += 1
                continue
            emit_state_event(
                conn, asset_id=row["image_asset_id"], to_state="resolved",
                actor="auto_dino", reason=d.reason,
                eurio_id=d.decided_eurio_id,
            )
            conn.commit()
            accepted += 1
        except Exception:
            conn.rollback()
            logger.exception("[auto-accept] échec review_id=%s", row["review_id"])

    logger.info(
        "[auto-accept] examinés=%d éligibles=%d accepté=%d concurrent=%d "
        "dry_run=%s par=%s catégories=%s",
        len(rows), n_eligible, accepted, skipped_concurrent, dry_run,
        principal.user_id, by_category,
    )
    return AutoAcceptResult(
        processed=len(rows), accepted=accepted,
        skipped_concurrent=skipped_concurrent, by_category=by_category,
        dry_run=dry_run, preview=preview, n_eligible_total=n_eligible,
    )
