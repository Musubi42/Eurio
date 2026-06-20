"""Pydantic schemas du domaine `sources`.

Familles :
- *Filter / *Query : payloads de requête (query strings)
- *Response / *Detail : payloads de réponse
- objets domaine internes (`SourceRun`, `FunnelStep`, etc.)
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ─── Sources status / list ──────────────────────────────────────────────────

class CliHint(BaseModel):
    kind: str
    title: str
    command: str
    description: str
    expected_outcome: str


class QuotaPerKey(BaseModel):
    slot: int
    key_hash: str
    calls: int
    exhausted: bool


class SourceQuota(BaseModel):
    window: str  # 'monthly' | 'daily'
    period: str
    limit: int
    calls: int
    remaining: int
    pct_used: float
    exhausted: bool
    per_key: list[QuotaPerKey] | None = None


class SourceDelta(BaseModel):
    n_stable: int | None
    n_new: int
    n_dropped: int
    delta_p50_median_pct: float | None
    delta_p50_p10_pct: float | None
    delta_p50_p90_pct: float | None
    swing_warning: bool


class SourceTemporal(BaseModel):
    last_run_at: str | None
    last_run_kind: str | None
    days_since_last_run: int | None
    expected_cadence_days: int
    overdue: bool
    delta: SourceDelta | None


class SourceCoverage(BaseModel):
    enriched: int
    total_target: int
    pct: float
    unit: str


class SourceStatus(BaseModel):
    id: str
    label: str
    subtitle: str
    kind: str  # 'api' | 'scrape'
    quota_group: str | None
    health: str  # 'healthy' | 'warning' | 'error'
    health_reason: str | None
    quota: SourceQuota | None
    temporal: SourceTemporal
    coverage: SourceCoverage
    cli_hints: list[CliHint]
    is_future: bool | None = None
    future_note: str | None = None


class SourcesStatusResponse(BaseModel):
    sources: list[SourceStatus]
    quota_groups: dict[str, SourceQuota]


# ─── Source detail (header) ─────────────────────────────────────────────────

class LastRunSummary(BaseModel):
    n_images: int
    n_quotes: int
    n_calls: int
    duration_s: int
    status: str  # 'success' | 'partial' | 'failed'


class SourceDetailHeader(BaseModel):
    id: str
    label: str
    subtitle: str
    health: str
    health_reason: str | None
    expected_cadence_days: int
    last_run_at: str | None
    last_run_summary: LastRunSummary | None
    coverage_pct: float
    coverage_label: str


# ─── Run snapshot / list ────────────────────────────────────────────────────

class RunSnapshot(BaseModel):
    id: str
    source: str
    kind: str  # 'run' | 'dry'
    status: str  # 'success' | 'partial' | 'failed' | 'running'
    current_step: str | None
    started_at: str
    ended_at: str | None
    duration_s: float | None
    n_calls: int
    n_raws_added: int
    n_crops_added: int
    n_quotes_added: int
    n_pending_added: int
    n_auto_resolved: int
    n_review_enqueued: int
    n_errors: int
    n_downloads_failed: int
    filters: dict[str, Any]
    error_summary: str | None
    log_path: str | None


class SourceRunListItem(BaseModel):
    id: str
    started_at: str
    kind: str
    duration_s: float
    n_calls: int
    n_images: int
    n_quotes: int
    n_errors: int
    status: str
    filters: dict[str, Any]
    log_path: str


# ─── Funnel ─────────────────────────────────────────────────────────────────

class FunnelStep(BaseModel):
    name: str
    status: str  # 'done' | 'running' | 'pending' | 'failed'


class DiscardedReasonGroup(BaseModel):
    reason: str
    count: int


class RunFunnel(BaseModel):
    run_id: str
    source_id: str
    status: str
    current_step: str | None
    duration_s: float | None
    n_errors: int
    error_summary: str | None
    steps: list[FunnelStep]
    n_searches: int
    n_summaries: int
    n_after_groups: int
    n_kept: int
    n_images: int
    n_cropped: int
    n_zero_crops: int
    n_crop_pending: int
    n_discarded: int
    discards: list[DiscardedReasonGroup]
    n_review_enqueued: int
    n_pending_quotes: int
    n_quotes: int


# ─── Breakdown ──────────────────────────────────────────────────────────────

class RunBreakdownEntry(BaseModel):
    eurio_id: str
    was_targeted: bool
    n_listings: int
    n_crops_searched: int
    n_searched_auto: int
    n_searched_review_single: int
    n_searched_review_lot: int
    n_searched_pending: int
    n_searched_rejected: int
    n_attributed_from_other: int
    via_lot: bool
    n_quotes: int
    marketplaces: list[str]


class RunBreakdown(BaseModel):
    run_id: str
    source_id: str
    started_at: str
    status: str
    filters: dict[str, Any]
    per_eurio: list[RunBreakdownEntry]


# ─── Listings ───────────────────────────────────────────────────────────────

class ListingCropAsset(BaseModel):
    asset_id: str
    crop_index: int
    resolution_status: str | None
    eurio_id: str | None
    review_id: str | None
    review_kind: str | None  # 'lot' | 'single'


class ListingDetail(BaseModel):
    source_image_id: str
    source_ref: str
    source_url: str | None
    target_eurio_id: str | None
    listing_title: str | None
    listing_country: str | None
    listing_year: int | None
    listing_price: float | None
    listing_currency: str | None
    seller_id: str | None
    is_lot_suspected: bool
    fetched_at: str | None
    download_endpoint: str | None
    download_status: str | None
    download_http_status: int | None
    download_error: str | None
    crop_status: str | None
    crop_error: str | None
    n_crops_detected: int | None
    route_decision: str | None
    route_reason: str | None
    crops: list[ListingCropAsset]


class RunListings(BaseModel):
    run_id: str
    source_id: str
    listings: list[ListingDetail]


# ─── Searches ───────────────────────────────────────────────────────────────

class DiscoverySearchItem(BaseModel):
    id: str
    target_eurio_id: str | None
    endpoint: str | None
    query_q: str | None
    query_filters: dict[str, Any] | None
    status: str  # 'success' | 'empty' | 'failed'
    http_status: int | None
    n_summaries: int | None
    n_after_groups: int | None
    n_raw_results: int | None
    n_kept_results: int | None
    duration_ms: int | None
    error: str | None
    marketplace: str | None
    browse_url: str | None
    created_at: str


class RunSearches(BaseModel):
    run_id: str
    source_id: str
    searches: list[DiscoverySearchItem]


# ─── Discarded ──────────────────────────────────────────────────────────────

class DiscardedListing(BaseModel):
    id: str
    source_ref: str
    target_eurio_id: str | None
    reason: str
    title: str | None
    item_id: str | None
    item_web_url: str | None
    price: float | None
    currency: str | None
    raw_payload: dict[str, Any] | None
    created_at: str


class RunDiscarded(BaseModel):
    run_id: str
    source_id: str
    total: int
    by_reason: list[DiscardedReasonGroup]
    listings: list[DiscardedListing]


# ─── Run log tail ───────────────────────────────────────────────────────────

class RunLogResponse(BaseModel):
    run_id: str
    log_path: str | None
    tail: str  # texte brut tail-N lignes


# ─── eBay endpoints ─────────────────────────────────────────────────────────

class EbayQuotaStatus(BaseModel):
    calls_today: int
    limit: int
    remaining: int
    exhausted: bool
    period: str
    avg_calls_per_eurio_id: float


class MarketplaceMapEntry(BaseModel):
    marketplace: str
    query_lang: str


class MarketplaceMapResponse(BaseModel):
    marketplaces: list[MarketplaceMapEntry]


class FilterRule(BaseModel):
    name: str
    kind: str  # 'reject' | 'flag'
    description: str
    pattern: str | None
    threshold: float | None
    policy: str | None


class EbayFilterConfig(BaseModel):
    rules: list[FilterRule]
    source_path: str


class FreshnessGroupItem(BaseModel):
    denomination: float
    country: str
    year: int
    n_coins: int
    last_enriched_at: str | None
    n_images: int
    n_crops: int
    status: str  # 'never' | 'stale' | 'fresh'


class FreshnessBuckets(BaseModel):
    never: int
    stale_90d: int
    fresh: int
    total: int


class EbayFreshnessGroupsResponse(BaseModel):
    items: list[FreshnessGroupItem]
    buckets: FreshnessBuckets


class MarketQuoteEntry(BaseModel):
    condition: str  # tier d'état : 'UNC' | 'TTB' | 'TB' | 'unknown'
    p10: float | None
    p50: float | None
    p90: float | None
    sample_size: int
    period_start: str


class MarketQuotesResponse(BaseModel):
    """Clé = eurio_id ; valeur = liste des quotes les plus récentes
    (`coin_market_quotes`, source ebay), une par tier d'état."""
    quotes: dict[str, list[MarketQuoteEntry]]


# ─── Filter / Query objects ─────────────────────────────────────────────────

class SourceRunFilter(BaseModel):
    source_id: str | None = None
    status: list[str] | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
