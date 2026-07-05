"""Tests for build_cohort_bundle source-routing + meta + helpers (phase 4).

On évite l'intégration complète (Store SQLite + Supabase) et on
verrouille les briques refactorées : `_resolve_source`,
`_infer_class_kind`, et la forme de `bundle_meta.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts import build_cohort_bundle as b


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "LAB_ITERATIONS_DIR", tmp_path / "lab" / "iterations")
    monkeypatch.setattr(b, "PROD_CURRENT", tmp_path / "prod" / "current")
    yield tmp_path


def _populate_iter(root: Path, iid: str) -> Path:
    iter_dir = root / iid
    (iter_dir / "tflite").mkdir(parents=True)
    (iter_dir / "embeddings").mkdir(parents=True)
    (iter_dir / "tflite" / "eurio_embedder_v1.tflite").write_bytes(b"\xff" * 32)
    (iter_dir / "tflite" / "model_meta.json").write_text("{}")
    (iter_dir / "embeddings" / "embeddings_v1.json").write_text(
        json.dumps({"coins": {"a": {}, "b": {}}})
    )
    return iter_dir


def _populate_prod(prod_current: Path, *, iteration_id: str | None) -> None:
    (prod_current / "tflite").mkdir(parents=True)
    (prod_current / "embeddings").mkdir(parents=True)
    (prod_current / "tflite" / "eurio_embedder_v1.tflite").write_bytes(b"\x00" * 32)
    (prod_current / "tflite" / "model_meta.json").write_text("{}")
    (prod_current / "embeddings" / "embeddings_v1.json").write_text(
        json.dumps({"coins": {"x": {}}})
    )
    if iteration_id is not None:
        (prod_current / "promoted_from.json").write_text(
            json.dumps({"iteration_id": iteration_id})
        )


def _ns(**kwargs) -> argparse.Namespace:
    base = {"source": "lab", "cohort": "c1", "iteration": None, "out": "/tmp/x"}
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_resolve_lab_requires_iteration(isolated):
    with pytest.raises(SystemExit, match="--source lab requires --iteration"):
        b._resolve_source(_ns(source="lab", iteration=None), store=None)


def test_resolve_lab_missing_iter_dir(isolated):
    with pytest.raises(SystemExit, match="lab iteration dir missing"):
        b._resolve_source(
            _ns(source="lab", iteration="ghost"), store=None,
        )


def test_resolve_lab_returns_iter_paths(isolated):
    iter_dir = _populate_iter(b.LAB_ITERATIONS_DIR, "iid-1")
    tflite, emb, meta, iid = b._resolve_source(
        _ns(source="lab", iteration="iid-1"), store=None,
    )
    assert tflite == iter_dir / "tflite" / "eurio_embedder_v1.tflite"
    assert emb == iter_dir / "embeddings" / "embeddings_v1.json"
    assert meta == iter_dir / "tflite" / "model_meta.json"
    assert iid == "iid-1"


def test_resolve_prod_missing_dir(isolated):
    with pytest.raises(SystemExit, match="prod/current/ missing"):
        b._resolve_source(_ns(source="prod"), store=None)


def test_resolve_prod_uses_promoted_from(isolated):
    _populate_prod(b.PROD_CURRENT, iteration_id="iid-promoted")
    _, _, _, iid = b._resolve_source(_ns(source="prod"), store=None)
    assert iid == "iid-promoted"


def test_resolve_prod_explicit_iteration_overrides(isolated):
    _populate_prod(b.PROD_CURRENT, iteration_id="iid-promoted")
    _, _, _, iid = b._resolve_source(
        _ns(source="prod", iteration="iid-override"), store=None,
    )
    assert iid == "iid-override"


def test_resolve_prod_no_promoted_meta_no_iteration(isolated):
    _populate_prod(b.PROD_CURRENT, iteration_id=None)
    _, _, _, iid = b._resolve_source(_ns(source="prod"), store=None)
    assert iid is None


def test_infer_class_kind_default():
    assert b._infer_class_kind({}) == "eurio_id"
    assert b._infer_class_kind({"coins": {}}) == "eurio_id"


def test_infer_class_kind_majority():
    emb = {"coins": {
        "a": {"class_kind": "eurio_id"},
        "b": {"class_kind": "eurio_id"},
        "c": {"class_kind": "design_group_id"},
    }}
    assert b._infer_class_kind(emb) == "eurio_id"


def test_infer_class_kind_design_group_majority():
    emb = {"coins": {
        "a": {"class_kind": "design_group_id"},
        "b": {"class_kind": "design_group_id"},
        "c": {"class_kind": "eurio_id"},
    }}
    assert b._infer_class_kind(emb) == "design_group_id"


def test_sha256_changes_on_content_change(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    h1 = b._sha256(p)
    p.write_bytes(b"abd")
    h2 = b._sha256(p)
    assert h1 != h2
    assert len(h1) == 64


def test_build_test_list_samples_large_cohorts():
    ids = [f"coin-{i:03}" for i in range(b.SAMPLE_COIN_THRESHOLD)]
    tests, sampled = b._build_test_list(ids, {})
    assert sampled is True
    assert len(tests) == b.SAMPLED_COIN_COUNT * len(b.TEST_CONDITIONS)


def test_build_test_list_no_sample_prescribes_all():
    # Sessions corpus (scan-quality) : chaque pièce doit être prescrite,
    # même au-delà du seuil OQ-4.
    ids = [f"coin-{i:03}" for i in range(42)]
    tests, sampled = b._build_test_list(ids, {}, no_sample=True)
    assert sampled is False
    assert len(tests) == 42 * len(b.TEST_CONDITIONS)
    assert {t["expected_eurio_id"] for t in tests} == set(ids)


def test_conditions_include_glare_inhand():
    assert {"glare", "inhand"} <= set(b.TEST_CONDITIONS)
