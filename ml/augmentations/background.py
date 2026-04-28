"""Background substitution augmentor.

Numista source images are studio shots on a clean (usually white) background.
The phone scan lands on a wood table, a hand, fabric, paper… anything but a
clean studio backdrop. Without this layer the model learns "studio white =
coin" and degrades the moment it meets a real surface.

This augmentor:
  1. Builds a circular mask centered on the input image (the source coins
     are already centered, the mask matches the coin's silhouette).
  2. Synthesizes a random background image — solid color, gradient, or
     textured noise — sampled from a palette parameterized per zone.
  3. Composites the coin onto the new background using the mask, with a
     slight Gaussian feather so the seam isn't visible.

Sits at the FIRST position of every zone recipe so all subsequent layers
(perspective, relighting, overlays) operate on the realistic-bg variant.
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from augmentations.base import PROBABILITY_SCHEMA, Augmentor, LayerSchema, circular_mask

logger = logging.getLogger(__name__)

PALETTES = ("plain", "gradient", "noise")
"""Three families of synthetic backgrounds.

- ``plain``   : single solid color, sampled from a curated palette
                (wood, grey, cream, dark, beige). Cheapest, used in green
                zone where over-augmentation hurts.
- ``gradient``: linear gradient between two random RGB points.
- ``noise``   : per-pixel random noise with a Gaussian blur — approximates
                fabric / table textures without a real image library.
"""


def _solid_color(size: int, rng: np.random.Generator) -> Image.Image:
    palette = (
        (rng.integers(140, 200), rng.integers(100, 160), rng.integers(60, 120)),  # wood
        (rng.integers(180, 230), rng.integers(180, 230), rng.integers(180, 230)),  # grey
        (rng.integers(230, 255), rng.integers(230, 255), rng.integers(230, 255)),  # white-ish
        (rng.integers(20, 60), rng.integers(20, 60), rng.integers(20, 60)),        # dark
        (rng.integers(160, 200), rng.integers(140, 180), rng.integers(120, 160)),  # beige
    )
    color = palette[int(rng.integers(0, len(palette)))]
    return Image.new("RGB", (size, size), tuple(int(c) for c in color))


def _gradient(size: int, rng: np.random.Generator) -> Image.Image:
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    c1 = np.array([rng.integers(50, 200) for _ in range(3)], dtype=np.float32)
    c2 = np.array([rng.integers(50, 200) for _ in range(3)], dtype=np.float32)
    for y in range(size):
        t = y / size
        arr[y, :] = (c1 * (1.0 - t) + c2 * t).astype(np.uint8)
    return Image.fromarray(arr)


def _noise(size: int, rng: np.random.Generator) -> Image.Image:
    arr = rng.integers(100, 200, (size, size, 3), dtype=np.int16).astype(np.uint8)
    img = Image.fromarray(arr)
    blur_radius = float(rng.uniform(2.0, 5.0))
    return img.filter(ImageFilter.GaussianBlur(radius=blur_radius))


_PALETTE_FUNCS = {
    "plain": _solid_color,
    "gradient": _gradient,
    "noise": _noise,
}


class BackgroundAugmentor(Augmentor):
    """Replace the source background with a synthesized one.

    Numista studio shots have a clean studio backdrop that doesn't exist in
    the wild. This augmentor cuts the coin out via a circular mask and pastes
    it onto a synthetic surface (solid / gradient / textured), so downstream
    augmentations and the trained model never bake in the studio assumption.
    """

    def __init__(
        self,
        palette: list[str] | None = None,
        feather: int = 3,
        probability: float = 1.0,
        **params: object,
    ) -> None:
        super().__init__(probability=probability, **params)
        # Empty list / None falls back to all three palettes.
        chosen = list(palette) if palette else list(PALETTES)
        unknown = [p for p in chosen if p not in _PALETTE_FUNCS]
        if unknown:
            raise ValueError(
                f"unknown background palette(s): {unknown!r} "
                f"(allowed: {sorted(_PALETTE_FUNCS)})"
            )
        self.palette = chosen
        self.feather = int(feather)

    @classmethod
    def get_schema(cls) -> LayerSchema:
        return {
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

    def apply(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        img = img.convert("RGB")
        size = max(img.size)
        # Force square canvas — the source isn't always exactly square but the
        # circular mask + downstream layers assume a square frame.
        if img.size != (size, size):
            square = Image.new("RGB", (size, size), (255, 255, 255))
            offset = ((size - img.size[0]) // 2, (size - img.size[1]) // 2)
            square.paste(img, offset)
            img = square

        choice = self.palette[int(rng.integers(0, len(self.palette)))]
        bg = _PALETTE_FUNCS[choice](size, rng)

        # circular_mask returns float32 [0,1]; PIL expects 'L' uint8 for paste.
        mask = circular_mask(size, feather=self.feather)
        mask_pil = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
        bg.paste(img, (0, 0), mask_pil)
        return bg
