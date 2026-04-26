"""Unit tests for Lab — Store CRUD + pure logic (verdict, delta, sensitivity).

API-level tests live in `test_lab_api.py`. The IterationRunner subprocess
chain is not exercised here (it shells out); we unit-test its pure helpers
and the pieces of state it manipulates.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from state import ExperimentCohortRow, ExperimentIterationRow, Store  # noqa: E402


# ─── Store CRUD ─────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.db")


def _cohort(store: Store, name: str = "c1", eurio_ids=("a", "b")) -> str:
    cid = name.replace("-", "") + "id"
    store.create_cohort(
        ExperimentCohortRow(id=cid, name=name, zone="green", eurio_ids=list(eurio_ids))
    )
    return cid


def _iteration(
    store: Store, cohort_id: str, iid: str,
    parent: str | None = None, variant_count: int = 100,
    recipe_id: str | None = None,
) -> None:
    store.create_iteration(
        ExperimentIterationRow(
            id=iid,
            cohort_id=cohort_id,
            parent_iteration_id=parent,
            name=iid,
            variant_count=variant_count,
            training_config={"epochs": 40},
            recipe_id=recipe_id,
            status="pending",
        )
    )


def test_cohort_crud(store: Store):
    cid = _cohort(store, "green-v1", eurio_ids=("fr-2007", "de-2005"))
    got = store.get_cohort(cid)
    assert got is not None and got.name == "green-v1"
    assert store.get_cohort("green-v1").id == cid
    store.update_cohort(cid, description="calibrage zone verte")
    assert store.get_cohort(cid).description == "calibrage zone verte"
    assert len(store.list_cohorts(zone="green")) == 1
    assert len(store.list_cohorts(zone="red")) == 0
    assert store.delete_cohort(cid) is True
    assert store.get_cohort(cid) is None


def test_iteration_cascade_on_cohort_delete(store: Store):
    cid = _cohort(store, "c")
    _iteration(store, cid, "it-1")
    _iteration(store, cid, "it-2", parent="it-1")
    assert len(store.list_iterations(cohort_id=cid)) == 2
    store.delete_cohort(cid)
    assert store.get_iteration("it-1") is None
    assert store.get_iteration("it-2") is None


def test_iteration_parent_frees_when_deleted(store: Store):
    cid = _cohort(store, "c")
    _iteration(store, cid, "it-1")
    _iteration(store, cid, "it-2", parent="it-1")
    store.delete_iteration("it-1")
    # parent FK SET NULL → it-2 still exists with parent_iteration_id=None
    it2 = store.get_iteration("it-2")
    assert it2 is not None
    assert it2.parent_iteration_id is None


def test_iteration_update_transitions_status(store: Store):
    cid = _cohort(store, "c")
    _iteration(store, cid, "it")
    store.update_iteration("it", status="training", training_run_id=None)
    assert store.get_iteration("it").status == "training"
    store.update_iteration(
        "it",
        status="completed",
        verdict="better",
        delta_vs_parent={"r_at_1": 0.03},
        diff_from_parent={"variant_count": {"before": 100, "after": 200}},
    )
    it = store.get_iteration("it")
    assert it.verdict == "better"
    assert it.delta_vs_parent == {"r_at_1": 0.03}
    assert it.diff_from_parent == {"variant_count": {"before": 100, "after": 200}}


def test_list_iterations_filters_and_orders(store: Store):
    cid = _cohort(store, "c")
    _iteration(store, cid, "it-1")
    _iteration(store, cid, "it-2")
    _iteration(store, cid, "it-3")
    store.update_iteration("it-2", status="training")
    all_items = store.list_iterations(cohort_id=cid)
    assert [i.id for i in all_items] == ["it-1", "it-2", "it-3"]  # creation order
    training = store.list_iterations(cohort_id=cid, status="training")
    assert [i.id for i in training] == ["it-2"]


# ─── Verdict / delta / sensitivity (pure) ───────────────────────────────────


def test_verdict_matrix():
    from api.iteration_logic import compute_verdict

    # Baseline
    assert compute_verdict({"r_at_1": 0.8}, None) == "baseline"

    # No change
    assert compute_verdict({"r_at_1": 0.801}, {"r_at_1": 0.800}) == "no_change"

    # Better — clean
    assert compute_verdict({"r_at_1": 0.85}, {"r_at_1": 0.80}) == "better"

    # Better global BUT a zone regresses → mixed
    assert compute_verdict(
        {"r_at_1": 0.85, "per_zone": {"red": {"r_at_1": 0.70}}},
        {"r_at_1": 0.80, "per_zone": {"red": {"r_at_1": 0.80}}},
    ) == "mixed"

    # Worse
    assert compute_verdict({"r_at_1": 0.74}, {"r_at_1": 0.80}) == "worse"

    # Middle band with zone disagreement
    assert compute_verdict(
        {"r_at_1": 0.81, "per_zone": {"green": {"r_at_1": 0.95}, "red": {"r_at_1": 0.70}}},
        {"r_at_1": 0.80, "per_zone": {"green": {"r_at_1": 0.88}, "red": {"r_at_1": 0.80}}},
    ) == "mixed"


def test_delta_handles_none_parent_and_common_coins():
    from api.iteration_logic import compute_delta

    assert compute_delta({"r_at_1": 0.8}, None) == {}

    d = compute_delta(
        {
            "r_at_1": 0.85, "r_at_3": 0.95, "r_at_5": 0.99,
            "per_zone": {"green": {"r_at_1": 0.90}, "red": {"r_at_1": 0.75}},
            "per_coin": [
                {"eurio_id": "fr-2007", "r_at_1": 1.0},
                {"eurio_id": "de-2005", "r_at_1": 0.60},
            ],
        },
        {
            "r_at_1": 0.80, "r_at_3": 0.94, "r_at_5": 0.99,
            "per_zone": {"green": {"r_at_1": 0.85}, "red": {"r_at_1": 0.75}},
            "per_coin": [
                {"eurio_id": "fr-2007", "r_at_1": 0.80},
                {"eurio_id": "de-2005", "r_at_1": 0.50},
            ],
        },
    )
    assert d["r_at_1"] == 0.05
    assert d["r_at_5"] == 0.0
    assert d["per_zone"]["green"] == 0.05
    assert d["per_zone"]["red"] == 0.0
    assert d["per_coin"]["fr-2007"] == 0.2
    assert d["per_coin"]["de-2005"] == 0.1


def test_input_diff_flattens_recipe_layers():
    from api.iteration_logic import compute_input_diff

    diff = compute_input_diff(
        {
            "variant_count": 200,
            "training_config": {"epochs": 60, "batch_size": 256},
            "recipe": {"layers": [
                {"type": "perspective", "max_tilt_degrees": 25},
                {"type": "overlays", "opacity_range": [0.1, 0.3]},
            ]},
        },
        {
            "variant_count": 100,
            "training_config": {"epochs": 40, "batch_size": 256},
            "recipe": {"layers": [
                {"type": "perspective", "max_tilt_degrees": 15},
                {"type": "overlays", "opacity_range": [0.1, 0.3]},
            ]},
        },
    )
    assert diff["variant_count"] == {"before": 100, "after": 200}
    assert diff["training_config.epochs"] == {"before": 40, "after": 60}
    assert "training_config.batch_size" not in diff  # unchanged
    assert "recipe.perspective.max_tilt_degrees" in diff
    assert "recipe.overlays.opacity_range" not in diff  # unchanged


def test_sensitivity_averages_deltas_per_path():
    from api.iteration_logic import compute_sensitivity

    # Two iterations where variant_count doubled and R@1 gained 3pts and 2pts
    sens = compute_sensitivity([
        ({"variant_count": 200, "training_config": {}, "recipe": {}},
         {"variant_count": 100, "training_config": {}, "recipe": {}},
         {"r_at_1": 0.83}, {"r_at_1": 0.80}),
        ({"variant_count": 400, "training_config": {}, "recipe": {}},
         {"variant_count": 200, "training_config": {}, "recipe": {}},
         {"r_at_1": 0.85}, {"r_at_1": 0.83}),
        # A third iteration that touched epochs only (regression)
        ({"variant_count": 400, "training_config": {"epochs": 80}, "recipe": {}},
         {"variant_count": 400, "training_config": {"epochs": 40}, "recipe": {}},
         {"r_at_1": 0.81}, {"r_at_1": 0.85}),
    ])
    paths = {s.path: s for s in sens}
    assert "variant_count" in paths
    assert paths["variant_count"].observations == 2
    assert paths["variant_count"].direction == "+"
    assert "training_config.epochs" in paths
    assert paths["training_config.epochs"].direction == "-"
    # Sorted by |delta| descending
    assert abs(sens[0].avg_delta_r1) >= abs(sens[-1].avg_delta_r1)
