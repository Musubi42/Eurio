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


def _reject_crop_terminal(
    conn: sqlite3.Connection,
    *,
    asset_id: str,
    review_id: str,
    quality_reason: str,
    decided_by: str,
    state_reason: str,
    engine_version: str,
    decision_payload: dict,
    target_eurio_id: str | None,
    run_id: str | None,
) -> None:
    """Rejet auto ré-ouvrable d'un crop (pattern partagé consensus / face).

    Même état terminal qu'un reject humain mais estampillé pipeline : apparaît
    dans la grille /rejected et se ré-ouvre via /restore (la row review_queue
    doit exister → l'appelant l'insère d'abord). actor='pipeline' (CHECK
    image_state_events.actor). La row review_queue est marquée `done` avec
    ``decided_by`` (ex. 'consensus', 'pipeline').
    """
    conn.execute(
        """
        UPDATE image_assets
           SET resolution_status = 'rejected',
               training_eligible = 0,
               quality_reason    = ?,
               resolved_at       = datetime('now')
         WHERE id = ?
        """,
        (quality_reason, asset_id),
    )
    conn.execute(
        """
        UPDATE review_queue
           SET status = 'done',
               decided_at = datetime('now'),
               decided_by = ?,
               decision_notes = 'rejected',
               decision_engine_version = ?,
               decision_metadata_json = ?
         WHERE id = ?
        """,
        (decided_by, engine_version, json.dumps(decision_payload), review_id),
    )
    emit_state_event(
        conn, asset_id=asset_id, to_state="rejected",
        actor="pipeline", reason=state_reason,
        target_eurio_id=target_eurio_id, run_id=run_id,
    )


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


def _route_decision_for_source_image(
    conn: sqlite3.Connection,
    *,
    source_image_id: str,
    kind: str,
    is_lot_suspected: bool,
) -> tuple[str, str]:
    """Agrège les statuts des crops en un verdict listing-level pour debug.

    Priorité (du plus saillant au plus discret) :
        needs_review > rejected > auto_* > manual > pending
    """
    rows = conn.execute(
        "SELECT resolution_status, quality_reason "
        "FROM image_assets WHERE source_image_id = ?",
        (source_image_id,),
    ).fetchall()
    if not rows:
        return ("pending", "no_crops_yet")

    statuses = {r["resolution_status"] for r in rows}
    n_crops = len(rows)

    if "needs_review" in statuses:
        decision = "review_lot" if kind == "lot" else "review_single"
        if is_lot_suspected:
            reason = "is_lot_suspected"
        elif n_crops > 1:
            reason = "multi_coin_photo"
        elif kind == "lot":
            reason = "listing_kind_lot"
        else:
            reason = "single_unmatched"
        return (decision, reason)

    if statuses == {"rejected"}:
        # C7 — si TOUS les crops rejetés le sont pour face=revers commun, on le
        # dit explicitement (bucket funnel « revers commun 2€ ») ; sinon rejet
        # générique. Cas typique : listing single-crop montrant le revers.
        reasons = {r["quality_reason"] for r in rows}
        if reasons == {"face_reverse"}:
            return ("rejected", "face_reverse")
        if reasons == {"not_2eur"}:
            return ("rejected", "not_2eur")
        return ("rejected", "all_crops_rejected")

    if statuses <= {"auto_phash", "auto_name", "manual", "rejected"}:
        if "auto_phash" in statuses:
            return ("auto_resolved", "auto_phash_match")
        if "auto_name" in statuses:
            return ("auto_resolved", "auto_name_match")
        if "manual" in statuses:
            return ("auto_resolved", "manual")
        return ("auto_resolved", "auto")

    return ("pending", "mixed_status")


def _kind_for_source_image(
    conn: sqlite3.Connection, *, source_image_id: str, is_lot_suspected: bool
) -> str:
    """D-26 — résout 'single' vs 'lot' pour cette source_image.

    Niveau 1 : titre suggère lot (``is_lot_suspected``, FR/EN) → 'lot'.
    Niveau 2 : ``listing_text_signals.listing_kind == 'lot'`` (classifieur
        multilingue : KMS/Satz/cofre/N valores/≥2 pays/≥3 millésimes/plage
        1 cent–2 euro). 'coffret'/'graded_slab'/'single' = 1 pièce → PAS lot.
        Cf. docs/cohort-pipeline/coin-census-bench.md.
    Niveau 3 : >1 crops détectés sur cette image → 'lot' (multi-coin photo).
    """
    if is_lot_suspected:
        return "lot"
    sig = conn.execute(
        "SELECT listing_kind FROM listing_text_signals WHERE source_image_id = ?",
        (source_image_id,),
    ).fetchone()
    if sig is not None and sig["listing_kind"] == "lot":
        return "lot"
    n_crops = conn.execute(
        "SELECT count(*) AS n FROM image_assets WHERE source_image_id = ?",
        (source_image_id,),
    ).fetchone()["n"]
    return "lot" if (n_crops or 0) > 1 else "single"


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
            # {accept→auto_accept, needs_review→ccproxy/manual, reject→manual}.
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
