"""Step 6 — Enqueue review.

Inserts one `review_queue` row per `image_assets` flagged
`needs_review`. The `UNIQUE (image_asset_id)` on `review_queue` makes
the upsert idempotent: re-running the pipeline on the same data
inserts zero new rows.

Priority (review-queue.md §"Priorisation"):
    100 base
    -30 if the source_image had a target_eurio_id (the fetch was
        targeted, the human just needs to confirm)

D-26 / phase 3.F — kind:
    'lot'    si source_images.is_lot_suspected (titre suggère lot)
             OU si N crops > 1 sur cette source_image (multi-coin photo)
    'single' sinon

Les `lot` rows sont visibles dans /review mais l'UI dédiée
(/review/lots) viendra en V1.5 (parking lot kickoff).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass

from review.review_lanes import DEFAULT_LANE
# Les trois helpers de rejet/routage vivent dans `store/review_routing.py`
# depuis le 2026-08-27 : ils sont du SQL pur, mais ce module-ci tire
# `training` via review_lanes / review.validation, donc l'image lean du VPS ne
# peut pas l'importer — et le canonique est le SEUL writer. Une passe
# corrective y aurait dû réécrire le rejet. Ré-importés sous leurs anciens
# noms privés : il n'y a qu'UNE définition, et tous les appelants tiennent.
from store.review_routing import (
    kind_for_source_image as _kind_for_source_image,
    reject_crop_terminal as _reject_crop_terminal,
    route_decision_for_source_image as _route_decision_for_source_image,
)
from review.validation.consensus import RULE_VERSION, consensus_verdict
from review.validation.experts import collect_signals
from review.validation.persist import upsert_consensus_verdict
from sources._base.run_logger import RunHandle
from store import emit_state_event

logger = logging.getLogger(__name__)

_BASE_PRIORITY = 100
_BONUS_TARGETED = 30
# Estampille `decision_engine_version` d'un rejet auto par la règle de consensus
# (cf. format schema.sql review_queue : 'auto_dino@…', 'human@v1', …).
_CONSENSUS_ENGINE_VERSION = f"consensus@v{RULE_VERSION}"
# Rejet auto par le détecteur de face (C7) : crop = revers commun 2€.
_FACE_ENGINE_VERSION = "face@v1"
_DENOM_ENGINE_VERSION = "denom@v1"


@dataclass
class EnqueueResult:
    n_enqueued: int
    n_skipped_already_queued: int
    n_kind_lot: int
    n_auto_rejected: int = 0  # verdicts consensus 'reject' (ré-ouvrables, C5)


def _compute_priority(*, target_eurio_id: str | None) -> int:
    p = _BASE_PRIORITY
    if target_eurio_id:
        p -= _BONUS_TARGETED
    return p


# Called by: ml/sources/_base/orchestrator.py (step 8/8 — final step; decides single vs lot kind, sets review_queue rows)
def run_enqueue(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    source_id: str,
    source_image_ids: dict[str, str],
) -> EnqueueResult:
    n_enqueued = 0
    n_skipped = 0
    n_lot = 0
    n_rejected = 0

    for sid in source_image_ids.values():
        si_meta = conn.execute(
            "SELECT is_lot_suspected, target_eurio_id FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if si_meta is None:
            continue
        is_lot_suspected = bool(si_meta["is_lot_suspected"])
        kind = _kind_for_source_image(
            conn,
            source_image_id=sid,
            is_lot_suspected=is_lot_suspected,
        )

        rows = conn.execute(
            """
            SELECT a.id AS asset_id,
                   a.candidate_eurio_ids_json,
                   a.face,
                   a.denom
              FROM image_assets a
             WHERE a.source_image_id = ?
               AND a.resolution_status = 'needs_review'
            """,
            (sid,),
        ).fetchall()
        for r in rows:
            already = conn.execute(
                "SELECT 1 FROM review_queue WHERE image_asset_id = ?",
                (r["asset_id"],),
            ).fetchone()
            if already:
                n_skipped += 1
                continue

            priority = _compute_priority(target_eurio_id=si_meta["target_eurio_id"])
            candidates = r["candidate_eurio_ids_json"]

            # C7 — Face : un crop du REVERS commun 2€ n'est pas identifiable
            # (l'avers national est ce qu'on matche). Rejet terminal ré-ouvrable
            # AVANT le consensus (sinon dino/texte produiraient un verdict
            # contradictoire sur une face non pertinente). La garde `already`
            # ci-dessus rend un /restore humain sticky → pas de re-rejet.
            if r["face"] == "reverse":
                review_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO review_queue (
                      id, image_asset_id, priority, candidate_eurio_ids_json, kind, lane
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (review_id, r["asset_id"], priority, candidates, kind, DEFAULT_LANE),
                )
                _reject_crop_terminal(
                    conn, asset_id=r["asset_id"], review_id=review_id,
                    quality_reason="face_reverse",
                    decided_by="pipeline",
                    state_reason="face_reverse",
                    engine_version=_FACE_ENGINE_VERSION,
                    decision_payload={"reason": "face_reverse"},
                    target_eurio_id=si_meta["target_eurio_id"], run_id=run.run_id,
                )
                n_rejected += 1
                continue

            # C7 pilier 2 — Dénomination : un crop qui n'est PAS un 2€ (cent,
            # médaille, mire, 1€, set) ne part pas en identité 2€. Rejet terminal
            # ré-ouvrable, per-crop (jamais la photo entière → les avers 2€ d'un
            # lot mixte restent en review). Même pattern que face_reverse.
            if r["denom"] == "not_2eur":
                review_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO review_queue (
                      id, image_asset_id, priority, candidate_eurio_ids_json, kind, lane
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (review_id, r["asset_id"], priority, candidates, kind, DEFAULT_LANE),
                )
                _reject_crop_terminal(
                    conn, asset_id=r["asset_id"], review_id=review_id,
                    quality_reason="not_2eur",
                    decided_by="pipeline",
                    state_reason="not_2eur",
                    engine_version=_DENOM_ENGINE_VERSION,
                    decision_payload={"reason": "not_2eur"},
                    target_eurio_id=si_meta["target_eurio_id"], run_id=run.run_id,
                )
                n_rejected += 1
                continue

            # Lane figée à l'enqueue par la RÈGLE DE CONSENSUS (C3) — source de
            # vérité unique du routage : agrège text + dino + crop_quality (tous
            # disponibles ici : text au step 2.5, dino au 5.5, crop si mesuré) en
            # {accept→auto_accept, needs_review→manual, reject→manual}.
            # Remplace l'ancien compute_lane (branche contradict→divergent). Le
            # verdict est aussi PERSISTÉ (consensus_verdicts) pour audit/replay.
            # Pas de signal exploitable (asset non résolu) ⇒ lane 'manual'.
            signals = collect_signals(conn, r["asset_id"])
            cv = consensus_verdict(signals)
            lane = cv.lane if signals else DEFAULT_LANE
            if signals:
                upsert_consensus_verdict(
                    conn, r["asset_id"], signals=signals, verdict=cv, commit=False,
                )
            review_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO review_queue (
                  id, image_asset_id, priority, candidate_eurio_ids_json, kind, lane
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (review_id, r["asset_id"], priority, candidates, kind, lane),
            )

            # C5 — un verdict consensus `reject` (dual_contradict) devient un
            # REJET ré-ouvrable, pas un item de queue à trier ni une suppression :
            # même état terminal qu'un reject humain (cf. reject_review) mais
            # estampillé `consensus`. Il apparaît dans la grille /rejected et se
            # ré-ouvre via /restore (qui exige une row review_queue → on l'insère
            # d'abord). La garde `already` ci-dessus rend le restore humain sticky.
            if signals and cv.outcome == "reject":
                _reject_crop_terminal(
                    conn, asset_id=r["asset_id"], review_id=review_id,
                    quality_reason="consensus_reject",
                    decided_by="consensus",
                    state_reason=f"consensus_{cv.rule}",
                    engine_version=_CONSENSUS_ENGINE_VERSION,
                    decision_payload={"reason": cv.reason, "rule": cv.rule},
                    target_eurio_id=si_meta["target_eurio_id"], run_id=run.run_id,
                )
                n_rejected += 1
                continue

            # Modèle d'état : crop entre en file → 'queued' (from_state résolu
            # depuis l'état courant : 'detected' au scrape normal, 'orphaned'
            # pour un crop recroppé/réparé, NULL si jamais journalisé).
            emit_state_event(
                conn, asset_id=r["asset_id"], to_state="queued", actor="pipeline",
                reason="enqueued", target_eurio_id=si_meta["target_eurio_id"],
                run_id=run.run_id,
            )
            n_enqueued += 1
            if kind == "lot":
                n_lot += 1

        decision, reason = _route_decision_for_source_image(
            conn, source_image_id=sid, kind=kind, is_lot_suspected=is_lot_suspected,
        )
        conn.execute(
            "UPDATE source_images SET route_decision=?, route_reason=? WHERE id=?",
            (decision, reason, sid),
        )

    run.bump(n_review_enqueued=n_enqueued)
    logger.info(
        "[%s] enqueue → %d new (%d lot / %d single) / %d auto-rejected / %d already-queued",
        source_id, n_enqueued, n_lot, n_enqueued - n_lot, n_rejected, n_skipped,
    )
    return EnqueueResult(
        n_enqueued=n_enqueued, n_skipped_already_queued=n_skipped, n_kind_lot=n_lot,
        n_auto_rejected=n_rejected,
    )
