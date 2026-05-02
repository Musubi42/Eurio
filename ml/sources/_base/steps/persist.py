"""Step 2 — Persist raw.

Upserts one `source_images` row per discovered item (dedup layer 2,
the `(source, source_ref)` UNIQUE) and advances the matching
`discovery_log.pipeline_state` to 'persisted'. No file I/O — the
download itself happens in step 3.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from sources._base.adapter import DiscoveredItem
from sources._base.dedup import (
    SourceImageRow,
    set_discovery_pipeline_state,
    upsert_source_image,
)
from sources._base.run_logger import RunHandle
from sources._base.sources_registry import get as get_source_spec

logger = logging.getLogger(__name__)


@dataclass
class PersistResult:
    n_added: int
    n_updated: int
    source_image_ids: dict[str, str]   # source_ref -> source_images.id


def run_persist(
    items: list[DiscoveredItem],
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    source_id: str,
) -> PersistResult:
    spec = get_source_spec(source_id)
    n_added = 0
    n_updated = 0
    ids: dict[str, str] = {}

    for item in items:
        # Dedup-aware count: pre-check existence so we know whether
        # this row was inserted or merely refreshed.
        existing = conn.execute(
            "SELECT id FROM source_images WHERE source = ? AND source_ref = ?",
            (source_id, item.source_ref),
        ).fetchone()
        is_new = existing is None

        sid = upsert_source_image(
            conn,
            SourceImageRow(
                source=source_id,
                source_ref=item.source_ref,
                source_url=item.source_url,
                target_eurio_id=item.target_eurio_id,
                listing_title=item.listing_title,
                listing_country=item.listing_country,
                listing_year=item.listing_year,
                listing_price=item.listing_price,
                listing_currency=item.listing_currency,
                condition_raw=item.condition_raw,
                seller_id=item.seller_id,
                license=spec.default_license,
                redistributable=spec.redistributable,
                raw_payload=item.raw_payload,
                run_id=run.run_id,
            ),
        )
        ids[item.source_ref] = sid

        set_discovery_pipeline_state(
            conn, source=source_id, source_ref=item.source_ref, state="persisted"
        )

        if is_new:
            n_added += 1
        else:
            n_updated += 1

    run.bump(n_raws_added=n_added)
    logger.info(
        "[%s] persist → %d added / %d refreshed", source_id, n_added, n_updated,
    )
    return PersistResult(n_added=n_added, n_updated=n_updated, source_image_ids=ids)
