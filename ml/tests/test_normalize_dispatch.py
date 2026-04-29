"""Sanity tests for the normalize dispatcher in `ml/scan/normalize_snap.py`.

Verifies:
  - the public API exists and exports the expected names
  - constants haven't drifted from the ArcFace contract
  - both pipelines return a 224×224 BGR uint8 image on a known-good source
  - the studio fallback is reachable and tagged

Not a parity test — `parity_test.py` does that. Just the dispatch contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan import normalize_snap  # noqa: E402


ML_DIR = Path(__file__).resolve().parents[1]


def test_public_api_present():
    expected = {
        "normalize_studio", "normalize_studio_path",
        "normalize_device", "normalize_device_path",
        "draw_debug",
        "OUTPUT_SIZE", "COIN_MARGIN", "BG_COLOR", "WORKING_RES",
        "NormalizationResult",
    }
    missing = expected - set(dir(normalize_snap))
    assert not missing, f"missing from normalize_snap: {missing}"


def test_constants_frozen():
    assert normalize_snap.OUTPUT_SIZE == 224
    assert normalize_snap.COIN_MARGIN == 0.02
    assert normalize_snap.BG_COLOR == (0, 0, 0)
    assert normalize_snap.WORKING_RES == 1024


@pytest.mark.parametrize("nid", [9761])  # AT 2nd map — clean bimetal,
                                          # both pipelines land on outer rim
def test_studio_returns_224(nid: int):
    p = ML_DIR / "datasets" / str(nid) / "obverse.jpg"
    if not p.is_file():
        pytest.skip(f"missing {p}")
    res = normalize_snap.normalize_studio_path(p)
    assert res.image is not None, f"studio failed: {res.debug}"
    assert res.image.shape == (224, 224, 3)
    assert res.image.dtype == np.uint8
    assert res.r > 0
    # method is either "contour" (success) or "contour_fallback:<hough_pass>"
    assert res.method.startswith("contour"), f"unexpected method: {res.method}"


@pytest.mark.parametrize("nid", [9761])
def test_device_returns_224(nid: int):
    p = ML_DIR / "datasets" / str(nid) / "obverse.jpg"
    if not p.is_file():
        pytest.skip(f"missing {p}")
    res = normalize_snap.normalize_device_path(p)
    assert res.image is not None, f"device failed: {res.debug}"
    assert res.image.shape == (224, 224, 3)
    assert res.image.dtype == np.uint8
    assert res.method.startswith("hough_"), f"unexpected method: {res.method}"


def test_studio_fallback_tagged():
    # ID 2180 = pale 2 EUR Andorra; Phase A confirmed studio falls back to
    # the Hough device path on this one (low_fill_ratio).
    p = ML_DIR / "datasets" / "2180" / "obverse.jpg"
    if not p.is_file():
        pytest.skip(f"missing {p}")
    res = normalize_snap.normalize_studio_path(p)
    assert res.image is not None
    assert res.method.startswith("contour_fallback:"), \
        f"expected fallback, got method={res.method}"
    assert res.debug.get("fallback_reason"), \
        "fallback_reason missing in debug"


def test_empty_input_returns_failed():
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    s = normalize_snap.normalize_studio(empty)
    d = normalize_snap.normalize_device(empty)
    assert s.image is None and d.image is None
    assert s.debug.get("error") and d.debug.get("error")
