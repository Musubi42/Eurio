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
    # eBay multi-mkt (B4) : marketplace qui a yieldé puis rejeté ce listing.
    # None pour les sources sans notion de marketplace (mock, numista, ...).
    marketplace: str | None = None


RecordDiscardedFn = Callable[[DiscardedListingRecord], None]


@dataclass(frozen=True)
class DiscoveryGroup:
    """A discovery scope — the natural unit of one eBay search.

    Two ``kind`` :

    - ``"commemorative"`` (défaut) : ``(dénomination, pays, année)``. La
      requête est fonction pure des trois axes ; deux commémos-sœurs
      même pays/année partageraient une recherche byte-identique. Le
      groupe fanne sur K eurio_ids, attribués post-hoc par le theme-match.
    - ``"standard"`` : ``(dénomination, pays)`` — ``year`` est ``None``.
      Un standard n'a pas de thème par année : sa face nationale est
      identique sur toute une *ère de design*, et une seule recherche
      large « 2 euro {pays} » couvre toutes les ères. L'attribution à une
      ère se fait par appartenance de plage d'années
      (``sources/ebay/standards.py``), pas par theme-match.
    """

    denomination: float
    country: str
    year: int | None = None
    kind: str = "commemorative"

    def __post_init__(self) -> None:
        if self.kind == "commemorative" and self.year is None:
            raise ValueError(
                "DiscoveryGroup commemorative requiert une année (year=None "
                "réservé aux standards)."
            )
        if self.kind == "standard" and self.year is not None:
            raise ValueError(
                "DiscoveryGroup standard ne porte pas d'année "
                f"(year={self.year!r}) — le design couvre toutes les années."
            )
        if self.kind not in ("commemorative", "standard"):
            raise ValueError(f"DiscoveryGroup.kind invalide: {self.kind!r}")


@dataclass(frozen=True)
class SourceQuery:
    """Filter spec passed to `adapter.discover()`.

    Strict named fields cover the common case (cohort scoped by
    country/denomination/year, optional pin to a single eurio_id, or
    a batch of eurio_ids for enrichment sources — see D-19/D-21).
    `extra` is the escape hatch for source-specific filters (eBay
    category, Catawiki auction subtype, ...).

    Two discovery modes, mutually exclusive per the singular/plural
    pattern below:
    - `discovery_group` / `discovery_groups` : group-scoped discovery
      (eBay — one search per (denom, country, year), listings attributed
      to coins post-hoc by the theme matcher).
    - `target_eurio_id` / `target_eurio_ids` : per-coin discovery
      (generic enrichment sources / mock). For eBay a singular
      `target_eurio_id` is still accepted and resolved to *its* group.

    The plural in each pair signals a batch; the orchestrator loops over
    it at the Discover step and synthesises one mono-scoped SourceQuery
    before calling the adapter.
    """

    source_id: str
    country: str | None = None
    denomination: str | None = None
    year: int | None = None
    target_eurio_id: str | None = None
    target_eurio_ids: tuple[str, ...] | None = None
    discovery_group: DiscoveryGroup | None = None
    discovery_groups: tuple[DiscoveryGroup, ...] | None = None
    limit: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.target_eurio_id and self.target_eurio_ids:
            raise ValueError(
                "SourceQuery: target_eurio_id (singular) and target_eurio_ids "
                "(plural) are mutually exclusive — pick one."
            )
        if self.discovery_group and self.discovery_groups:
            raise ValueError(
                "SourceQuery: discovery_group (singular) and discovery_groups "
                "(plural) are mutually exclusive — pick one."
            )
        if self.target_eurio_ids is not None and not isinstance(
            self.target_eurio_ids, tuple
        ):
            # Allow callers to pass list/iterable for ergonomics.
            object.__setattr__(self, "target_eurio_ids", tuple(self.target_eurio_ids))
        if self.discovery_groups is not None and not isinstance(
            self.discovery_groups, tuple
        ):
            object.__setattr__(self, "discovery_groups", tuple(self.discovery_groups))


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
    # eBay multi-mkt (B4). `marketplace` = mkt qui a yieldé le listing en
    # premier dans l'ordre primary→global. `marketplace_found` = liste
    # complète après merge en RAM. None pour les sources sans notion de
    # marketplace.
    marketplace: str | None = None
    marketplace_found: tuple[str, ...] | None = None


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
