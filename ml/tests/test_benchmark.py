"""Unit tests for the benchmark pieces (Bloc 3).

Covers Store CRUD on `benchmark_runs`, the `check_real_photos` validator,
the hold-out gate in `train_embedder`, and the `evaluate_real_photos`
aggregation helpers. No FastAPI routes here — see `test_benchmark_api.py`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from state import BenchmarkRunRow, Store  # noqa: E402


# ─── Store ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.db")


def _mk_run(**over) -> BenchmarkRunRow:
    base = BenchmarkRunRow(
        id="r-1",
        model_path="ml/checkpoints/best.pth",
        model_name="arcface_v4_green",
        eurio_ids=["fr-2007-2eur"],
        zones=["green"],
        num_photos=8,
        num_coins=1,
        r_at_1=0.8,
        r_at_3=0.9,
        r_at_5=1.0,
        mean_spread=0.2,
        per_zone={"green": {"r_at_1": 0.8, "num_photos": 8}},
        per_coin=[{"eurio_id": "fr-2007-2eur", "r_at_1": 0.8, "num_photos": 8}],
        confusion={"fr-2007-2eur": {"fr-2007-2eur": 7}},
        top_confusions=[],
        report_path="ml/reports/r-1.json",
        status="running",
    )
    return replace(base, **over)


def test_store_create_get_delete(store: Store):
    store.create_benchmark_run(_mk_run())
    got = store.get_benchmark_run("r-1")
    assert got is not None
    assert got.r_at_1 == 0.8
    assert got.eurio_ids == ["fr-2007-2eur"]
    assert store.count_benchmark_runs() == 1
    deleted = store.delete_benchmark_run("r-1")
    assert deleted is not None
    assert store.get_benchmark_run("r-1") is None


def test_store_update_completes_run(store: Store):
    store.create_benchmark_run(_mk_run())
    store.update_benchmark_run(
        "r-1",
        status="completed",
        r_at_1=0.95,
        finished_at="2026-04-19T12:00:00Z",
    )
    got = store.get_benchmark_run("r-1")
    assert got.status == "completed"
    assert got.r_at_1 == 0.95
    assert got.finished_at == "2026-04-19T12:00:00Z"


def test_store_list_filters_by_zone(store: Store):
    store.create_benchmark_run(_mk_run(id="g", zones=["green"]))
    store.create_benchmark_run(_mk_run(id="o", zones=["orange"]))
    store.create_benchmark_run(_mk_run(id="gr", zones=["green", "red"]))
    rows = store.list_benchmark_runs(zone="green")
    assert {r.id for r in rows} == {"g", "gr"}
    rows = store.list_benchmark_runs(zone="orange")
    assert {r.id for r in rows} == {"o"}


def test_store_list_filters_by_model_and_recipe(store: Store):
    # FK: benchmark_runs.recipe_id → augmentation_recipes.id. Create two
    # real recipes to back the IDs we filter on.
    from state import AugmentationRecipeRow

    store.create_recipe(
        AugmentationRecipeRow(id="rX", name="rx", zone="green", config={"layers": []})
    )
    store.create_recipe(
        AugmentationRecipeRow(id="rY", name="ry", zone="green", config={"layers": []})
    )

    store.create_benchmark_run(_mk_run(id="a", model_name="mA", recipe_id="rX"))
    store.create_benchmark_run(_mk_run(id="b", model_name="mA", recipe_id="rY"))
    store.create_benchmark_run(_mk_run(id="c", model_name="mB", recipe_id="rX"))
    assert {r.id for r in store.list_benchmark_runs(model_name="mA")} == {"a", "b"}
    assert {r.id for r in store.list_benchmark_runs(recipe_id="rX")} == {"a", "c"}


# ─── Hold-out gate ─────────────────────────────────────────────────────────


def test_hold_out_gate_rejects_real_photos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Redirect REAL_PHOTOS_DIR to our tmpdir so we can construct paths under it.
    import train_embedder as te

    fake_root = (tmp_path / "real_photos").resolve()
    fake_root.mkdir()
    (fake_root / "fr-2007-2eur").mkdir()
    monkeypatch.setattr(te, "REAL_PHOTOS_DIR", fake_root)

    # Allowed: anywhere else
    te._assert_no_real_photos(str(tmp_path / "eurio-poc" / "train"), role="train")

    # Denied: under real_photos root
    with pytest.raises(SystemExit) as exc:
        te._assert_no_real_photos(str(fake_root / "fr-2007-2eur"), role="train")
    assert "Data leak" in str(exc.value)


# ─── check_real_photos ──────────────────────────────────────────────────────


def test_check_real_photos_flags_single_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import check_real_photos as crp

    # No Supabase in tests.
    monkeypatch.setattr(crp, "_fetch_zones", lambda ids: {})

    root = tmp_path / "real_photos"
    root.mkdir()
    coin = root / "fr-2007-2eur"
    coin.mkdir()
    Image.new("RGB", (1024, 1024), (200, 200, 200)).save(
        coin / "01_natural-direct_wood_0deg.jpg"
    )
    Image.new("RGB", (400, 400)).save(coin / "02_natural-direct_wood_15deg.jpg")

    coverages, summary = crp.scan_library(root)
    assert summary["num_coins"] == 1
    assert summary["num_photos"] == 2
    c = coverages[0]
    assert c.eurio_id == "fr-2007-2eur"
    # Both photos share session (natural-direct|wood) → flagged.
    assert any("distinct session" in w for w in c.warnings)
    # Low-res photo warned.
    assert any("below 800px" in w for w in c.warnings)

    # Write manifest and re-read it.
    manifest = crp._write_manifest(coverages, summary, root)
    data = json.loads(manifest.read_text())
    assert data["summary"]["num_photos"] == 2
    assert len(data["coins"]) == 1


# ─── evaluate_real_photos aggregation ──────────────────────────────────────


def test_aggregate_empty_returns_zero_metrics():
    import evaluate_real_photos as erp

    metrics, per_zone, per_coin, per_cond, confusion, top = erp._aggregate([], top_n=5)
    assert metrics["r_at_1"] == 0.0
    assert per_zone == {}
    assert per_coin == []
    assert per_cond == {}
    assert confusion == {}
    assert top == []


def test_aggregate_computes_hits_and_top_confusions():
    import evaluate_real_photos as erp

    results = [
        erp.PhotoResult(
            photo_path=f"ml/data/real_photos/fr-2007/0{i}.jpg",
            ground_truth="fr-2007",
            zone="green",
            top5=[("fr-2007", 0.9), ("de-2005", 0.5)],
            hit_at={1: True, 3: True, 5: True},
        )
        for i in range(3)
    ]
    # Add an incorrect with tight spread
    results.append(
        erp.PhotoResult(
            photo_path="ml/data/real_photos/de-2005/01.jpg",
            ground_truth="de-2005",
            zone="orange",
            top5=[("at-2005", 0.81), ("de-2005", 0.80)],
            hit_at={1: False, 3: True, 5: True},
        )
    )
    metrics, per_zone, per_coin, per_cond, confusion, top = erp._aggregate(results, top_n=5)
    assert metrics["r_at_1"] == pytest.approx(3 / 4)
    assert metrics["r_at_3"] == 1.0
    assert per_zone["green"]["num_photos"] == 3
    assert per_zone["orange"]["num_photos"] == 1
    assert any(r["eurio_id"] == "de-2005" and r["r_at_1"] == 0.0 for r in per_coin)
    assert len(top) == 1
    assert top[0]["ground_truth"] == "de-2005"
    assert top[0]["spread"] == pytest.approx(0.01, abs=1e-6)


def test_aggregate_per_condition_buckets():
    import evaluate_real_photos as erp

    results = [
        erp.PhotoResult(
            photo_path=f"ml/data/real_photos/fr-2007/0{i}.jpg",
            ground_truth="fr-2007",
            zone="green",
            top5=[("fr-2007", 0.9), ("de-2005", 0.5)],
            hit_at={1: True, 3: True, 5: True},
            conditions={"lighting": "natural-direct", "angle": "0deg"},
        )
        for i in range(2)
    ]
    results.append(
        erp.PhotoResult(
            photo_path="ml/data/real_photos/fr-2007/03.jpg",
            ground_truth="fr-2007",
            zone="green",
            top5=[("de-2005", 0.80), ("fr-2007", 0.79)],
            hit_at={1: False, 3: True, 5: True},
            conditions={"lighting": "artificial-warm", "angle": "45deg"},
        )
    )
    _, _, _, per_cond, _, _ = erp._aggregate(results, top_n=5)
    assert "lighting" in per_cond
    assert per_cond["lighting"]["natural-direct"]["r_at_1"] == 1.0
    assert per_cond["lighting"]["artificial-warm"]["r_at_1"] == 0.0
    assert per_cond["angle"]["0deg"]["num_photos"] == 2
    assert per_cond["angle"]["45deg"]["num_photos"] == 1
    # Axes non-représentées absentes.
    assert "state" not in per_cond


def test_centroid_covers_semantics():
    import evaluate_real_photos as erp

    c_group = erp.Centroid(
        class_id="de-1euro-n111",
        class_kind="design_group_id",
        eurio_ids={"de-2002-1eur-standard", "de-2003-1eur-standard"},
        vector=np.ones(8, dtype=np.float32),
    )
    assert c_group.covers("de-2002-1eur-standard")
    assert c_group.covers("de-2003-1eur-standard")
    assert not c_group.covers("fr-2002-1eur-standard")

    c_coin = erp.Centroid(
        class_id="fr-2007-2eur",
        class_kind="eurio_id",
        eurio_ids={"fr-2007-2eur"},
        vector=np.ones(8, dtype=np.float32),
    )
    assert c_coin.covers("fr-2007-2eur")
    assert not c_coin.covers("fr-2008-2eur")


def test_match_topk_orders_by_similarity():
    import evaluate_real_photos as erp

    centroids = [
        erp.Centroid("a", "eurio_id", {"a"}, np.array([1.0, 0.0], dtype=np.float32)),
        erp.Centroid("b", "eurio_id", {"b"}, np.array([0.6, 0.8], dtype=np.float32)),
        erp.Centroid("c", "eurio_id", {"c"}, np.array([0.0, 1.0], dtype=np.float32)),
    ]
    # query aligned with "a"
    query = np.array([1.0, 0.0], dtype=np.float32)
    top = erp.match_topk(query, centroids, k=3)
    assert top[0][0] == "a"
    assert top[0][1] == pytest.approx(1.0)
    assert top[1][0] == "b"
    assert top[2][0] == "c"
