"""Base abstractions shared by every augmentor.

An ``Augmentor`` is a callable-ish object that takes a PIL image and a numpy
``Generator`` (for deterministic RNG) and returns a transformed image. The
pipeline (see ``pipeline.py``) composes several of them in order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


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
    options: list[str] # string / list[string] with a finite set
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


class Augmentor(ABC):
    """Contract for a single augmentation layer.

    Subclasses implement ``apply``. ``maybe_apply`` gates execution on the
    configured probability so the pipeline can compose stochastic steps
    without scattering ``rng.random() < p`` checks everywhere.
    """

    def __init__(self, probability: float = 1.0, **params: object) -> None:
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {probability}")
        self.probability = probability
        self.params = params

    @abstractmethod
    def apply(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        """Apply the transformation unconditionally."""

    def maybe_apply(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        """Apply with the configured probability, else return input unchanged."""
        if self.probability >= 1.0 or rng.random() < self.probability:
            return self.apply(img, rng)
        return img

    @classmethod
    def get_schema(cls) -> LayerSchema:
        """Return a JSON-friendly introspection payload for this Augmentor.

        Subclasses override to declare their own params. The default
        implementation exposes only ``probability`` so a custom Augmentor with
        no extra knobs still yields a valid schema.
        """
        return {
            "type": cls.__name__.replace("Augmentor", "").lower(),
            "label": cls.__name__,
            "description": (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else "",
            "params": [PROBABILITY_SCHEMA],
        }


def circular_mask(size: int, feather: int = 2) -> np.ndarray:
    """Centered circular mask as float32 array in [0, 1].

    Used to keep overlays from leaking outside the coin. A slight Gaussian
    feather softens the edge so blends don't show a harsh ring.
    """
    mask_img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask_img)
    margin = max(1, int(size * 0.02))
    draw.ellipse([margin, margin, size - margin, size - margin], fill=255)
    if feather > 0:
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=feather))
    return np.asarray(mask_img, dtype=np.float32) / 255.0
