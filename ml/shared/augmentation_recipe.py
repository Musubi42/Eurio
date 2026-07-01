"""Augmentation recipe schema + validation — **pure Python, zero heavy deps**.

Single source of truth for:
- the JSON schema of every augmentation layer (params, bounds, options), and
- ``validate_recipe`` — structural + bounds validation of a recipe dict.

Deliberately imports **only** stdlib (``typing``). No numpy / PIL / cv2 / torch.
That is what lets a recipe be pure **metadata** manipulated by the *light*
canonical API (``serving.recipe_routes`` on ``eurio-api``, the single writer),
while the actual pixel work stays in the *heavy* ``training.augmentations``
package served on the local ML API (``:8042``).

The heavy augmentors (``background`` / ``perspective`` / ``relighting`` /
``overlays``) import their ``get_schema()`` payload **from here** — so there is
exactly one definition of each layer's contract, no drift between what the
validator accepts and what the augmentor exposes.
"""

from __future__ import annotations

from typing import TypedDict


class ParamSchema(TypedDict, total=False):
    """JSON-serializable description of one Augmentor param.

    Consumed by ``GET /augmentation/schema`` so the admin Studio can render
    sliders/selects without duplicating bounds. Only ``name``, ``type`` and
    ``default`` are required; the rest are type-dependent.
    """

    name: str
    type: str          # float | int | bool | string | list[float] | list[string]
    default: object
    min: float | int
    max: float | int
    step: float
    length: int        # list[...] only
    options: list[str]  # string / list[string] with a finite set
    description: str


class LayerSchema(TypedDict):
    type: str
    label: str
    description: str
    params: list[ParamSchema]


PROBABILITY_SCHEMA: ParamSchema = {
    "name": "probability",
    "type": "float",
    "default": 1.0,
    "min": 0.0,
    "max": 1.0,
    "step": 0.05,
    "description": "Probabilité d'appliquer ce layer à chaque variation (0 = jamais, 1 = toujours).",
}


# ---------------------------------------------------------------------------
# Finite option sets — the single source of truth shared with the heavy
# augmentors (``background.PALETTES`` / ``overlays.CATEGORIES`` import these).
# ---------------------------------------------------------------------------

PALETTES: tuple[str, ...] = ("plain", "gradient", "noise")
OVERLAY_CATEGORIES: tuple[str, ...] = ("patina", "dust", "scratches", "fingerprints")


# ---------------------------------------------------------------------------
# Per-layer schemas (source of truth — augmentors return these verbatim).
# ---------------------------------------------------------------------------

BACKGROUND_SCHEMA: LayerSchema = {
    "type": "background",
    "label": "Background (cutout + replacement)",
    "description": (
        "Découpe la pièce via un masque circulaire et la repose sur un fond "
        "synthétique. Empêche le modèle d'apprendre le fond studio Numista "
        "comme signature. Les recettes par zone choisissent une palette plus ou "
        "moins agressive."
    ),
    "params": [
        {**PROBABILITY_SCHEMA, "default": 1.0},
        {
            "name": "palette",
            "type": "list[string]",
            "default": list(PALETTES),
            "options": list(PALETTES),
            "description": (
                "Familles de fonds tirées au hasard à chaque variation : "
                "plain (couleur unie), gradient (dégradé linéaire), "
                "noise (texture bruitée floutée)."
            ),
        },
        {
            "name": "feather",
            "type": "int",
            "default": 3,
            "min": 0,
            "max": 10,
            "step": 1,
            "description": "Adoucissement gaussien du bord du masque (px).",
        },
    ],
}

PERSPECTIVE_SCHEMA: LayerSchema = {
    "type": "perspective",
    "label": "Perspective (tilt 3D)",
    "description": (
        "Simule un angle caméra non perpendiculaire à la pièce via une homographie. "
        "Valeur = angle maximum de tilt en degrés sur les axes X et Y."
    ),
    "params": [
        {**PROBABILITY_SCHEMA, "default": 0.6},
        {
            "name": "max_tilt_degrees",
            "type": "float",
            "default": 15.0,
            "min": 0.0,
            "max": 45.0,
            "step": 1.0,
            "description": "Angle maximum de tilt en degrés (tiré uniformément entre -max et +max).",
        },
    ],
}

RELIGHTING_SCHEMA: LayerSchema = {
    "type": "relighting",
    "label": "Re-lighting 2.5D",
    "description": (
        "Re-éclaire la pièce avec une lumière directionnelle dérivée d'un normal map Sobel. "
        "Simule l'angle de prise utilisateur avec une source lumineuse décentrée."
    ),
    "params": [
        {**PROBABILITY_SCHEMA, "default": 0.6},
        {
            "name": "ambient",
            "type": "float",
            "default": 0.35,
            "min": 0.0,
            "max": 1.0,
            "step": 0.05,
            "description": "Lumière ambiante de base (0 = noir dans les ombres, 1 = image plate).",
        },
        {
            "name": "min_elevation_deg",
            "type": "float",
            "default": 15.0,
            "min": 0.0,
            "max": 89.0,
            "step": 1.0,
            "description": "Angle minimum d'élévation de la source lumineuse (doit être < max).",
        },
        {
            "name": "max_elevation_deg",
            "type": "float",
            "default": 60.0,
            "min": 1.0,
            "max": 90.0,
            "step": 1.0,
            "description": "Angle maximum d'élévation de la source lumineuse.",
        },
        {
            "name": "intensity_range",
            "type": "list[float]",
            "default": [0.6, 1.1],
            "min": 0.0,
            "max": 2.0,
            "length": 2,
            "step": 0.05,
            "description": "Plage d'intensité appliquée après shading [min, max].",
        },
        {
            "name": "normal_strength",
            "type": "float",
            "default": 1.5,
            "min": 0.0,
            "max": 3.0,
            "step": 0.05,
            "description": "Amplification de la dérivation du normal map depuis la luminance.",
        },
        {
            "name": "smooth_sigma",
            "type": "float",
            "default": 2.0,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "description": "Sigma du flou gaussien appliqué avant Sobel (lisse les détails fins).",
        },
    ],
}

OVERLAYS_SCHEMA: LayerSchema = {
    "type": "overlays",
    "label": "Overlays (patina / dust / scratches / fingerprints)",
    "description": (
        "Compose 1 à max_layers textures par-dessus la pièce (multiply / screen / overlay). "
        "Simule usure, dépôt, rayures et traces de doigts. Les bancs de textures vivent sous ml/data/overlays/<category>/."
    ),
    "params": [
        {**PROBABILITY_SCHEMA, "default": 0.5},
        {
            "name": "categories",
            "type": "list[string]",
            "default": ["patina", "dust"],
            "options": list(OVERLAY_CATEGORIES),
            "description": "Catégories de textures autorisées pour ce layer.",
        },
        {
            "name": "opacity_range",
            "type": "list[float]",
            "default": [0.10, 0.30],
            "min": 0.0,
            "max": 1.0,
            "length": 2,
            "step": 0.05,
            "description": "Plage d'opacité appliquée à chaque texture [min, max].",
        },
        {
            "name": "max_layers",
            "type": "int",
            "default": 2,
            "min": 1,
            "max": 5,
            "step": 1,
            "description": "Nombre maximum de textures empilées par variation.",
        },
    ],
}


# Stable order respected by the schema endpoint and the admin Studio. Mirrors
# the runtime order of the recipes: background → perspective → relighting → overlays.
_SCHEMA_ORDER: tuple[str, ...] = ("background", "perspective", "relighting", "overlays")

SCHEMA_BY_TYPE: dict[str, LayerSchema] = {
    "background": BACKGROUND_SCHEMA,
    "perspective": PERSPECTIVE_SCHEMA,
    "relighting": RELIGHTING_SCHEMA,
    "overlays": OVERLAYS_SCHEMA,
}


def list_layer_schemas() -> list[LayerSchema]:
    """Introspection payload for all registered layers (stable order)."""
    return [SCHEMA_BY_TYPE[key] for key in _SCHEMA_ORDER]


# ---------------------------------------------------------------------------
# Validation (pure — ported verbatim from the former pipeline.py)
# ---------------------------------------------------------------------------


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
        if layer_type not in SCHEMA_BY_TYPE:
            raise RecipeValidationError(
                f"unknown layer type {layer_type!r}; expected one of {list(SCHEMA_BY_TYPE.keys())}",
                layer=str(layer_type),
            )

        _coerce_probability(layer, layer_type)

        schema = SCHEMA_BY_TYPE[layer_type]
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
