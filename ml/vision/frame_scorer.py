"""Python port of the Android frame-quality scorer (best-frame-capture chunk 7).

Parity contract — three Kotlin sources mirrored 1:1 :

  - ``domain/scan/quality/QualityMath.kt``   → pure-math helpers below
  - ``domain/scan/quality/ScoringPolicy.kt`` → :class:`ScoringPolicy` defaults
  - ``ml/quality/FrameQualityScorer.kt``     → :func:`measure_crop` (OpenCV)

The split matters for replay (``bench/replay.py``) : sessions recorded
*without* ``frames/`` still carry the raw measures per frame
(``sharpness_raw``, ``mean_luminance``, ``clipping_ratio``, ``completeness``,
``motion``) in ``events.jsonl``, so :func:`rescore_from_measures` can
recompute gates + aggregate under an alternative policy without any image.
:func:`measure_crop` is only needed to re-score from JPEG frames (and to
bench future sub-scores that need pixels).

Locked by ``ml/tests/test_frame_scorer.py``, which replays the recorded
Kotlin scores of a real device session and asserts ≤ 1e-3 drift. Any change
here must keep that test green or bump the bench schema consciously.

Caveat (chunk-7 spec §Questions ouvertes Q1) : recorded frames are JPEG q85,
so image-level re-scoring carries a small sharpness bias vs the live YUV
frame. The measure pipeline itself is bit-faithful ; the bias is in the input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np


@dataclass(frozen=True)
class ScoringPolicy:
    """Mirror of ``ScoringPolicy.kt`` — same defaults, same semantics."""

    w_sharpness: float = 0.5
    w_exposure: float = 0.2
    w_completeness: float = 0.2
    w_motion: float = 0.1

    sharpness_min: float = 80.0
    exposure_band_half_width: float = 0.2
    clipping_max: float = 0.01
    completeness_min: float = 0.95
    motion_max: float = 0.05
    motion_enabled: bool = False

    sharpness_normalization_ceiling: float = 400.0


# ── QualityMath.kt — pure math, no OpenCV ────────────────────────────────────


def normalize_sharpness(raw: float, ceiling: float) -> float:
    """``(raw / ceiling).coerceIn(0f, 1f)``"""
    if ceiling == 0:
        return 0.0
    return min(max(raw / ceiling, 0.0), 1.0)


def exposure_score(
    mean_luminance: float,
    clipping_ratio: float,
    band_half_width: float,
    clipping_max: float,
) -> float:
    band_distance = (
        abs(mean_luminance - 0.5) / band_half_width if band_half_width > 0 else 1.0
    )
    band_sub = min(max(1.0 - band_distance, 0.0), 1.0)
    clipping_sub = (
        min(max(1.0 - clipping_ratio / clipping_max, 0.0), 1.0)
        if clipping_max > 0
        else 0.0
    )
    return (band_sub + clipping_sub) / 2.0


def exposure_passes(
    mean_luminance: float,
    clipping_ratio: float,
    band_half_width: float,
    clipping_max: float,
) -> bool:
    band_distance = (
        abs(mean_luminance - 0.5) / band_half_width if band_half_width > 0 else 1.0
    )
    return band_distance <= 1.0 and clipping_ratio <= clipping_max


def completeness(cx: int, cy: int, r: int, frame_w: int, frame_h: int) -> float:
    """Geometric margin score : 1.0 at ≥5 % margin, 0.5 touching, 0.0 clipped ≥5 %."""
    if r <= 0:
        return 0.0
    rf = float(r)
    min_margin = min(
        (cx - r) / rf,
        (frame_w - cx - r) / rf,
        (cy - r) / rf,
        (frame_h - cy - r) / rf,
    )
    return min(max((min_margin + 0.05) / 0.10, 0.0), 1.0)


def motion(
    previous_center: tuple[float, float] | None,
    current_cx: int,
    current_cy: int,
    radius: int,
    motion_max: float,
) -> float:
    if previous_center is None or radius <= 0:
        return 1.0
    px, py = previous_center
    delta = math.hypot(current_cx - px, current_cy - py) / radius
    if motion_max <= 0:
        return 1.0 if delta == 0 else 0.0
    return min(max(1.0 - delta / motion_max, 0.0), 1.0)


def motion_passes(
    previous_center: tuple[float, float] | None,
    current_cx: int,
    current_cy: int,
    radius: int,
    motion_max: float,
) -> bool:
    if previous_center is None or radius <= 0:
        return True
    px, py = previous_center
    delta = math.hypot(current_cx - px, current_cy - py) / radius
    return delta <= motion_max


def aggregate(
    sharpness: float,
    exposure: float,
    completeness_score: float,
    motion_score: float | None,
    policy: ScoringPolicy,
) -> float:
    """Weighted mean over active axes, weights renormalized like Kotlin."""
    num = (
        sharpness * policy.w_sharpness
        + exposure * policy.w_exposure
        + completeness_score * policy.w_completeness
    )
    den = policy.w_sharpness + policy.w_exposure + policy.w_completeness
    if policy.motion_enabled and motion_score is not None:
        num += motion_score * policy.w_motion
        den += policy.w_motion
    return num / den if den > 0 else 0.0


# ── Recompute from recorded measures (replay without frames) ─────────────────


class FrameScore(NamedTuple):
    """Mirror of ``FrameScore.kt`` flattened for replay output."""

    sharpness: float
    sharpness_raw: float
    exposure: float
    mean_luminance: float
    clipping_ratio: float
    completeness: float
    motion: float | None
    aggregate: float
    passes_sharpness: bool
    passes_exposure: bool
    passes_completeness: bool
    passes_motion: bool | None
    passes_all: bool

    def as_payload(self) -> dict:
        """Shape of the ``score`` object in ``events.jsonl`` (ScorePayload)."""
        return {
            "sharpness": self.sharpness,
            "sharpness_raw": self.sharpness_raw,
            "exposure": self.exposure,
            "mean_luminance": self.mean_luminance,
            "clipping_ratio": self.clipping_ratio,
            "completeness": self.completeness,
            "motion": self.motion,
            "aggregate": self.aggregate,
            "passes": {
                "sharpness": self.passes_sharpness,
                "exposure": self.passes_exposure,
                "completeness": self.passes_completeness,
                "motion": self.passes_motion,
                "all": self.passes_all,
            },
        }


def rescore_from_measures(
    sharpness_raw: float,
    mean_luminance: float,
    clipping_ratio: float,
    completeness_score: float,
    motion_score: float | None,
    policy: ScoringPolicy,
) -> FrameScore:
    """Recompute every derived value (sub-scores, gates, aggregate) from the
    raw measures a session recorded, under an arbitrary policy.

    This is the exact tail of ``FrameQualityScorer.score()`` after the OpenCV
    measures are in — same order, same formulas.
    """
    sharpness = normalize_sharpness(
        sharpness_raw, policy.sharpness_normalization_ceiling
    )
    sharpness_ok = sharpness_raw >= policy.sharpness_min

    exposure = exposure_score(
        mean_luminance,
        clipping_ratio,
        policy.exposure_band_half_width,
        policy.clipping_max,
    )
    exposure_ok = exposure_passes(
        mean_luminance,
        clipping_ratio,
        policy.exposure_band_half_width,
        policy.clipping_max,
    )

    completeness_ok = completeness_score >= policy.completeness_min

    if policy.motion_enabled and motion_score is not None:
        # Le gate Kotlin compare le delta brut à motionMax, pas le score. Le
        # delta est récupérable depuis le score enregistré tant que celui-ci
        # n'est pas saturé à 0 : score = clamp(1 - delta/recordedMotionMax) avec
        # recordedMotionMax figé à 0.05 (ScoringPolicy.kt, pas exposé dans la
        # debug-bar ni dans ConfigPayload). score == 0 ⇒ delta ≥ 0.05 : on le
        # traite en échec sous toute policy dont motion_max ≤ 0.05.
        recorded_motion_max = 0.05
        if motion_score > 0.0:
            delta = (1.0 - motion_score) * recorded_motion_max
            motion_ok: bool | None = delta <= policy.motion_max
            motion_out: float | None = (
                min(max(1.0 - delta / policy.motion_max, 0.0), 1.0)
                if policy.motion_max > 0
                else (1.0 if delta == 0 else 0.0)
            )
        else:
            motion_ok = policy.motion_max > recorded_motion_max
            motion_out = 0.0
    else:
        motion_ok = None
        motion_out = motion_score

    agg = aggregate(sharpness, exposure, completeness_score, motion_out, policy)
    all_ok = sharpness_ok and exposure_ok and completeness_ok and (
        motion_ok if motion_ok is not None else True
    )

    return FrameScore(
        sharpness=sharpness,
        sharpness_raw=sharpness_raw,
        exposure=exposure,
        mean_luminance=mean_luminance,
        clipping_ratio=clipping_ratio,
        completeness=completeness_score,
        motion=motion_out,
        aggregate=agg,
        passes_sharpness=sharpness_ok,
        passes_exposure=exposure_ok,
        passes_completeness=completeness_ok,
        passes_motion=motion_ok,
        passes_all=all_ok,
    )


# ── FrameQualityScorer.kt — OpenCV measures from a normalized crop ───────────


class CropMeasures(NamedTuple):
    """Raw OpenCV measures — the inputs Kotlin feeds into QualityMath."""

    sharpness_raw: float
    mean_luminance: float
    clipping_ratio: float
    mask_pixels: int


def measure_crop(image: np.ndarray | str | Path) -> CropMeasures | None:
    """Measure a normalized 224 crop exactly like ``FrameQualityScorer.kt``.

    - mask = gray > 5 (THRESH_BINARY at 5.0) — the black-disc background of
      ``SnapNormalizer`` is excluded ;
    - sharpness_raw = stddev² of ``Laplacian(gray, CV_64F, ksize=3)`` over the
      mask ;
    - mean_luminance = masked gray mean / 255, clamped [0, 1] ;
    - clipping_ratio = fraction of masked pixels < 4 (THRESH_BINARY_INV at 4.0,
      i.e. gray ≤ 4) or > 251.

    Returns ``None`` for degenerate input (empty image or empty mask) — the
    mirror of ``FrameScore.Failed``. Per ``feedback_no_debt`` callers must
    surface that case, never skip it silently.
    """
    if isinstance(image, (str, Path)):
        loaded = cv2.imread(str(image), cv2.IMREAD_COLOR)
        if loaded is None:
            return None
        image = loaded
    if image.size == 0:
        return None

    gray = (
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    )
    _, mask = cv2.threshold(gray, 5.0, 255.0, cv2.THRESH_BINARY)
    mask = mask.astype(np.uint8)
    mask_pixels = int(cv2.countNonZero(mask))
    if mask_pixels == 0:
        return None

    lap = cv2.Laplacian(gray, cv2.CV_64F, ksize=3)
    _, lap_stddev = cv2.meanStdDev(lap, mask=mask)
    stddev = float(lap_stddev[0][0])
    sharpness_raw = stddev * stddev

    gray_mean, _ = cv2.meanStdDev(gray, mask=mask)
    mean_luminance = min(max(float(gray_mean[0][0]) / 255.0, 0.0), 1.0)

    _, dark = cv2.threshold(gray, 4.0, 255.0, cv2.THRESH_BINARY_INV)
    _, bright = cv2.threshold(gray, 251.0, 255.0, cv2.THRESH_BINARY)
    clipped = int(
        cv2.countNonZero(cv2.bitwise_and(dark.astype(np.uint8), mask))
    ) + int(cv2.countNonZero(cv2.bitwise_and(bright.astype(np.uint8), mask)))
    clipping_ratio = clipped / mask_pixels

    return CropMeasures(
        sharpness_raw=sharpness_raw,
        mean_luminance=mean_luminance,
        clipping_ratio=clipping_ratio,
        mask_pixels=mask_pixels,
    )
