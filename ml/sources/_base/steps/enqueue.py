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

import logging
import sqlite3
import uuid
from dataclasses import dataclass

from foundation.review_lanes import compute_lane
from sources._base.run_logger import RunHandle

logger = logging.getLogger(__name__)

_BASE_PRIORITY = 100
_BONUS_TARGETED = 30


@dataclass
class EnqueueResult:
    n_enqueued: int
    n_skipped_already_queued: int
    n_kind_lot: int


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
        "SELECT resolution_status FROM image_assets WHERE source_image_id = ?",
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
                   a.candidate_eurio_ids_json
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
            # Lane persistée figée à l'enqueue (règle centralisée review_lanes).
            # Dino tourne au step 5.5 (avant enqueue) → la prédiction est dispo ;
            # absente ⇒ verdict 'unknown' ⇒ lane 'manual' (filet de sécurité).
            _verdict, lane = compute_lane(conn, r["asset_id"])
            conn.execute(
                """
                INSERT INTO review_queue (
                  id, image_asset_id, priority, candidate_eurio_ids_json, kind, lane
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, r["asset_id"], priority, candidates, kind, lane),
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
        "[%s] enqueue → %d new (%d lot / %d single) / %d already-queued",
        source_id, n_enqueued, n_lot, n_enqueued - n_lot, n_skipped,
    )
    return EnqueueResult(
        n_enqueued=n_enqueued, n_skipped_already_queued=n_skipped, n_kind_lot=n_lot,
    )
