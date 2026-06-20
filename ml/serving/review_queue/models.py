"""Pydantic schemas du domaine `review_queue`.

Shape JSON aligné sur `review/review_queue_routes.py` legacy (consommé par
`admin/packages/studio-local/src/features/review/composables/*`).

Phase 2c scope : stats, rejected, text-signals. Les endpoints `list`, `detail`,
`triage-stats`, `lots` sont planifiés pour Phase 2c-bis (ils requièrent un port
de logique plus lourde — cf. DECISIONS.md §D-10).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ─── Stats ──────────────────────────────────────────────────────────────────


class ReviewStats(BaseModel):
    n_pending: int
    n_done_today: int
    n_done_this_week: int
    median_seconds_per_decision: float


# ─── Rejected crops ─────────────────────────────────────────────────────────


class RejectedCrop(BaseModel):
    review_id: str
    image_asset_id: str
    crop_url: str
    listing_title: str | None
    quality_reason: str | None
    decided_at: str | None
    target_eurio_id: str | None
    target_label: str | None


# ─── Text signals ───────────────────────────────────────────────────────────


class TextSignalsResponse(BaseModel):
    """Snapshot des signaux extraits du titre du listing (table
    `listing_text_signals`, peuplée par le step text_signal du pipeline).

    Shape identique au legacy `review_queue_routes.TextSignalsResponse`.
    """
    source_image_id: str
    extractor_version: str
    listing_title: str | None = None
    target_eurio_id: str | None = None
    countries: list[str]
    years: list[int]
    denominations: list[float]
    theme_tokens: list[str]
    rejected_markers: list[str]
    is_lot: bool
    coverage: str
    matched: dict[str, list[str]]
    vs_target_verdict: str | None = None
    contradictions: list[str] = []
    convergences: list[str] = []
    computed_at: str | None = None
