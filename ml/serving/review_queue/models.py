"""Pydantic schemas du domaine `review_queue`.

Shape JSON aligné sur `review/review_queue_routes.py` legacy (consommé par
`admin/packages/studio-local/src/features/review/composables/*`).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ─── Review item shape (list + detail) ──────────────────────────────────────


class ReviewBbox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ReviewCandidate(BaseModel):
    eurio_id: str
    score: float
    label: str
    country: str
    denomination: str
    year: int | None = None
    canonical_thumb_url: str = ""


class ReviewItem(BaseModel):
    id: str
    crop_url: str
    bbox: ReviewBbox | None
    source: str
    source_ref: str
    listing_title: str | None
    listing_url: str | None
    listing_price: float | None
    listing_kind: str | None = None
    listing_kind_confidence: float | None = None
    condition: str | None = None
    condition_confidence: float | None = None
    listing_origin_date: str | None = None
    sold_qty: int | None = None
    candidates: list[ReviewCandidate]
    face_detected: str | None
    priority: int
    is_multi_coin_lot: bool
    quality_score: float
    enqueued_at: str
    target_eurio_id: str | None = None
    target_candidate: ReviewCandidate | None = None
    group_candidates: list[ReviewCandidate] = []
    standard_candidates: list[ReviewCandidate] = []
    dino_top1: ReviewCandidate | None = None
    # Signaux de la banque des SUGGESTIONS (`2eur_all`), pas de celle du
    # verdict. Ils portent le tri : sans eux, l'écran classerait les crops par
    # un critère qu'il ne peut pas montrer, et l'opérateur n'aurait aucun moyen
    # de savoir pourquoi celui-ci est en tête.
    sugg_top1_eurio_id: str | None = None
    sugg_top1_sim: float | None = None
    sugg_spread: float | None = None


# ─── Stats ──────────────────────────────────────────────────────────────────


class ReviewStats(BaseModel):
    n_pending: int
    n_done_today: int
    n_done_this_week: int
    median_seconds_per_decision: float


class TriageVerdictCounts(BaseModel):
    auto_candidate: int
    partial: int
    divergent: int
    unknown: int


class TriageLaneCounts(BaseModel):
    manual: int
    auto_accept: int


class TriageStats(BaseModel):
    """Réponse de /review-queue/triage-stats. Mirror du legacy."""
    n_pending: int
    n_done_today: int
    n_done_today_auto_dino: int
    n_done_this_week: int
    by_verdict: TriageVerdictCounts
    by_lane: TriageLaneCounts
    by_lane_lot: TriageLaneCounts
    n_lot_crops: int
    n_rejected: int
    n_skipped: int


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


# ─── Lots ───────────────────────────────────────────────────────────────────


class LotListItem(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    n_images: int
    n_crops_in_review: int
    oldest_enqueued_at: str
    thumb_url: str | None


class LotListResponse(BaseModel):
    items: list[LotListItem]
    total: int


class LotCrop(BaseModel):
    asset_id: str
    review_id: str
    crop_url: str
    crop_index: int
    phash: int | None
    current_eurio_id: str | None
    candidate_eurio_ids: list[ReviewCandidate]
    bbox: ReviewBbox | None


class LotDetection(BaseModel):
    cx: int
    cy: int
    r: int
    accepted: bool
    reject_reason: str | None
    method: str
    crop_index: int | None


class LotImage(BaseModel):
    source_image_id: str
    image_index: int | None
    raw_url: str
    raw_width: int | None
    raw_height: int | None
    detections: list[LotDetection]
    crops: list[LotCrop]


class LotDetail(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    target_candidate: ReviewCandidate | None = None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    is_multi_crop_single: bool
    images: list[LotImage]
    prev_listing_key: str | None
    next_listing_key: str | None


# ─── Text signals ───────────────────────────────────────────────────────────


class TextSignalsResponse(BaseModel):
    """Snapshot des signaux extraits du titre du listing (table
    `listing_text_signals`).
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
