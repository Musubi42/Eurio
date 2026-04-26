"""Advanced 2D augmentation pipeline — Phase 2 of ML scalability plan.

This module layers perspective warp + dirt/patina overlays on top of the
existing legacy pipeline (rotation, color jitter, blur, backgrounds). See
docs/research/ml-scalability-phases/phase-2-augmentation.md for the spec.
Integration with train_embedder.py is intentionally deferred — this first
iteration ships the primitives plus a preview CLI so variations can be
inspected before being wired into training.
"""

from augmentations.base import Augmentor, LayerSchema, ParamSchema, circular_mask
from augmentations.overlays import CATEGORIES as OVERLAY_CATEGORIES, OverlayAugmentor, sanity_check_textures
from augmentations.perspective import PerspectiveAugmentor
from augmentations.pipeline import (
    AugmentationPipeline,
    RecipeValidationError,
    list_layer_schemas,
    validate_recipe,
)
from augmentations.recipes import DEFAULT_RECIPE, ZONE_RECIPES
from augmentations.relighting import RelightingAugmentor

__all__ = [
    "Augmentor",
    "AugmentationPipeline",
    "DEFAULT_RECIPE",
    "LayerSchema",
    "OVERLAY_CATEGORIES",
    "OverlayAugmentor",
    "ParamSchema",
    "PerspectiveAugmentor",
    "RecipeValidationError",
    "RelightingAugmentor",
    "ZONE_RECIPES",
    "circular_mask",
    "list_layer_schemas",
    "sanity_check_textures",
    "validate_recipe",
]
