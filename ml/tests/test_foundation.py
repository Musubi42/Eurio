"""Unit tests for ml/foundation/ — DINOv2 wrapper + anchors + matcher.

Heavy ops (loading the model, encoding) are gated behind a class with
the marker `slow`; everything else runs in milliseconds and stays in
default test runs.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.foundation import (  # noqa: E402
    DEFAULT_ENCODER_VERSION,
    INPUT_SIZE,
    AnchorBank,
    Match,
    build_transform,
    load_anchors,
    pick_device,
    save_anchors,
    spread,
    top_k_match,
    top_k_match_country,
)


# ---------------------------------------------------------------------------
# Fast tests (no model load)
# ---------------------------------------------------------------------------


def test_encoder_constants():
    assert DEFAULT_ENCODER_VERSION == "dinov2-vits14"
    assert INPUT_SIZE == 224
    assert INPUT_SIZE % 14 == 0  # DINOv2 patch size


def test_pick_device_returns_torch_device():
    import torch
    dev = pick_device()
    assert isinstance(dev, torch.device)
    assert dev.type in {"cuda", "mps", "cpu"}


def test_build_transform_shapes_and_normalizes():
    tx = build_transform()
    img = Image.new("RGB", (640, 480), color=(128, 128, 128))
    out = tx(img)
    assert out.shape == (3, INPUT_SIZE, INPUT_SIZE)
    # ImageNet-normalized grey 128 lands roughly in [-2, 2]
    assert -2.5 < float(out.mean()) < 2.5


# ---------------------------------------------------------------------------
# Matcher (no model load — uses fixture bank)
# ---------------------------------------------------------------------------


def _fixture_bank() -> AnchorBank:
    """3 random L2-normalized anchors of dim 8."""
    rng = np.random.default_rng(42)
    raw = rng.standard_normal((3, 8)).astype(np.float32)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    return AnchorBank(
        eurio_ids=["a", "b", "c"],
        matrix=raw,
        encoder_version="test",
        anchors_kind="test",
        built_at=datetime.now(timezone.utc).isoformat(),
        source_paths=[],
    )


def test_top_k_match_orders_desc_by_sim():
    bank = _fixture_bank()
    # Aim the query straight at the second anchor → top1 must be 'b'.
    query = bank.matrix[1].copy()
    matches = top_k_match(query, bank, top_k=3)
    assert len(matches) == 3
    sims = [m.sim for m in matches]
    assert sims == sorted(sims, reverse=True)
    assert matches[0].eurio_id == "b"
    assert matches[0].sim == pytest.approx(1.0, abs=1e-5)


def test_top_k_match_clamps_to_bank_size():
    bank = _fixture_bank()
    matches = top_k_match(bank.matrix[0], bank, top_k=99)
    assert len(matches) == 3


def test_top_k_match_rejects_dim_mismatch():
    bank = _fixture_bank()
    with pytest.raises(ValueError, match="dim"):
        top_k_match(np.zeros(7, dtype=np.float32), bank, top_k=2)


def test_top_k_match_rejects_2d_query():
    bank = _fixture_bank()
    with pytest.raises(ValueError, match="1-D"):
        top_k_match(np.zeros((1, 8), dtype=np.float32), bank, top_k=2)


def test_spread_zero_when_lt_2():
    assert spread([]) == 0.0
    assert spread([Match("x", 0.9)]) == 0.0


def test_spread_returns_top1_minus_top2():
    matches = [Match("a", 0.8), Match("b", 0.5), Match("c", 0.4)]
    assert spread(matches) == pytest.approx(0.3, abs=1e-9)


def test_match_to_dict():
    m = Match("ad-2007-2eur-bearded", 0.7421)
    assert m.to_dict() == {"eurio_id": "ad-2007-2eur-bearded", "sim": 0.7421}


# ---------------------------------------------------------------------------
# B · banque multi-exemplaires : dédup par classe + FPS + round-trip asset_ids
# ---------------------------------------------------------------------------


def _multi_exemplar_bank() -> AnchorBank:
    """Classe 'a' a 3 lignes (1 canonique + 2 exemplaires), 'b' a 1 ligne."""
    rng = np.random.default_rng(7)
    raw = rng.standard_normal((4, 8)).astype(np.float32)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    return AnchorBank(
        eurio_ids=["a", "a", "a", "b"],
        matrix=raw,
        encoder_version="test", anchors_kind="2eur_all",
        built_at=datetime.now(timezone.utc).isoformat(),
        source_paths=["can_a", "crop1", "crop2", "can_b"],
        asset_ids=[None, "as1", "as2", None],
    )


def test_top_k_match_dedups_classes_takes_max_line():
    """Une classe multi-lignes ne sort qu'UNE fois, à sa meilleure ligne."""
    bank = _multi_exemplar_bank()
    # Query = la 2ᵉ ligne de 'a' (exemplaire) → 'a' top1 à sim ~1, une seule fois.
    matches = top_k_match(bank.matrix[1].copy(), bank, top_k=5)
    eids = [m.eurio_id for m in matches]
    assert eids.count("a") == 1               # dédup : pas 3× 'a'
    assert set(eids) == {"a", "b"}
    assert matches[0].eurio_id == "a"
    assert matches[0].sim == pytest.approx(1.0, abs=1e-5)


def test_anchor_bank_roundtrip_preserves_asset_ids(tmp_path, monkeypatch):
    """save/load conservent asset_ids (None = canonique)."""
    from training.foundation import anchors as anchors_mod
    monkeypatch.setattr(anchors_mod, "STATE_DIR", tmp_path)
    bank = _multi_exemplar_bank()
    save_anchors(bank)
    # La banque porte un encodeur ("test") qui n'est pas celui de production
    # pour `2eur_all` : depuis le scoping, elle n'écrit QUE son chemin scopé
    # (c'est précisément ce qui l'empêche d'écraser la banque servie).
    loaded = load_anchors("2eur_all", "test")
    assert loaded is not None
    assert loaded.eurio_ids == ["a", "a", "a", "b"]
    assert loaded.asset_ids == [None, "as1", "as2", None]


def test_farthest_point_select_prefers_diverse_over_duplicate():
    """FPS choisit le point NOUVEAU, pas le quasi-doublon du canonique."""
    from training.foundation.anchors import farthest_point_select
    # canonique = e0 ; candidats : c0 ≈ canonique (doublon), c1 orthogonal-ish.
    canon = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    dup = np.array([0.99, 0.14, 0.0], dtype=np.float32)
    dup /= np.linalg.norm(dup)
    diverse = np.array([0.5, 0.86, 0.0], dtype=np.float32)
    diverse /= np.linalg.norm(diverse)
    vecs = np.stack([dup, diverse])
    picks = farthest_point_select(
        vecs, candidate_idx=[0, 1], k=1, seed_vecs=canon[None, :],
        floor_sim=0.0,
    )
    assert len(picks) == 1
    assert picks[0][0] == 1  # 'diverse' choisi, pas le doublon


def test_farthest_point_select_floor_rejects_outliers():
    """Le plancher de validité écarte un candidat trop loin du centroïde."""
    from training.foundation.anchors import farthest_point_select
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([0.98, 0.2, 0.0], dtype=np.float32); b /= np.linalg.norm(b)
    junk = np.array([0.0, 0.0, 1.0], dtype=np.float32)  # orthogonal = outlier
    vecs = np.stack([a, b, junk])
    picks = farthest_point_select(
        vecs, candidate_idx=[0, 1, 2], k=3, seed_vecs=None, floor_sim=0.5,
    )
    chosen = {i for i, _ in picks}
    assert 2 not in chosen  # 'junk' sous le plancher → jamais choisi


# ---------------------------------------------------------------------------
# Country-restricted matcher (chunk 3.5 — re-rank within target ISO2)
# ---------------------------------------------------------------------------


def _multi_country_bank() -> AnchorBank:
    """5 anchors across 3 countries (ad/it/si) with deterministic vectors."""
    rng = np.random.default_rng(7)
    raw = rng.standard_normal((5, 8)).astype(np.float32)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    return AnchorBank(
        eurio_ids=[
            "ad-2014-2eur-x",
            "ad-2017-2eur-y",
            "it-2015-2eur-z",
            "si-2011-2eur-w",
            "si-2014-2eur-v",
        ],
        matrix=raw,
        encoder_version="test",
        anchors_kind="test_country",
        built_at=datetime.now(timezone.utc).isoformat(),
        source_paths=[],
    )


def test_top_k_match_country_filters_to_target_iso2():
    bank = _multi_country_bank()
    # Aim straight at it-2015 — without filter that's top1.
    query = bank.matrix[2].copy()
    matches = top_k_match_country(query, bank, target_country="ad", top_k=5)
    # Only AD anchors should appear.
    assert len(matches) == 2
    assert all(m.eurio_id.startswith("ad") for m in matches)
    # Sims still come from the unmasked dot-product, not the -inf placeholder.
    assert all(-1.0 <= m.sim <= 1.0 for m in matches)
    # Order: desc by sim within country.
    assert matches[0].sim >= matches[1].sim


def test_top_k_match_country_returns_empty_when_no_anchor():
    bank = _multi_country_bank()
    matches = top_k_match_country(
        bank.matrix[0], bank, target_country="zz", top_k=3,
    )
    assert matches == []


def test_top_k_match_country_case_insensitive():
    bank = _multi_country_bank()
    a = top_k_match_country(bank.matrix[0], bank, target_country="ad")
    b = top_k_match_country(bank.matrix[0], bank, target_country="AD")
    assert [(m.eurio_id, m.sim) for m in a] == [(m.eurio_id, m.sim) for m in b]


def test_top_k_match_country_picks_correct_top1_when_target_in_country():
    """The crop's true match (target itself, sim=1.0) should win the
    country band when it's in the target country."""
    bank = _multi_country_bank()
    # Aim straight at ad-2014 (idx 0). Country filter to AD → top1 = ad-2014.
    matches = top_k_match_country(bank.matrix[0], bank, target_country="ad", top_k=5)
    assert matches[0].eurio_id == "ad-2014-2eur-x"
    assert matches[0].sim == pytest.approx(1.0, abs=1e-5)


def test_top_k_match_country_clamps_to_in_country_count():
    bank = _multi_country_bank()
    # Only 1 IT anchor; asking for top_k=5 should yield exactly 1.
    matches = top_k_match_country(bank.matrix[0], bank, target_country="it", top_k=5)
    assert len(matches) == 1
    assert matches[0].eurio_id.startswith("it")


def test_top_k_match_country_rejects_dim_mismatch():
    bank = _multi_country_bank()
    with pytest.raises(ValueError, match="dim"):
        top_k_match_country(np.zeros(7, dtype=np.float32), bank, target_country="ad")


def test_top_k_match_country_returns_empty_on_blank_target():
    bank = _multi_country_bank()
    assert top_k_match_country(bank.matrix[0], bank, target_country="") == []


# ---------------------------------------------------------------------------
# Anchor bank persistence
# ---------------------------------------------------------------------------


def test_anchor_bank_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("training.foundation.anchors.STATE_DIR", tmp_path)
    bank = _fixture_bank()
    bank.anchors_kind = "roundtrip_test"
    saved_path = save_anchors(bank)
    assert saved_path.exists()

    loaded = load_anchors("roundtrip_test", bank.encoder_version)
    assert loaded is not None
    assert loaded.eurio_ids == bank.eurio_ids
    assert loaded.encoder_version == bank.encoder_version
    assert loaded.anchors_kind == bank.anchors_kind
    np.testing.assert_array_almost_equal(loaded.matrix, bank.matrix)


def test_load_anchors_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("training.foundation.anchors.STATE_DIR", tmp_path)
    assert load_anchors("does_not_exist") is None


# ---------------------------------------------------------------------------
# Slow integration test (gated)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_encode_image_returns_normalized_vec():
    """Loads DINOv2 (downloads weights on first call) and encodes a grey square.

    Skipped by default — opt in with `-m slow` to actually pay the
    model download / load cost.
    """
    from training.foundation import encode_image

    img = Image.new("RGB", (256, 256), color=(120, 120, 120))
    vec = encode_image(img)
    assert vec.dtype == np.float32
    assert vec.ndim == 1
    assert vec.shape[0] == 384  # ViT-S/14 hidden dim
    assert float(np.linalg.norm(vec)) == pytest.approx(1.0, abs=1e-3)
