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

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import normalize_snap  # noqa: E402


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


# ---------------------------------------------------------------------------
# CropConfig & edge_mode (ablation infra)
# ---------------------------------------------------------------------------


def _synthetic_coin(size: int = 600, r: int = 200) -> np.ndarray:
    """Pièce synthétique : disque gris sur fond blanc, motif central plus
    sombre pour avoir un signal interne distinct."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    cv2.circle(img, (size // 2, size // 2), r, (160, 160, 160), -1)
    cv2.circle(img, (size // 2, size // 2), r // 2, (80, 80, 80), -1)
    return img


def test_crop_config_default_matches_legacy_constants():
    cfg = normalize_snap.CropConfig()
    assert cfg.margin_frac == normalize_snap.COIN_MARGIN
    assert cfg.edge_mode == "hard"
    assert cfg.output_size == normalize_snap.OUTPUT_SIZE


def test_crop_config_default_is_bit_identical_to_legacy():
    """Le path config=None DOIT produire le même crop que config=default
    (= zero régression Kotlin parity)."""
    img = _synthetic_coin()
    r_none = normalize_snap._crop_mask_resize_int(img, 300, 300, 200,
                                                    method="test", config=None)
    r_default = normalize_snap._crop_mask_resize_int(img, 300, 300, 200,
                                                      method="test",
                                                      config=normalize_snap.CropConfig())
    assert r_none.image is not None and r_default.image is not None
    assert np.array_equal(r_none.image, r_default.image)


def test_edge_mode_none_keeps_corners():
    """Avec edge_mode='none' on garde le fond blanc dans les coins."""
    img = _synthetic_coin()
    cfg = normalize_snap.CropConfig(edge_mode="none")
    res = normalize_snap._crop_mask_resize_int(img, 300, 300, 200,
                                                method="test", config=cfg)
    assert res.image is not None
    # Coins doivent rester proches du blanc (250+)
    corner = res.image[2, 2]
    assert int(corner.mean()) > 200, f"corner not preserved: {corner}"


def test_edge_mode_hard_blacks_corners():
    img = _synthetic_coin()
    cfg = normalize_snap.CropConfig(edge_mode="hard")
    res = normalize_snap._crop_mask_resize_int(img, 300, 300, 200,
                                                method="test", config=cfg)
    assert res.image is not None
    corner = res.image[2, 2]
    assert int(corner.mean()) < 20, f"corner not blacked: {corner}"


def test_edge_mode_feathered_transitions():
    """Feathered : ni purement noir ni purement préservé sur la frontière."""
    img = _synthetic_coin()
    cfg = normalize_snap.CropConfig(edge_mode="feathered",
                                     feather_width_frac=0.10)
    res = normalize_snap._crop_mask_resize_int(img, 300, 300, 200,
                                                method="test", config=cfg)
    assert res.image is not None
    # Le coin doit être noir (loin du disque), mais des pixels intermédiaires
    # doivent exister dans la zone de transition. Sample sur une diagonale.
    diag = [res.image[i, i].mean() for i in range(res.image.shape[0])]
    intermediate = [v for v in diag if 20 < v < 200]
    assert len(intermediate) > 5, \
        f"expected feathered transition, got step (intermediate count={len(intermediate)})"


def test_custom_output_size_respected():
    img = _synthetic_coin()
    cfg = normalize_snap.CropConfig(output_size=160)
    res = normalize_snap._crop_mask_resize_int(img, 300, 300, 200,
                                                method="test", config=cfg)
    assert res.image is not None
    assert res.image.shape == (160, 160, 3)


def test_margin_frac_affects_crop_side():
    img = _synthetic_coin()
    res_tight = normalize_snap._crop_mask_resize_int(
        img, 300, 300, 200, method="t",
        config=normalize_snap.CropConfig(margin_frac=0.02))
    res_loose = normalize_snap._crop_mask_resize_int(
        img, 300, 300, 200, method="t",
        config=normalize_snap.CropConfig(margin_frac=0.15))
    # Tous deux resized à 224, mais l'aire utile (disque visible) sera plus
    # petite dans le loose → on le mesure via le nombre de pixels non-BG.
    assert res_tight.image is not None and res_loose.image is not None
    nonbg_tight = int((res_tight.image.sum(axis=2) > 0).sum())
    nonbg_loose = int((res_loose.image.sum(axis=2) > 0).sum())
    # Plus de margin → plus de BG noir dans les coins → moins de pixels non-BG
    assert nonbg_loose < nonbg_tight, \
        f"loose ({nonbg_loose}) should have fewer non-BG px than tight ({nonbg_tight})"


def test_normalize_device_accepts_config():
    """L'orchestrateur normalize_device propage bien le config."""
    img = _synthetic_coin(size=800, r=300)
    cfg = normalize_snap.CropConfig(output_size=160, edge_mode="none")
    res = normalize_snap.normalize_device(img, config=cfg)
    if res.image is None:
        pytest.skip(f"Hough did not detect synth coin: {res.debug}")
    assert res.image.shape == (160, 160, 3)
    corner = res.image[2, 2]
    assert int(corner.mean()) > 200, "edge_mode none not propagated"
