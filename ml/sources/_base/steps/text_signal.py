"""Step 2.5 — Extract text signals from listing titles + reject contradicts.

Runs ``ml/sources/text_signals/extractor.extract_listing_text_signals``
on each ``source_images.listing_title`` produced by step 2 (``persist``)
puis ``compare_to_target`` quand le ``target_eurio_id`` est connu
(chunk 6 auto-validation). Persiste 1 row par ``source_image_id`` dans
``listing_text_signals`` avec le verdict.

**Décision pipeline** (chunk 6.c) : sur verdict ``contradict``, le step
écrit dans ``discarded_listings(reason='text_contradict_<axe>')`` et
pose ``source_images.route_decision='rejected_text'``. Le step
``download`` saute ensuite ces sources_images — le crop n'est pas
téléchargé. Audit : le panel front "Listings rejetés pré-ingestion"
affiche les nouveaux rejets sans nouveau code.

Idempotence : skip un source_image si une row existe déjà pour la même
``extractor_version``. Passer ``force=True`` pour recompute (auquel cas
les rejets ``text_contradict_*`` du même source_ref sont nettoyés et
ré-écrits).

Placé entre ``persist`` et ``download`` dans la pipeline : le titre est
disponible dès que le source_image existe en DB, et le filtre dur
économise download + detect_crop pour les listings clairement
contradictoires.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass

from sources._base.dedup import record_discarded_listing
from sources._base.run_logger import RunHandle
from sources.text_signals import (
    compare_to_target,
    extract_listing_text_signals,
    load_target_identity,
)
from store import ListingTextSignalsRow

logger = logging.getLogger(__name__)

# v2 (chunk C2) : ajoute listing_kind + condition_normalized. Le bump
# force la ré-extraction des rows v1 (l'idempotence est clé sur version).
EXTRACTOR_VERSION = "v2"


@dataclass
class TextSignalResult:
    n_extracted: int
    n_skipped_existing: int
    n_skipped_empty_title: int
    n_errors: int
    n_rejected_contradict: int = 0


# Called by: ml/sources/_base/orchestrator.py (step 3/8 — after persist, before download)
#            ml/scripts/backfill_text_signals.py (standalone re-run on existing source_images)
def run_text_signal_extract(
    *,
    conn: sqlite3.Connection,
    run: RunHandle | None,
    source_image_ids: dict[str, str],
    force: bool = False,
    store=None,
) -> TextSignalResult:
    """Extract & persist text signals for the given source_image_ids.

    Args:
        conn: SQLite connection. Used for SELECTs and (en l'absence de
              store) pour les writes via SQL direct.
        run: RunHandle for counters. None acceptable (path backfill).
        source_image_ids: ``{source_ref: source_image_id}`` map produced
              by the ``persist`` step.
        force: when True, recompute even if a row exists for the same
               extractor_version.
        store: Store optionnel — si fourni, on persiste via
               ``store.upsert_listing_text_signals`` (write lock géré).
               Sinon on écrit en SQL direct sur la conn (path test /
               backfill avec raw connection).
    """
    if not source_image_ids:
        return TextSignalResult(0, 0, 0, 0)

    n_extracted = 0
    n_skipped_existing = 0
    n_skipped_empty = 0
    n_errors = 0
    n_rejected_contradict = 0
    rows: list[ListingTextSignalsRow] = []
    # Pending rejet writes : (source_ref, sid, target_eurio_id, axe, title, payload)
    pending_rejects: list[tuple[str, str, str | None, str, str | None, dict]] = []
    run_id_for_reject = run.run_id if run is not None else None
    source_id_for_reject: str | None = None

    t0 = time.monotonic()
    for source_ref, sid in source_image_ids.items():
        # Garde-fou correction manuelle (chunk C4) : une row marquée
        # extractor_version='manual' a été corrigée à la main dans la
        # review — on ne la ré-extrait jamais, même en force.
        manual = conn.execute(
            "SELECT 1 FROM listing_text_signals "
            "WHERE source_image_id = ? AND extractor_version = 'manual'",
            (sid,),
        ).fetchone()
        if manual:
            n_skipped_existing += 1
            continue

        # Idempotence
        if not force:
            existing = conn.execute(
                "SELECT 1 FROM listing_text_signals "
                "WHERE source_image_id = ? AND extractor_version = ?",
                (sid, EXTRACTOR_VERSION),
            ).fetchone()
            if existing:
                n_skipped_existing += 1
                continue

        title_row = conn.execute(
            "SELECT listing_title, target_eurio_id, source "
            "  FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if title_row is None:
            n_errors += 1
            logger.warning(
                "[text_signal] source_image not found id=%s ref=%s",
                sid, source_ref,
            )
            continue

        title = title_row["listing_title"] or ""
        target_eurio_id = title_row["target_eurio_id"]
        if source_id_for_reject is None:
            source_id_for_reject = title_row["source"]
        if not title.strip():
            # On persiste quand même un row "empty" pour éviter de
            # ré-extraire à chaque run, mais on compte séparément.
            n_skipped_empty += 1

        try:
            sig = extract_listing_text_signals(title)
        except Exception as exc:  # noqa: BLE001 — keep the run going
            logger.exception(
                "[text_signal] extraction failed sid=%s ref=%s: %s",
                sid, source_ref, exc,
            )
            n_errors += 1
            continue

        # Chunk 6 — compute verdict vs target (and persist). Le filtre
        # dur (chunk 6.c) écrit dans discarded_listings + pose
        # route_decision='rejected_text' uniquement sur ``contradict``.
        # Skip silently quand le target n'est pas connu (pas de
        # target_eurio_id, ou absent de coins).
        verdict: str | None = None
        contradictions: list[str] = []
        convergences: list[str] = []
        if target_eurio_id:
            target = load_target_identity(conn, target_eurio_id)
            if target is not None:
                cmp_result = compare_to_target(sig, target)
                verdict = cmp_result.verdict
                contradictions = list(cmp_result.contradictions)
                convergences = list(cmp_result.convergences)
                if verdict == "contradict":
                    pending_rejects.append((
                        source_ref, sid, target_eurio_id,
                        contradictions[0],
                        title or None,
                        {
                            "contradictions": contradictions,
                            "convergences": convergences,
                            "signals": {
                                "countries": sorted(sig.countries),
                                "years": sorted(sig.years),
                                "denominations": sorted(sig.denominations),
                                "matched": {k: list(v) for k, v in sig.matched.items()},
                            },
                            "target": {
                                "country": target.country,
                                "year": target.year,
                                "face_value": target.face_value,
                            },
                        },
                    ))

        rows.append(ListingTextSignalsRow(
            source_image_id=sid,
            extractor_version=EXTRACTOR_VERSION,
            countries=sorted(sig.countries),
            years=sorted(sig.years),
            denominations=sorted(sig.denominations),
            theme_tokens=list(sig.theme_tokens),
            rejected_markers=list(sig.rejected_markers),
            is_lot=sig.is_lot,
            coverage=sig.coverage,
            matched={k: list(v) for k, v in sig.matched.items()},
            vs_target_verdict=verdict,
            contradictions=contradictions,
            convergences=convergences,
            listing_kind=sig.listing_kind,
            listing_kind_confidence=sig.listing_kind_confidence,
            condition_normalized=sig.condition,
            condition_confidence=sig.condition_confidence,
        ))
        n_extracted += 1

    if rows:
        if store is not None:
            store.upsert_listing_text_signals(rows)
        else:
            _flush_rows_direct(conn, rows)

    # Filtre dur (chunk 6.c) — applique les rejets contradict après le
    # flush des signaux pour que la row listing_text_signals existe déjà
    # quand le panel front la consulte.
    n_rejected_contradict = _apply_text_contradict_rejections(
        conn,
        pending_rejects=pending_rejects,
        run_id=run_id_for_reject,
        source_id=source_id_for_reject,
    )

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "[text_signal] extracted=%d skipped_existing=%d skipped_empty=%d "
        "errors=%d rejected_contradict=%d duration_ms=%d",
        n_extracted, n_skipped_existing, n_skipped_empty, n_errors,
        n_rejected_contradict, duration_ms,
    )
    return TextSignalResult(
        n_extracted=n_extracted,
        n_skipped_existing=n_skipped_existing,
        n_skipped_empty_title=n_skipped_empty,
        n_errors=n_errors,
        n_rejected_contradict=n_rejected_contradict,
    )


def _apply_text_contradict_rejections(
    conn,
    *,
    pending_rejects: list,
    run_id: str | None,
    source_id: str | None,
) -> int:
    """Écrit les rejets ``text_contradict_<axe>`` dans discarded_listings
    et pose ``route_decision='rejected_text'`` sur les source_images
    correspondants. Idempotent : nettoie d'abord les rows
    ``text_contradict_*`` pré-existantes pour le même (source, source_ref)
    avant d'écrire les nouvelles, pour ne pas dupliquer sur force=True.
    """
    if not pending_rejects or source_id is None:
        return 0

    n_rejected = 0
    for source_ref, sid, target_eurio_id, axe, title, payload in pending_rejects:
        # Cleanup stale rejects (force-recompute path).
        conn.execute(
            """
            DELETE FROM discarded_listings
             WHERE source = ? AND source_ref = ?
               AND reason LIKE 'text_contradict_%'
            """,
            (source_id, source_ref),
        )
        record_discarded_listing(
            conn,
            run_id=run_id,
            source=source_id,
            source_ref=source_ref,
            target_eurio_id=target_eurio_id,
            reason=f"text_contradict_{axe}",
            title=title,
            raw_payload=payload,
        )
        # Marque le source_image comme rejeté pour que ``download`` saute.
        conn.execute(
            """
            UPDATE source_images
               SET route_decision = 'rejected_text',
                   route_reason   = ?
             WHERE id = ?
            """,
            (axe, sid),
        )
        n_rejected += 1
    conn.commit()
    return n_rejected


def _flush_rows_direct(
    conn: sqlite3.Connection,
    rows: list[ListingTextSignalsRow],
) -> None:
    """Direct SQL path when no Store is available (tests, raw conn)."""
    import json as _json
    conn.executemany(
        """
        INSERT INTO listing_text_signals (
          source_image_id, extractor_version,
          countries_json, years_json, denominations_json,
          theme_tokens_json, rejected_markers_json,
          is_lot, coverage, matched_json,
          vs_target_verdict, contradictions_json, convergences_json,
          listing_kind, listing_kind_confidence,
          condition_normalized, condition_confidence,
          computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(source_image_id) DO UPDATE SET
          extractor_version     = excluded.extractor_version,
          countries_json        = excluded.countries_json,
          years_json            = excluded.years_json,
          denominations_json    = excluded.denominations_json,
          theme_tokens_json     = excluded.theme_tokens_json,
          rejected_markers_json = excluded.rejected_markers_json,
          is_lot                = excluded.is_lot,
          coverage              = excluded.coverage,
          matched_json          = excluded.matched_json,
          vs_target_verdict     = excluded.vs_target_verdict,
          contradictions_json   = excluded.contradictions_json,
          convergences_json     = excluded.convergences_json,
          listing_kind            = excluded.listing_kind,
          listing_kind_confidence = excluded.listing_kind_confidence,
          condition_normalized    = excluded.condition_normalized,
          condition_confidence    = excluded.condition_confidence,
          computed_at           = datetime('now')
        """,
        [
            (
                r.source_image_id,
                r.extractor_version,
                _json.dumps(r.countries),
                _json.dumps(r.years),
                _json.dumps(r.denominations),
                _json.dumps(r.theme_tokens),
                _json.dumps(r.rejected_markers),
                int(r.is_lot),
                r.coverage,
                _json.dumps(r.matched),
                r.vs_target_verdict,
                _json.dumps(r.contradictions),
                _json.dumps(r.convergences),
                r.listing_kind,
                r.listing_kind_confidence,
                r.condition_normalized,
                r.condition_confidence,
            )
            for r in rows
        ],
    )
    conn.commit()
