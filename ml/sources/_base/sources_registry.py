"""Declarative registry of every supported source.

Single source of truth for: which sources exist, their kind (api vs
scrape), default license, default `variant_kind`, expected cadence,
and quota policy. Consumed by:
- the orchestrator (license/redistributable defaults at upsert time)
- the admin `/sources/status` endpoint (display metadata)
- onboarding checks (a new source must register here before it can run)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceSpec:
    id: str
    label: str
    kind: str                              # 'api' | 'scrape'
    default_variant_kind: str
    default_license: str
    redistributable: bool
    expected_cadence_days: int
    quota_window: str | None = None        # 'daily' | 'monthly' | None
    quota_limit: int | None = None
    rate_limit_calls_per_sec: float | None = None
    is_future: bool = False
    notes: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


SOURCES: dict[str, SourceSpec] = {
    "mock": SourceSpec(
        id="mock",
        label="Mock (test fixture)",
        kind="api",
        default_variant_kind="unknown",
        default_license="unknown",
        redistributable=False,
        expected_cadence_days=0,
        is_future=True,
        notes="Used by ml/tests/test_orchestrator.py — not a real source.",
    ),
    "numista": SourceSpec(
        id="numista",
        label="Numista",
        kind="api",
        default_variant_kind="canonical",
        default_license="numista_api",
        redistributable=False,
        expected_cadence_days=30,
        quota_window="monthly",
        quota_limit=1800,
        notes="Canonical obverse/reverse + rich metadata. 2 keys shared.",
    ),
    "ebay": SourceSpec(
        id="ebay",
        label="eBay Browse",
        kind="api",
        default_variant_kind="auction_listing",
        default_license="fair_use_research",
        redistributable=False,
        expected_cadence_days=30,
        quota_window="daily",
        quota_limit=5000,
        notes="Active listings only. Sold listings need Marketplace Insights (paid).",
    ),
    "lmdlp": SourceSpec(
        id="lmdlp",
        label="La Monnaie de la Pièce",
        kind="scrape",
        default_variant_kind="merchant_catalog",
        default_license="fair_use_research",
        redistributable=False,
        expected_cadence_days=90,
        rate_limit_calls_per_sec=0.5,
    ),
    "mdp": SourceSpec(
        id="mdp",
        label="Monnaie de Paris",
        kind="scrape",
        default_variant_kind="official_press",
        default_license="editorial_official",
        redistributable=False,
        expected_cadence_days=90,
        rate_limit_calls_per_sec=0.5,
    ),
    "bce": SourceSpec(
        id="bce",
        label="BCE",
        kind="scrape",
        default_variant_kind="official_press",
        default_license="editorial_official",
        redistributable=False,
        expected_cadence_days=90,
        rate_limit_calls_per_sec=0.5,
    ),
    "catawiki": SourceSpec(
        id="catawiki",
        label="Catawiki",
        kind="scrape",
        default_variant_kind="auction_listing",
        default_license="fair_use_research",
        redistributable=False,
        expected_cadence_days=14,
        rate_limit_calls_per_sec=0.5,
        is_future=True,
        notes="Phase 2. Dynamic JS site, may need Playwright.",
    ),
    "numiscorner": SourceSpec(
        id="numiscorner",
        label="NumisCorner",
        kind="scrape",
        default_variant_kind="merchant_catalog",
        default_license="fair_use_research",
        redistributable=False,
        expected_cadence_days=30,
        rate_limit_calls_per_sec=1.0,
        is_future=True,
        notes="Phase 2. Structured merchant site, low-noise images.",
    ),
    "cgb": SourceSpec(
        id="cgb",
        label="CGB",
        kind="scrape",
        default_variant_kind="merchant_catalog",
        default_license="fair_use_research",
        redistributable=False,
        expected_cadence_days=30,
        rate_limit_calls_per_sec=1.0,
        is_future=True,
        notes="Phase 2. Fine grading (FDC, SUP-62, ...) needs a rich condition map.",
    ),
    "wikipedia": SourceSpec(
        id="wikipedia",
        label="Wikipedia",
        kind="scrape",
        default_variant_kind="official_press",
        default_license="public_domain",
        redistributable=True,
        expected_cadence_days=365,
        is_future=True,
        notes="Per-country catalogue pages. License varies per image — re-tag at fetch time.",
    ),
}


def get(source_id: str) -> SourceSpec:
    try:
        return SOURCES[source_id]
    except KeyError as e:
        raise KeyError(f"Unknown source '{source_id}'. Add it to SOURCES first.") from e
