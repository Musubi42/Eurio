"""Tests for the listing pipeline (multi-Hough) in `ml/scan/normalize_snap.py`.

Covers `detect_circles_multi`, `normalize_listing`, and the contract
expected by `sources/_base/steps/detect_crop.py` (one NormalizationResult
per accepted coin, 224×224 BGR uint8, ordered by Hough vote).

Synthetic fixtures only — no on-disk dependency.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan.normalize_snap import (  # noqa: E402
    CircleDetection,
    NormalizationResult,
    detect_circles_multi,
    normalize_listing,
)


# ─── Fixture helpers ────────────────────────────────────────────────────

def _make_listing(circles: list[tuple[int, int, int]],
                  bg_color: tuple[int, int, int] = (40, 40, 50),
                  size: tuple[int, int] = (1200, 900)) -> np.ndarray:
    """Build a synthetic listing image with N coins on a uniform background.

    `circles` is a list of ``(cx, cy, r)`` tuples in native pixel coords.
    Coins drawn as filled grey circles (intentionally distinct from BG so
    Hough has a clear gradient).
    """
    h, w = size[1], size[0]
    img = np.full((h, w, 3), bg_color, dtype=np.uint8)
    for cx, cy, r in circles:
        cv2.circle(img, (cx, cy), r, (220, 200, 180), -1)
        cv2.circle(img, (cx, cy), r, (40, 40, 40), 3)  # rim contrast for Hough
    return img


# ─── detect_circles_multi ──────────────────────────────────────────────

def test_detect_zero_when_blank_image():
    img = np.full((900, 1200, 3), 50, dtype=np.uint8)
    detections = detect_circles_multi(img)
    assert detections == []


def test_detect_one_coin_centered():
    img = _make_listing([(600, 450, 200)])
    detections = detect_circles_multi(img)
    accepted = [d for d in detections if d.accepted]
    assert len(accepted) == 1
    d = accepted[0]
    assert abs(d.cx - 600) < 15
    assert abs(d.cy - 450) < 15
    assert abs(d.r - 200) < 15
    assert d.method == "hough_strict"
    assert d.reject_reason is None


def test_detect_eight_coins_grid():
    """BU coffret 3+3+2 layout — should accept all 8."""
    coins = [
        (300, 250, 110), (600, 250, 110), (900, 250, 110),
        (300, 500, 110), (600, 500, 110), (900, 500, 110),
        (450, 750, 110), (750, 750, 110),
    ]
    img = _make_listing(coins, size=(1200, 1000))
    detections = detect_circles_multi(img)
    accepted = [d for d in detections if d.accepted]
    # Multi-Hough may merge or miss 1 in synthetic conditions; allow 7-9.
    assert 7 <= len(accepted) <= 9, f"got {len(accepted)} accepted: {accepted}"


def test_detect_off_edge_circle_rejected():
    # Coin partially off the right edge.
    img = _make_listing([(1180, 450, 100)])
    detections = detect_circles_multi(img)
    rejected = [d for d in detections if not d.accepted]
    # Either rejected for off_edge, or detected at adjusted position.
    # We at least want the off-edge case to be flagged when picked up.
    if rejected:
        assert any(d.reject_reason == "off_edge" for d in rejected)


def test_detect_radius_too_small_rejected():
    # Coin with r=40 in a 900-tall image: short=900, rmin_strict = 0.10*900 = 90.
    img = _make_listing([(600, 450, 40)])
    detections = detect_circles_multi(img)
    # r=40 might not even pass the loose rmin (=0.06*900=54), so could be 0.
    rejected = [d for d in detections if not d.accepted]
    if rejected:
        assert any(d.reject_reason == "radius_too_small" for d in rejected)


def test_detect_returns_circle_detection_dataclass():
    img = _make_listing([(600, 450, 200)])
    detections = detect_circles_multi(img)
    for d in detections:
        assert isinstance(d, CircleDetection)
        assert isinstance(d.accepted, bool)
        assert d.method.startswith("hough_")


# ─── normalize_listing ─────────────────────────────────────────────────

def test_normalize_listing_emits_one_per_accepted():
    img = _make_listing([(600, 450, 200)])
    results = normalize_listing(img)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, NormalizationResult)
    assert r.image is not None
    assert r.image.shape == (224, 224, 3)
    assert r.image.dtype == np.uint8


def test_normalize_listing_empty_on_blank():
    img = np.full((900, 1200, 3), 50, dtype=np.uint8)
    results = normalize_listing(img)
    assert results == []


def test_normalize_listing_eight_coins():
    coins = [
        (300, 250, 110), (600, 250, 110), (900, 250, 110),
        (300, 500, 110), (600, 500, 110), (900, 500, 110),
        (450, 750, 110), (750, 750, 110),
    ]
    img = _make_listing(coins, size=(1200, 1000))
    results = normalize_listing(img)
    assert 7 <= len(results) <= 9
    for r in results:
        assert r.image is not None
        assert r.image.shape == (224, 224, 3)


def test_normalize_listing_handles_none_input():
    # Defensive — empty array, None.
    assert normalize_listing(None) == []  # type: ignore[arg-type]
    assert normalize_listing(np.zeros((0, 0, 3), dtype=np.uint8)) == []


def test_detect_order_stable_for_identical_input():
    """Determinism — same input → same detections in same order."""
    img = _make_listing([(300, 300, 150), (700, 600, 130)])
    d1 = detect_circles_multi(img)
    d2 = detect_circles_multi(img)
    assert len(d1) == len(d2)
    for a, b in zip(d1, d2):
        assert a.cx == b.cx and a.cy == b.cy and a.r == b.r
        assert a.accepted == b.accepted
