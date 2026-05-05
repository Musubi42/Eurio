"""Contract between the orchestrator and a per-source module.

Every source under `ml/sources/<id>/` provides a `SourceAdapter`
implementation. The orchestrator only knows about this Protocol — it
never imports a concrete adapter directly. See
`docs/sources-refacto/orchestration.md` (4 layers) and `decisions.md`
D-13 (8-step pipeline).

A source adapter is responsible for the *source-specific* steps:
- `discover(query)` : enumerate listings/items matching a query
- `download_raw(item, dest)` : fetch one raw file to disk

All other steps (persist, detect & crop, resolve, enqueue review) are
generic and live in `ml/sources/_base/steps/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

from sources._base.dedup import DiscoverySearchRecord

RecordSearchFn = Callable[[DiscoverySearchRecord], None]


@dataclass
class DiscardedListingRecord:
    """One listing rejected by accept_listing before ingestion.

    Used to trace rejection causes for audit. `run_id` and `source` are
    filled by the discover step; the adapter only fills the listing-level
    fields it has under hand.
    """

    source_ref: str
    target_eurio_id: str | None = None
    reason: str = ""
    title: str | None = None
    raw_payload: dict[str, Any] | None = None


RecordDiscardedFn = Callable[[DiscardedListingRecord], None]


@dataclass(frozen=True)
class SourceQuery:
    """Filter spec passed to `adapter.discover()`.

    Strict named fields cover the common case (cohort scoped by
    country/denomination/year, optional pin to a single eurio_id, or
    a batch of eurio_ids for enrichment sources — see D-19/D-21).
    `extra` is the escape hatch for source-specific filters (eBay
    category, Catawiki auction subtype, ...).

    `target_eurio_id` (singular) and `target_eurio_ids` (plural)
    sont mutuellement exclusifs. Le pluriel signale un batch
    d'enrichissement piloté par freshness queue ; l'orchestrateur
    boucle dessus à l'étape Discover et synthétise une SourceQuery
    par eurio_id avant d'appeler l'adapter.
    """

    source_id: str
    country: str | None = None
    denomination: str | None = None
    year: int | None = None
    target_eurio_id: str | None = None
    target_eurio_ids: tuple[str, ...] | None = None
    limit: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.target_eurio_id and self.target_eurio_ids:
            raise ValueError(
                "SourceQuery: target_eurio_id (singular) and target_eurio_ids "
                "(plural) are mutually exclusive — pick one."
            )
        if self.target_eurio_ids is not None and not isinstance(
            self.target_eurio_ids, tuple
        ):
            # Allow callers to pass list/iterable for ergonomics.
            object.__setattr__(self, "target_eurio_ids", tuple(self.target_eurio_ids))


@dataclass
class DiscoveredItem:
    """One listing surfaced by `adapter.discover()`.

    `source_ref` is the stable per-source identifier (eBay item id,
    Numista coin id, listing URL slug). It feeds the
    `(source, source_ref)` UNIQUE on `source_images` and the
    `discovery_log` UNIQUE — the dedup spine of the pipeline.
    """

    source_ref: str
    source_url: str | None = None
    target_eurio_id: str | None = None
    listing_title: str | None = None
    listing_country: str | None = None
    listing_year: int | None = None
    listing_price: float | None = None
    listing_currency: str = "EUR"
    condition_raw: str | None = None
    seller_id: str | None = None
    is_lot_suspected: bool = False
    raw_payload: dict[str, Any] | None = None


@dataclass
class RawDownloadResult:
    """What `adapter.download_raw()` returns once the file is on disk."""

    storage_path: Path
    bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None
    endpoint_url: str | None = None
    http_status: int | None = None


@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str

    def discover(
        self,
        query: SourceQuery,
        *,
        record_search: RecordSearchFn | None = None,
        record_discarded: RecordDiscardedFn | None = None,
    ) -> Iterable[DiscoveredItem]:
        """Enumerate items for a query. Should be a generator when
        the source paginates — the orchestrator drains it eagerly per
        run.

        `record_search` (optional) is a callback the adapter calls once
        per logical search. Persists query + result counters into
        `discovery_searches` for debug.

        `record_discarded` (optional) is a callback the adapter calls
        once per listing rejected before ingestion (year_mismatch,
        non_eur, noise_title, …). Persists into `discarded_listings`
        for audit (assouplissement futur des règles). Adapters qui ne
        l'appellent pas restent valides — la table est juste vide."""
        ...

    def download_raw(self, item: DiscoveredItem, dest: Path) -> RawDownloadResult:
        """Fetch the raw file to `dest`. `dest` is the canonical path
        chosen by the orchestrator's storage layer; the adapter writes
        bytes there (atomically) and returns metadata."""
        ...
