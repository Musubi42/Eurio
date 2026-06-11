"""Parité Kotlin↔Python du frame-quality scorer (best-frame-capture chunk 7).

Le test pivot rejoue les mesures brutes d'une **vraie session device**
(``ml/bench/sessions/Pixel9a/...``, committée) à travers le port Python et
exige ≤ 1e-3 d'écart vs les valeurs que le Kotlin a calculées en live. C'est
le verrou du contrat ``FrameQualityScorer.kt`` / ``QualityMath.kt`` ↔
``vision/frame_scorer.py`` : si l'un bouge sans l'autre, ce test casse.

La parité *image-level* (re-scorer depuis frames/*.jpg) attend une session
enregistrée avec ``recordFramesEnabled`` — aucune n'existe encore ; en
attendant :func:`measure_crop` est verrouillé sur des images synthétiques.
"""

from __future__ import annotations

import numpy as np
import pytest

from bench.replay import policy_from_config
from bench.session_io import load_session
from tests._bench_fixtures import REAL_SESSION
from vision import frame_scorer as fs

TOL = 1e-3

pytestmark_session = pytest.mark.skipif(
    not (REAL_SESSION / "events.jsonl").exists(),
    reason="session device committée absente",
)


# ── Parité sur session réelle ────────────────────────────────────────────────


@pytestmark_session
def test_parity_against_recorded_device_session():
    session = load_session(REAL_SESSION)
    assert session.config is not None
    policy = policy_from_config(session.config)

    scored = [f for f in session.frames if f.score is not None]
    assert scored, "la session fixture doit contenir des frames scorées"

    for frame in scored:
        s = frame.score
        re = fs.rescore_from_measures(
            sharpness_raw=s.sharpness_raw,
            mean_luminance=s.mean_luminance,
            clipping_ratio=s.clipping_ratio,
            completeness_score=s.completeness,
            motion_score=s.motion,
            policy=policy,
        )
        ctx = f"frame {frame.frame_id}"
        assert abs(re.sharpness - s.sharpness) <= TOL, ctx
        assert abs(re.exposure - s.exposure) <= TOL, ctx
        assert abs(re.aggregate - s.aggregate) <= TOL, ctx
        assert re.passes_sharpness == s.passes["sharpness"], ctx
        assert re.passes_exposure == s.passes["exposure"], ctx
        assert re.passes_completeness == s.passes["completeness"], ctx
        assert re.passes_motion == s.passes["motion"], ctx
        assert re.passes_all == s.passes["all"], ctx


# ── QualityMath pur (cas miroir des tests Kotlin) ───────────────────────────


def test_normalize_sharpness_clamps():
    assert fs.normalize_sharpness(200.0, 400.0) == 0.5
    assert fs.normalize_sharpness(800.0, 400.0) == 1.0
    assert fs.normalize_sharpness(-5.0, 400.0) == 0.0


def test_exposure_score_perfect_midband_no_clipping():
    assert fs.exposure_score(0.5, 0.0, 0.2, 0.01) == 1.0


def test_exposure_score_recorded_frame_values():
    # Valeurs de la 2e frame scorée de la session Pixel9a (calcul Kotlin :
    # 0.8691902) — vérifie la formule indépendamment du fichier.
    got = fs.exposure_score(0.4476761, 0.0, 0.2, 0.01)
    assert abs(got - 0.8691902) <= TOL


def test_exposure_passes_band_edges():
    assert fs.exposure_passes(0.3, 0.0, 0.2, 0.01)  # pile au bord de bande
    assert not fs.exposure_passes(0.29, 0.0, 0.2, 0.01)
    assert not fs.exposure_passes(0.5, 0.02, 0.2, 0.01)  # clipping trop haut


def test_completeness_geometry():
    # Disque bien à l'intérieur (marge ≥ 5 % du rayon) → 1.0
    assert fs.completeness(112, 112, 80, 224, 224) == 1.0
    # Disque qui touche exactement le bord gauche (marge 0) → 0.5
    assert fs.completeness(80, 112, 80, 224, 224) == 0.5
    # Clippé d'au moins 5 % → 0.0
    assert fs.completeness(70, 112, 80, 224, 224) == 0.0
    # Rayon dégénéré
    assert fs.completeness(0, 0, 0, 224, 224) == 0.0


def test_motion_first_frame_is_perfect():
    assert fs.motion(None, 100, 100, 50, 0.05) == 1.0
    assert fs.motion_passes(None, 100, 100, 50, 0.05)


def test_aggregate_renormalizes_without_motion():
    policy = fs.ScoringPolicy(motion_enabled=False)
    # (1*0.5 + 0.8692*0.2 + 0*0.2) / 0.9 — la frame réelle au completeness 0
    got = fs.aggregate(1.0, 0.8691902, 0.0, None, policy)
    assert abs(got - 0.7487089) <= TOL


def test_aggregate_includes_motion_when_enabled():
    policy = fs.ScoringPolicy(motion_enabled=True)
    with_motion = fs.aggregate(1.0, 1.0, 1.0, 0.0, policy)
    assert abs(with_motion - 0.9) <= TOL  # (0.5+0.2+0.2+0) / 1.0


# ── measure_crop (OpenCV) sur images synthétiques ───────────────────────────


def _disc_image(value: int, size: int = 224, radius: int = 80) -> np.ndarray:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    disc = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= radius**2
    img[disc] = value
    return img


def test_measure_crop_excludes_black_background():
    measures = fs.measure_crop(_disc_image(128))
    assert measures is not None
    disc_area = np.pi * 80 * 80
    assert measures.mask_pixels == pytest.approx(disc_area, rel=0.02)
    assert measures.mean_luminance == pytest.approx(128 / 255, abs=0.01)
    assert measures.clipping_ratio < 0.05  # seul l'anneau de bord clippe bas


def test_measure_crop_bright_clipping():
    measures = fs.measure_crop(_disc_image(255))
    assert measures is not None
    assert measures.clipping_ratio > 0.95


def test_measure_crop_degenerate_inputs():
    # Tout noir → mask vide → Failed (None), jamais un score silencieux.
    assert fs.measure_crop(np.zeros((224, 224, 3), dtype=np.uint8)) is None
    assert fs.measure_crop(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_measure_crop_sharpness_orders_blur():
    rng = np.random.default_rng(42)
    noisy = _disc_image(128)
    noise = rng.integers(-60, 60, noisy.shape[:2])
    yy, xx = np.ogrid[:224, :224]
    disc = (yy - 112) ** 2 + (xx - 112) ** 2 <= 80**2
    for c in range(3):
        chan = noisy[:, :, c].astype(int)
        chan[disc] = np.clip(chan[disc] + noise[disc], 6, 250)
        noisy[:, :, c] = chan.astype(np.uint8)

    import cv2

    blurred = cv2.GaussianBlur(noisy, (15, 15), 0)
    sharp_m = fs.measure_crop(noisy)
    blur_m = fs.measure_crop(blurred)
    assert sharp_m is not None and blur_m is not None
    assert sharp_m.sharpness_raw > blur_m.sharpness_raw * 2
