"""Step 1 — Discover.

Drains `adapter.discover(query)`, upserts `discovery_log` for every
returned item (dedup layer 1), and returns the materialized list so
downstream steps don't re-iterate the (possibly costly) generator.

Quand `query.target_eurio_ids` (pluriel, D-19/D-21) est rempli, la
boucle d'itération vit ici : on synthétise une SourceQuery par
eurio_id et on appelle `adapter.discover()` pour chacune. L'adapter
ne voit jamais qu'une query mono-eurio_id à la fois — il n'a pas à
gérer le batching. Le run agrège tous les items dans la même
DiscoverResult.
"""

from __future__ import annotations

import dataclasses
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


def _iter_subqueries(query: SourceQuery) -> list[SourceQuery]:
    """Develop a batch query into per-eurio_id sub-queries.

    Returns `[query]` if no batching is needed.
    """
    if not query.target_eurio_ids:
        return [query]
    base = dataclasses.replace(query, target_eurio_ids=None)
    return [dataclasses.replace(base, target_eurio_id=eid) for eid in query.target_eurio_ids]


def run_discover(
    adapter: SourceAdapter,
    query: SourceQuery,
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
) -> DiscoverResult:
    # Signature au niveau du batch entier (stable et O(1) par item via dedup C1).
    signature = compute_query_signature(query)

    items: list[DiscoveredItem] = []
    n_new = 0
    n_seen = 0

    subqueries = _iter_subqueries(query)
    for subq in subqueries:
        for item in adapter.discover(subq):
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
        "[%s] discover sig=%s subqueries=%d → %d items (%d new / %d already-seen)",
        adapter.source_id, signature, len(subqueries), len(items), n_new, n_seen,
    )
    return DiscoverResult(items=items, query_signature=signature, n_new=n_new, n_seen=n_seen)
