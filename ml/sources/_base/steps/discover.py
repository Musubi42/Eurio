"""Step 1 — Discover.

Drains `adapter.discover(query)`, upserts `discovery_log` for every
returned item (dedup layer 1), and returns the materialized list so
downstream steps don't re-iterate the (possibly costly) generator.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from sources._base.adapter import DiscoveredItem, SourceAdapter, SourceQuery
from sources._base.dedup import upsert_discovery_log
from sources._base.query_sig import compute_query_signature
from sources._base.run_logger import RunHandle

logger = logging.getLogger(__name__)


@dataclass
class DiscoverResult:
    items: list[DiscoveredItem]
    query_signature: str
    n_new: int
    n_seen: int


def run_discover(
    adapter: SourceAdapter,
    query: SourceQuery,
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
) -> DiscoverResult:
    signature = compute_query_signature(query)
    items: list[DiscoveredItem] = []
    n_new = 0
    n_seen = 0

    for item in adapter.discover(query):
        items.append(item)
        _, is_new = upsert_discovery_log(
            conn,
            source=adapter.source_id,
            source_ref=item.source_ref,
            query_signature=signature,
            run_id=run.run_id,
        )
        if is_new:
            n_new += 1
        else:
            n_seen += 1

    run.bump(n_calls=1)
    logger.info(
        "[%s] discover sig=%s → %d items (%d new / %d already-seen)",
        adapter.source_id, signature, len(items), n_new, n_seen,
    )
    return DiscoverResult(items=items, query_signature=signature, n_new=n_new, n_seen=n_seen)
