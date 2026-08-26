"""Rejet terminal d'un crop et routage listing-level — write-half SQL-pure.

POURQUOI CES TROIS FONCTIONS VIVENT ICI ET PLUS DANS `steps/enqueue`
--------------------------------------------------------------------
Elles ne sont que du SQL et un événement : aucune dépendance à `training`, à
`cv2` ni à `torch`. Mais elles habitaient `sources/_base/steps/enqueue`, qui
importe `review.review_lanes` et `review.validation.*` — lesquels tirent
`training.foundation`. Conséquence mesurée le 2026-08-27 : dans l'image lean du
VPS, `import sources._base.steps.enqueue` lève
`ModuleNotFoundError: No module named 'training'`.

Or le canonique est le SEUL writer (Direction A). Une passe corrective qui doit
rejeter des crops **ne pouvait donc pas réutiliser ces helpers** : elle était
condamnée à réécrire le rejet en SQL, c'est-à-dire à en créer une seconde copie
libre de diverger. C'est le même piège que la règle de face, et la même sortie :
la logique descend dans un module que les deux côtés atteignent.

`enqueue` les ré-importe sous ses anciens noms privés — il n'y a **qu'une**
définition, et tous les appelants historiques continuent de marcher.
"""

from __future__ import annotations

import json
import sqlite3

from store.events import emit_state_event


def reject_crop_terminal(
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
    """Rejet auto RÉ-OUVRABLE d'un crop (pattern partagé consensus / face).

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


def route_decision_for_source_image(
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


def kind_for_source_image(
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
