"""Compose augmentors from a recipe and produce N variations per source image."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from augmentations.background import BackgroundAugmentor
from augmentations.base import Augmentor, LayerSchema
from augmentations.overlays import OverlayAugmentor
from augmentations.perspective import PerspectiveAugmentor
from augmentations.relighting import RelightingAugmentor

logger = logging.getLogger(__name__)

_DISPATCH: dict[str, type[Augmentor]] = {
    "background": BackgroundAugmentor,
    "perspective": PerspectiveAugmentor,
    "relighting": RelightingAugmentor,
    "overlays": OverlayAugmentor,
}

# Stable order respected by the schema endpoint and the admin Studio. Mirrors
# the runtime order of the recipes: background → perspective → relighting → overlays.
_SCHEMA_ORDER = ("background", "perspective", "relighting", "overlays")


def list_layer_schemas() -> list[LayerSchema]:
    """Introspection payload for all registered Augmentors (stable order)."""
    return [_DISPATCH[key].get_schema() for key in _SCHEMA_ORDER]


class RecipeValidationError(ValueError):
    """Raised when a recipe fails bounds/type validation."""

    def __init__(self, message: str, *, layer: str | None = None, param: str | None = None) -> None:
        super().__init__(message)
        self.layer = layer
        self.param = param


def _coerce_probability(layer: dict, layer_type: str) -> None:
    if "probability" not in layer:
        return
    p = layer["probability"]
    if not isinstance(p, (int, float)):
        raise RecipeValidationError(
            f"probability must be a number, got {type(p).__name__}",
            layer=layer_type,
            param="probability",
        )
    if not 0.0 <= float(p) <= 1.0:
        raise RecipeValidationError(
            f"probability={p} out of bounds [0, 1]",
            layer=layer_type,
            param="probability",
        )


def _validate_param(layer_type: str, param_schema: dict, value: object) -> None:
    name = param_schema["name"]
    ptype = param_schema["type"]

    if ptype in ("float", "int"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RecipeValidationError(
                f"{name} must be a number, got {type(value).__name__}",
                layer=layer_type,
                param=name,
            )
        v = float(value)
        if "min" in param_schema and v < float(param_schema["min"]):
            raise RecipeValidationError(
                f"{name}={v} < min={param_schema['min']}",
                layer=layer_type,
                param=name,
            )
        if "max" in param_schema and v > float(param_schema["max"]):
            raise RecipeValidationError(
                f"{name}={v} > max={param_schema['max']}",
                layer=layer_type,
                param=name,
            )
    elif ptype == "bool":
        if not isinstance(value, bool):
            raise RecipeValidationError(
                f"{name} must be a bool, got {type(value).__name__}",
                layer=layer_type,
                param=name,
            )
    elif ptype == "string":
        if not isinstance(value, str):
            raise RecipeValidationError(
                f"{name} must be a string, got {type(value).__name__}",
                layer=layer_type,
                param=name,
            )
        options = param_schema.get("options")
        if options and value not in options:
            raise RecipeValidationError(
                f"{name}={value!r} not in allowed options {options}",
                layer=layer_type,
                param=name,
            )
    elif ptype == "list[float]":
        if not isinstance(value, (list, tuple)):
            raise RecipeValidationError(
                f"{name} must be a list, got {type(value).__name__}",
                layer=layer_type,
                param=name,
            )
        length = param_schema.get("length")
        if length is not None and len(value) != length:
            raise RecipeValidationError(
                f"{name} expected length {length}, got {len(value)}",
                layer=layer_type,
                param=name,
            )
        pmin = param_schema.get("min")
        pmax = param_schema.get("max")
        for i, item in enumerate(value):
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                raise RecipeValidationError(
                    f"{name}[{i}] must be a number, got {type(item).__name__}",
                    layer=layer_type,
                    param=name,
                )
            fv = float(item)
            if pmin is not None and fv < float(pmin):
                raise RecipeValidationError(
                    f"{name}[{i}]={fv} < min={pmin}",
                    layer=layer_type,
                    param=name,
                )
            if pmax is not None and fv > float(pmax):
                raise RecipeValidationError(
                    f"{name}[{i}]={fv} > max={pmax}",
                    layer=layer_type,
                    param=name,
                )
    elif ptype == "list[string]":
        if not isinstance(value, list):
            raise RecipeValidationError(
                f"{name} must be a list of strings, got {type(value).__name__}",
                layer=layer_type,
                param=name,
            )
        options = param_schema.get("options")
        for i, item in enumerate(value):
            if not isinstance(item, str):
                raise RecipeValidationError(
                    f"{name}[{i}] must be a string, got {type(item).__name__}",
                    layer=layer_type,
                    param=name,
                )
            if options and item not in options:
                raise RecipeValidationError(
                    f"{name}[{i}]={item!r} not in allowed options {options}",
                    layer=layer_type,
                    param=name,
                )


def validate_recipe(recipe: dict) -> None:
    """Raise RecipeValidationError if recipe shape or bounds are invalid.

    Shape : ``{count?: int, layers: [{type, probability?, ...params}]}``.
    Unknown layer types and unknown params are rejected (fail-loud).
    """
    if not isinstance(recipe, dict):
        raise RecipeValidationError(f"recipe must be a dict, got {type(recipe).__name__}")

    count = recipe.get("count")
    if count is not None and (not isinstance(count, int) or count <= 0):
        raise RecipeValidationError(f"count must be a positive int, got {count!r}")

    layers = recipe.get("layers", [])
    if not isinstance(layers, list):
        raise RecipeValidationError(f"layers must be a list, got {type(layers).__name__}")

    for idx, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise RecipeValidationError(f"layers[{idx}] must be a dict")
        layer_type = layer.get("type")
        if layer_type not in _DISPATCH:
            raise RecipeValidationError(
                f"unknown layer type {layer_type!r}; expected one of {list(_DISPATCH.keys())}",
                layer=str(layer_type),
            )

        _coerce_probability(layer, layer_type)

        schema = _DISPATCH[layer_type].get_schema()
        known_params = {p["name"] for p in schema["params"]}
        for key in layer:
            if key in ("type", "probability"):
                continue
            if key not in known_params:
                raise RecipeValidationError(
                    f"unknown param {key!r} for layer {layer_type!r}; expected one of {sorted(known_params)}",
                    layer=layer_type,
                    param=key,
                )

        for param_schema in schema["params"]:
            name = param_schema["name"]
            if name == "probability":
                continue
            if name in layer:
                _validate_param(layer_type, param_schema, layer[name])


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
