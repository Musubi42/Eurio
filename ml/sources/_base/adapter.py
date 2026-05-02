"""Contract between the orchestrator and a per-source module.

Every source under `ml/sources/<id>/` provides a `SourceAdapter`
implementation. The orchestrator only knows about this Protocol — it
never imports a concrete adapter directly. See
`docs/sources-refacto/orchestration.md` (4 layers) and `decisions.md`
D-13 (6-step pipeline).

A source adapter is responsible for the *source-specific* steps:
- `discover(query)` : enumerate listings/items matching a query
- `download_raw(item, dest)` : fetch one raw file to disk

All other steps (persist, detect & crop, resolve, enqueue review) are
generic and live in `ml/sources/_base/steps/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceQuery:
    """Filter spec passed to `adapter.discover()`.

    Strict named fields cover the common case (cohort scoped by
    country/denomination/year, optional pin to a single eurio_id).
    `extra` is the escape hatch for source-specific filters (eBay
    category, Catawiki auction subtype, ...).
    """

    source_id: str
    country: str | None = None
    denomination: str | None = None
    year: int | None = None
    target_eurio_id: str | None = None
    limit: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


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
    raw_payload: dict[str, Any] | None = None


@dataclass
class RawDownloadResult:
    """What `adapter.download_raw()` returns once the file is on disk."""

    storage_path: Path
    bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None


@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str

    def discover(self, query: SourceQuery) -> Iterable[DiscoveredItem]:
        """Enumerate items for a query. Should be a generator when
        the source paginates — the orchestrator drains it eagerly per
        run."""
        ...

    def download_raw(self, item: DiscoveredItem, dest: Path) -> RawDownloadResult:
        """Fetch the raw file to `dest`. `dest` is the canonical path
        chosen by the orchestrator's storage layer; the adapter writes
        bytes there (atomically) and returns metadata."""
        ...
