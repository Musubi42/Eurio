"""Compose augmentors from a recipe and produce N variations per source image."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from training.augmentations.background import BackgroundAugmentor
from training.augmentations.base import Augmentor
from training.augmentations.overlays import OverlayAugmentor
from training.augmentations.perspective import PerspectiveAugmentor
from training.augmentations.relighting import RelightingAugmentor

# Schéma + validation vivent désormais dans le module PUR
# ``shared.augmentation_recipe`` (sans numpy/PIL/cv2) pour être servis par le
# CRUD recettes léger (eurio-api). Ré-export ici pour ne pas casser les imports
# historiques (``from training.augmentations.pipeline import validate_recipe``)
# ni ``training.augmentations.__init__``.
from shared.augmentation_recipe import (  # noqa: F401  (re-export)
    RecipeValidationError,
    list_layer_schemas,
    validate_recipe,
)

logger = logging.getLogger(__name__)

_DISPATCH: dict[str, type[Augmentor]] = {
    "background": BackgroundAugmentor,
    "perspective": PerspectiveAugmentor,
    "relighting": RelightingAugmentor,
    "overlays": OverlayAugmentor,
}


class AugmentationPipeline:
    """Instantiate augmentors from a recipe dict and generate variations.

    The RNG is seeded once at pipeline construction so re-running with the
    same ``seed`` yields identical outputs (useful for regression tests on
    the preview grid).
    """

    def __init__(self, recipe: dict, seed: int | None = None) -> None:
        self.recipe = recipe
        self.default_count = int(recipe.get("count", 16))
        self.augmentors: list[Augmentor] = []
        for layer in recipe.get("layers", []):
            layer_type = layer.get("type")
            if layer_type not in _DISPATCH:
                raise ValueError(f"Unknown augmentor type: {layer_type!r}")
            cls = _DISPATCH[layer_type]
            kwargs = {k: v for k, v in layer.items() if k != "type"}
            self.augmentors.append(cls(**kwargs))
        self.rng = np.random.default_rng(seed)

    def generate(
        self,
        base_img: Image.Image,
        count: int | None = None,
    ) -> list[Image.Image]:
        n = int(count) if count is not None else self.default_count
        out: list[Image.Image] = []
        for _ in range(n):
            img = base_img.convert("RGB")
            for aug in self.augmentors:
                img = aug.maybe_apply(img, self.rng)
            out.append(img)
        return out
