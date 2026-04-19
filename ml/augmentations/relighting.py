"""Re-lighting 2.5D augmentor.

A coin is quasi-planar: relief is a few mm on a 20-30mm diameter disc. On a
Numista studio scan the local luminance is a good proxy for relief altitude
(hollows are dark, high points are lit). So we can derive an approximate
normal map straight from the luminance gradient and re-illuminate the coin
with an arbitrary directional light (Lambertian shading).

This closes the gap between the uniformly-lit studio scan and the user's
handheld capture where a single off-axis light source will light one side
of the relief and shadow the other.

The normal map itself is deterministic for a given source image, so we cache
it per-instance (bounded LRU-ish dict) — a typical run generates 50-150
variations of the same coin and recomputing Sobel each time is pure waste.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from PIL import Image

from augmentations.base import Augmentor, circular_mask

logger = logging.getLogger(__name__)

_MIN_SIDE = 64
_NORMAL_CACHE_MAX = 4


class RelightingAugmentor(Augmentor):
    """Re-light a coin by deriving a normal map from luminance + Lambertian shading."""

    def __init__(
        self,
        probability: float = 0.6,
        ambient: float = 0.35,
        max_elevation_deg: float = 60.0,
        min_elevation_deg: float = 15.0,
        intensity_range: tuple[float, float] = (0.6, 1.1),
        normal_strength: float = 1.5,
        smooth_sigma: float = 2.0,
        **params: object,
    ) -> None:
        super().__init__(probability=probability, **params)
        if not 0.0 <= ambient <= 1.0:
            raise ValueError(f"ambient must be in [0, 1], got {ambient}")
        if min_elevation_deg >= max_elevation_deg:
            raise ValueError(
                "min_elevation_deg must be < max_elevation_deg "
                f"(got {min_elevation_deg} / {max_elevation_deg})"
            )
        self.ambient = float(ambient)
        self.min_elevation_deg = float(min_elevation_deg)
        self.max_elevation_deg = float(max_elevation_deg)
        self.intensity_range = (
            float(intensity_range[0]),
            float(intensity_range[1]),
        )
        self.normal_strength = float(normal_strength)
        self.smooth_sigma = float(smooth_sigma)
        self._normal_cache: dict[int, np.ndarray] = {}
        self._cache_order: list[int] = []

    # ------------------------------------------------------------------
    # Normal map (deterministic) — cached per source image.
    # ------------------------------------------------------------------

    def _compute_normal_map(self, rgb: np.ndarray) -> np.ndarray:
        # Luminance via Rec.601 weights. Keep float32 throughout — uint8 would
        # lose precision for the Gaussian + Sobel cascade.
        lum = (
            0.299 * rgb[..., 0]
            + 0.587 * rgb[..., 1]
            + 0.114 * rgb[..., 2]
        ).astype(np.float32)

        if self.smooth_sigma > 0:
            # cv2.GaussianBlur derives its kernel size from sigma when ksize=(0,0).
            lum = cv2.GaussianBlur(lum, (0, 0), sigmaX=self.smooth_sigma)

        dx = cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3)
        dy = cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3)

        nx = -dx * self.normal_strength
        ny = -dy * self.normal_strength
        nz = np.ones_like(nx, dtype=np.float32)

        norm = np.sqrt(nx * nx + ny * ny + nz * nz)
        norm = np.maximum(norm, 1e-6)
        normal = np.stack([nx / norm, ny / norm, nz / norm], axis=-1)
        return normal

    def _get_normal_map(self, rgb: np.ndarray) -> np.ndarray:
        # Hash a strided sample of the array: id() is unsafe because PIL-backed
        # numpy buffers can share ids across images, but hashing every pixel is
        # needlessly slow. A strided sample is both stable and fast enough.
        key = hash((
            rgb.shape,
            rgb.dtype.str,
            bytes(rgb[::max(1, rgb.shape[0] // 16), ::max(1, rgb.shape[1] // 16)].tobytes()),
        ))
        cached = self._normal_cache.get(key)
        if cached is not None:
            return cached

        normal = self._compute_normal_map(rgb)
        self._normal_cache[key] = normal
        self._cache_order.append(key)
        if len(self._cache_order) > _NORMAL_CACHE_MAX:
            evicted = self._cache_order.pop(0)
            self._normal_cache.pop(evicted, None)
        return normal

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        img = img.convert("RGB")
        w, h = img.size
        if min(w, h) < _MIN_SIDE:
            logger.debug(
                "Skipping relighting: image too small (%dx%d < %d)",
                w, h, _MIN_SIDE,
            )
            return img

        rgb = np.asarray(img, dtype=np.uint8)
        rgb_f = rgb.astype(np.float32)

        normal = self._get_normal_map(rgb_f)

        azim = float(rng.uniform(0.0, 2.0 * np.pi))
        elev = float(rng.uniform(
            np.deg2rad(self.min_elevation_deg),
            np.deg2rad(self.max_elevation_deg),
        ))
        # Elevation is the angle above the coin plane; nz=sin(elev) keeps the
        # light in the upper hemisphere so we never shade the coin from below.
        lx = np.cos(elev) * np.cos(azim)
        ly = np.cos(elev) * np.sin(azim)
        lz = np.sin(elev)
        light = np.array([lx, ly, lz], dtype=np.float32)

        shade = np.clip(normal @ light, 0.0, None)
        shade = self.ambient + (1.0 - self.ambient) * shade
        intensity = float(rng.uniform(*self.intensity_range))
        shade = shade * intensity

        shaded = rgb_f * shade[..., None]

        mask = circular_mask(max(h, w))[:h, :w][..., None]
        out = rgb_f * (1.0 - mask) + shaded * mask
        out = np.clip(out, 0.0, 255.0).astype(np.uint8)
        return Image.fromarray(out)
