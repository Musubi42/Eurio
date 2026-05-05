"""Step 5 — Resolve.

V1 policy (kickoff §"2.D"): no auto-name. Every freshly-cropped asset
that isn't already resolved by `auto_phash` (step 4) is marked
`needs_review` so a human can decide. The auto-name path will be
re-introduced in a later chunk once we have real listing data to
calibrate a precision threshold against.

D-26 / phase 3.F : pour les sources avec prix par listing (eBay), on
crée un ``pending_quote`` au resolve **si** :
- ``source_images.is_lot_suspected = false`` (single coin listing)
- ``source_images.listing_price > 0``
- c'est l'image canonique du listing (``raw_payload.image_index == 0``
  pour eBay, NULL ou ``image_index == 0`` pour les autres sources)

Le pending_quote est promu vers ``coin_market_quotes`` au moment de
la review humaine (D-04). Si le listing est un lot, pas de quote
(prix coffret non décomposable, D-15).

Idempotence : on ne crée pas de doublon de pending_quote (1 par
source_image_id max).

Aussi : avance ``discovery_log.pipeline_state`` à 'resolved' pour les
items qui ont au moins un image_asset en statut terminal.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

from sources._base.dedup import (
    PendingQuoteRow,
    insert_pending_quote,
    set_discovery_pipeline_state,
)
from sources._base.run_logger import RunHandle

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = ("auto_name", "auto_phash", "manual", "needs_review", "rejected")


@dataclass
class ResolveResult:
    n_marked_review: int
    n_skipped_already_resolved: int
    n_pending_quotes_added: int


def _is_canonical_image(raw_payload_json: str | None) -> bool:
    """True si c'est l'image principale d'un listing (image_index == 0).

    Convention eBay (cf. ebay/adapter.py) : raw_payload contient
    ``image_index``. Si la clé est absente ou == 0, l'image est traitée
    comme la canonical de son listing. Cette heuristique permet de ne
    créer qu'**une** pending_quote par listing eBay (qui crée N source_images,
    une par photo).
    """
    if not raw_payload_json:
        return True
    try:
        payload = json.loads(raw_payload_json)
    except (json.JSONDecodeError, TypeError):
        return True
    idx = payload.get("image_index")
    return idx is None or idx == 0


# Called by: ml/sources/_base/orchestrator.py (step 6/8 — after detect_crop, writes pending_quotes for canonical images)
def run_resolve(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    source_id: str,
    source_image_ids: dict[str, str],
) -> ResolveResult:
    n_marked = 0
    n_skipped = 0
    n_quotes_added = 0

    for source_ref, sid in source_image_ids.items():
        # Mark image_assets needs_review (sauf déjà résolus).
        rows = conn.execute(
            "SELECT id, resolution_status FROM image_assets WHERE source_image_id = ?",
            (sid,),
        ).fetchall()
        for r in rows:
            if r["resolution_status"] in ("auto_phash", "auto_name", "manual", "rejected"):
                n_skipped += 1
                continue
            conn.execute(
                "UPDATE image_assets SET resolution_status='needs_review' WHERE id=?",
                (r["id"],),
            )
            n_marked += 1

        # D-26 / 3.F : pending_quote pour les single listings non-lot.
        meta = conn.execute(
            """
            SELECT is_lot_suspected, listing_price, listing_currency,
                   condition_raw, raw_payload_json
              FROM source_images WHERE id = ?
            """,
            (sid,),
        ).fetchone()
        if meta and not meta["is_lot_suspected"] and (meta["listing_price"] or 0) > 0:
            if _is_canonical_image(meta["raw_payload_json"]):
                already = conn.execute(
                    "SELECT 1 FROM pending_quotes WHERE source_image_id = ?",
                    (sid,),
                ).fetchone()
                if not already:
                    insert_pending_quote(
                        conn,
                        PendingQuoteRow(
                            source_image_id=sid,
                            source=source_id,
                            price=meta["listing_price"],
                            currency=meta["listing_currency"] or "EUR",
                            condition_raw=meta["condition_raw"],
                        ),
                    )
                    n_quotes_added += 1

        if rows:
            set_discovery_pipeline_state(
                conn, source=source_id, source_ref=source_ref, state="resolved"
            )

    if n_quotes_added:
        run.bump(n_pending_added=n_quotes_added)
    logger.info(
        "[%s] resolve → %d marked needs_review / %d already-resolved / %d pending_quotes",
        source_id, n_marked, n_skipped, n_quotes_added,
    )
    return ResolveResult(
        n_marked_review=n_marked,
        n_skipped_already_resolved=n_skipped,
        n_pending_quotes_added=n_quotes_added,
    )
