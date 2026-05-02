"""Tests for promote_prod_assets — copy semantics + missing-source guards."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts import promote_prod_assets as p


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    prod_current = tmp_path / "prod" / "current"
    android_assets = tmp_path / "app-android" / "src" / "main" / "assets"
    repo_root = tmp_path
    monkeypatch.setattr(p, "PROD_CURRENT", prod_current)
    monkeypatch.setattr(p, "ANDROID_ASSETS", android_assets)
    monkeypatch.setattr(p, "REPO_ROOT", repo_root)
    monkeypatch.setattr(p, "COPIES", [
        (prod_current / "tflite" / "eurio_embedder_v1.tflite",
         android_assets / "models" / "eurio_embedder_v1.tflite"),
        (prod_current / "embeddings" / "coin_embeddings.json",
         android_assets / "data" / "coin_embeddings.json"),
        (prod_current / "tflite" / "model_meta.json",
         android_assets / "data" / "model_meta.json"),
    ])
    yield {"prod_current": prod_current, "android_assets": android_assets}


def _populate_prod(prod_current: Path) -> None:
    (prod_current / "tflite").mkdir(parents=True)
    (prod_current / "embeddings").mkdir(parents=True)
    (prod_current / "tflite" / "eurio_embedder_v1.tflite").write_bytes(b"\xff" * 64)
    (prod_current / "tflite" / "model_meta.json").write_text("{}")
    (prod_current / "embeddings" / "coin_embeddings.json").write_text("{}")


def test_refuses_when_prod_missing(isolated, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["promote_prod_assets"])
    rc = p.main()
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing" in err
    assert "promote_iteration" in err


def test_copies_all_three_artifacts(isolated, monkeypatch):
    _populate_prod(isolated["prod_current"])
    monkeypatch.setattr("sys.argv", ["promote_prod_assets"])
    rc = p.main()
    assert rc == 0
    assets = isolated["android_assets"]
    assert (assets / "models" / "eurio_embedder_v1.tflite").exists()
    assert (assets / "data" / "coin_embeddings.json").exists()
    assert (assets / "data" / "model_meta.json").exists()
    # Content matches.
    assert (assets / "models" / "eurio_embedder_v1.tflite").read_bytes() == b"\xff" * 64


def test_dry_run_does_not_write(isolated, monkeypatch):
    _populate_prod(isolated["prod_current"])
    monkeypatch.setattr("sys.argv", ["promote_prod_assets", "--dry-run"])
    rc = p.main()
    assert rc == 0
    assets = isolated["android_assets"]
    assert not (assets / "models" / "eurio_embedder_v1.tflite").exists()


def test_partial_prod_state_fails(isolated, monkeypatch):
    pc = isolated["prod_current"]
    (pc / "tflite").mkdir(parents=True)
    (pc / "tflite" / "eurio_embedder_v1.tflite").write_bytes(b"\xff" * 8)
    # Missing model_meta.json + embeddings/coin_embeddings.json
    monkeypatch.setattr("sys.argv", ["promote_prod_assets"])
    rc = p.main()
    assert rc == 3
