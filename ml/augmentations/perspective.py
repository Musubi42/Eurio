"""Perspective warp (tilt) augmentor.

The user's camera is never perfectly perpendicular to the coin. We simulate
that by tilting the image in 3D via a homography.

We use ``cv2.warpPerspective`` when OpenCV is available (it ships in the
project's Nix env at ``cv2 4.11``). This is more flexible than
``torchvision.transforms.functional.perspective`` because we control the
homography from explicit tilt angles on X and Y. torchvision is kept as a
fallback purely as a defensive measure — in the current env we always take
the cv2 path.
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from augmentations.base import PROBABILITY_SCHEMA, Augmentor, LayerSchema

logger = logging.getLogger(__name__)

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    logger.warning("cv2 not available, PerspectiveAugmentor will use torchvision fallback")


class PerspectiveAugmentor(Augmentor):
    """Apply a small 3D tilt via homography, filled with white background."""

    def __init__(
        self,
        max_tilt_degrees: float = 15.0,
        probability: float = 0.6,
        **params: object,
    ) -> None:
        super().__init__(probability=probability, **params)
        self.max_tilt_degrees = float(max_tilt_degrees)

    @classmethod
    def get_schema(cls) -> LayerSchema:
        return {
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

    def apply(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        img = img.convert("RGB")
        if _HAS_CV2:
            return self._apply_cv2(img, rng)
        return self._apply_torchvision(img, rng)

    def _sample_tilt(self, rng: np.random.Generator) -> tuple[float, float]:
        tilt_x = float(rng.uniform(-self.max_tilt_degrees, self.max_tilt_degrees))
        tilt_y = float(rng.uniform(-self.max_tilt_degrees, self.max_tilt_degrees))
        return tilt_x, tilt_y

    def _apply_cv2(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        w, h = img.size
        tilt_x, tilt_y = self._sample_tilt(rng)

        # Convert tilt angles into a displacement fraction. A 25° tilt maps to
        # ~25% inward shift at the extreme corners, which matches eyeballed
        # handheld perspective distortion on coin-sized subjects.
        shift_x = (tilt_x / 90.0) * w * 0.5
        shift_y = (tilt_y / 90.0) * h * 0.5

        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = np.float32([
            [0 + max(0, shift_x), 0 + max(0, shift_y)],
            [w - max(0, -shift_x), 0 + max(0, -shift_y)],
            [w - max(0, shift_x), h - max(0, shift_y)],
            [0 + max(0, -shift_x), h - max(0, -shift_y)],
        ])

        homography = cv2.getPerspectiveTransform(src, dst)
        arr = np.asarray(img)
        warped = cv2.warpPerspective(
            arr,
            homography,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
        return Image.fromarray(warped)

    def _apply_torchvision(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        from torchvision.transforms import functional as F  # lazy import

        w, h = img.size
        tilt_x, tilt_y = self._sample_tilt(rng)
        shift_x = int((tilt_x / 90.0) * w * 0.5)
        shift_y = int((tilt_y / 90.0) * h * 0.5)

        startpoints = [[0, 0], [w, 0], [w, h], [0, h]]
        endpoints = [
            [0 + max(0, shift_x), 0 + max(0, shift_y)],
            [w - max(0, -shift_x), 0 + max(0, -shift_y)],
            [w - max(0, shift_x), h - max(0, shift_y)],
            [0 + max(0, -shift_x), h - max(0, -shift_y)],
        ]
        return F.perspective(
            img,
            startpoints=startpoints,
            endpoints=endpoints,
            fill=[255, 255, 255],
        )
