"""Unit tests for PRD Bloc 1 — augmentation engine + Store extensions.

Run: `.venv/bin/python -m pytest ml/tests/test_augmentation.py -q`
or :   `.venv/bin/python ml/tests/test_augmentation.py`
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from augmentations import (  # noqa: E402
    AugmentationPipeline,
    RecipeValidationError,
    ZONE_RECIPES,
    list_layer_schemas,
    validate_recipe,
)
from state import AugmentationRecipeRow, ClassRef, Store  # noqa: E402


# ─── introspection ──────────────────────────────────────────────────────────


def test_list_layer_schemas_covers_all_layer_types():
    schemas = list_layer_schemas()
    types = {s["type"] for s in schemas}
    assert types == {"perspective", "relighting", "overlays"}
    for s in schemas:
        assert s["label"]
        assert s["description"]
        # probability is injected as the first param of every layer.
        names = [p["name"] for p in s["params"]]
        assert names[0] == "probability"


def test_schema_bounds_are_populated():
    schemas = {s["type"]: s for s in list_layer_schemas()}

    perspective_params = {p["name"]: p for p in schemas["perspective"]["params"]}
    assert perspective_params["max_tilt_degrees"]["max"] == 45.0

    relighting_params = {p["name"]: p for p in schemas["relighting"]["params"]}
    assert relighting_params["ambient"]["min"] == 0.0
    assert relighting_params["ambient"]["max"] == 1.0
    assert relighting_params["intensity_range"]["length"] == 2

    overlays_params = {p["name"]: p for p in schemas["overlays"]["params"]}
    assert set(overlays_params["categories"]["options"]) == {
        "patina", "dust", "scratches", "fingerprints",
    }


# ─── recipe validation ──────────────────────────────────────────────────────


def test_zone_recipes_pass_validation():
    for zone, recipe in ZONE_RECIPES.items():
        validate_recipe(recipe)  # should not raise


def test_unknown_layer_type_rejected():
    with pytest.raises(RecipeValidationError) as exc:
        validate_recipe({"layers": [{"type": "hallucinated"}]})
    assert "unknown layer type" in str(exc.value)


def test_unknown_param_rejected():
    with pytest.raises(RecipeValidationError) as exc:
        validate_recipe(
            {"layers": [{"type": "perspective", "wat": 1.0}]}
        )
    assert exc.value.param == "wat"


def test_out_of_bounds_param_rejected():
    with pytest.raises(RecipeValidationError) as exc:
        validate_recipe(
            {"layers": [{"type": "relighting", "ambient": 1.5}]}
        )
    assert exc.value.layer == "relighting"
    assert exc.value.param == "ambient"


def test_probability_out_of_bounds_rejected():
    with pytest.raises(RecipeValidationError) as exc:
        validate_recipe(
            {"layers": [{"type": "perspective", "probability": 1.5}]}
        )
    assert exc.value.param == "probability"


def test_list_length_mismatch_rejected():
    with pytest.raises(RecipeValidationError):
        validate_recipe(
            {
                "layers": [
                    {"type": "relighting", "intensity_range": [0.5, 0.7, 0.9]}
                ]
            }
        )


def test_list_param_out_of_bounds_rejected():
    with pytest.raises(RecipeValidationError):
        validate_recipe(
            {
                "layers": [
                    {"type": "overlays", "opacity_range": [0.2, 5.0]}
                ]
            }
        )


def test_string_option_not_allowed_rejected():
    with pytest.raises(RecipeValidationError):
        validate_recipe(
            {
                "layers": [
                    {"type": "overlays", "categories": ["not-a-real-category"]}
                ]
            }
        )


# ─── pipeline determinism ───────────────────────────────────────────────────


def _dummy_image(size: int = 256) -> Image.Image:
    # Simple radial gradient so Sobel / overlays have something to bite on.
    img = Image.new("RGB", (size, size), (128, 128, 128))
    for y in range(size):
        for x in range(size):
            r = int(((x - size // 2) ** 2 + (y - size // 2) ** 2) ** 0.5)
            v = max(0, min(255, 255 - r))
            img.putpixel((x, y), (v, v, v))
    return img


def test_pipeline_deterministic_with_seed():
    img = _dummy_image(128)
    recipe = ZONE_RECIPES["green"]

    a = AugmentationPipeline(recipe, seed=42).generate(img, count=4)
    b = AugmentationPipeline(recipe, seed=42).generate(img, count=4)
    assert len(a) == len(b) == 4
    for ia, ib in zip(a, b):
        assert ia.tobytes() == ib.tobytes()


def test_pipeline_different_seeds_diverge():
    img = _dummy_image(128)
    recipe = ZONE_RECIPES["green"]
    a = AugmentationPipeline(recipe, seed=42).generate(img, count=2)
    b = AugmentationPipeline(recipe, seed=43).generate(img, count=2)
    # At least one image differs — perspective uses RNG.
    assert any(ia.tobytes() != ib.tobytes() for ia, ib in zip(a, b))


# ─── Store extensions ───────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def test_store_recipe_crud(store: Store):
    recipe = AugmentationRecipeRow(
        id="abc123",
        name="test-recipe",
        zone="orange",
        config=ZONE_RECIPES["orange"],
    )
    store.create_recipe(recipe)

    by_id = store.get_recipe("abc123")
    by_name = store.get_recipe("test-recipe")
    assert by_id is not None and by_name is not None
    assert by_id.id == by_name.id == "abc123"
    assert by_id.name == "test-recipe"
    assert by_id.zone == "orange"

    store.update_recipe("abc123", name="test-recipe-v2", zone="red")
    updated = store.get_recipe("abc123")
    assert updated and updated.name == "test-recipe-v2"
    assert updated.zone == "red"

    all_red = store.list_recipes(zone="red")
    assert any(r.id == "abc123" for r in all_red)

    assert store.delete_recipe("abc123") is True
    assert store.get_recipe("abc123") is None


def test_store_stage_classes_with_recipe_ids(store: Store):
    recipe = AugmentationRecipeRow(
        id="r1",
        name="r-one",
        zone="red",
        config=ZONE_RECIPES["red"],
    )
    store.create_recipe(recipe)

    items = [
        ClassRef("fr-2e-2007", "eurio_id"),
        ClassRef("de-2e-2005", "eurio_id"),
    ]
    store.stage_classes(items, aug_recipe_ids=["r1", None])

    staged = store.list_staging_with_recipe()
    assert len(staged) == 2
    recipe_by_class = {ref.class_id: rid for ref, rid in staged}
    assert recipe_by_class["fr-2e-2007"] == "r1"
    assert recipe_by_class["de-2e-2005"] is None


def test_store_stage_classes_without_recipe_ids_is_legacy(store: Store):
    """Non-regression: legacy callers that don't pass aug_recipe_ids still work."""
    items = [ClassRef("fr-2e-2007", "eurio_id")]
    store.stage_classes(items)
    staged = store.list_staging_with_recipe()
    assert len(staged) == 1
    ref, recipe_id = staged[0]
    assert ref.class_id == "fr-2e-2007"
    assert recipe_id is None


def test_store_create_run_with_aug_recipe(store: Store):
    recipe = AugmentationRecipeRow(
        id="r1", name="r-one", zone="red", config=ZONE_RECIPES["red"],
    )
    store.create_recipe(recipe)

    from state import RunRow

    row = RunRow(
        id="run1",
        version=1,
        status="queued",
        config={"epochs": 1},
        aug_recipe_id="r1",
    )
    store.create_run(row)
    fetched = store.get_run("run1")
    assert fetched is not None
    assert fetched.aug_recipe_id == "r1"

    store.update_run_aug_recipe("run1", None)
    refetched = store.get_run("run1")
    assert refetched and refetched.aug_recipe_id is None


def test_store_prune_aug_runs(store: Store):
    from state import AugmentationRunRow

    store.create_aug_run(
        AugmentationRunRow(
            id="old",
            recipe_id=None,
            eurio_id="x",
            design_group_id=None,
            count=1,
            seed=None,
            output_dir="output/augmentation_previews/old",
            status="completed",
        )
    )
    # TTL=0s → everything already expired.
    removed = store.prune_aug_runs_older_than(seconds=0)
    assert any(r.id == "old" for r in removed)
    assert store.get_aug_run("old") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
