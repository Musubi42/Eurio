"""Compose augmentors from a recipe and produce N variations per source image."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from augmentations.base import Augmentor
from augmentations.overlays import OverlayAugmentor
from augmentations.perspective import PerspectiveAugmentor
from augmentations.relighting import RelightingAugmentor

logger = logging.getLogger(__name__)

_DISPATCH: dict[str, type[Augmentor]] = {
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
