"""Procedural generator for overlay textures (patina / dust / scratches / fingerprints).

The dirt-overlay bank consumed by ``augmentations.overlays.OverlayAugmentor``
is populated procedurally rather than scraped from CC0 libraries. We trade a
little photographic realism for zero licensing friction, fully deterministic
output (given ``--seed``), and no external download step.

Each category uses a different synthesis strategy chosen to fit its blend mode:

- ``patina``       fractal noise remapped to a bright range (blend=multiply)
- ``dust``         fine grain + sparse dark specks (blend=multiply)
- ``scratches``    random bright lines on a black canvas (blend=screen)
- ``fingerprints`` anisotropic concentric ridges on mid-gray (blend=overlay)

Usage::

    python generate_overlay_textures.py
    python generate_overlay_textures.py --clean --size 1024
    python generate_overlay_textures.py --scratches 20 --seed 7
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

logger = logging.getLogger(__name__)

OVERLAYS_DIR = Path(__file__).parent / "data" / "overlays"

DEFAULT_COUNTS: dict[str, int] = {
    "patina": 18,
    "dust": 14,
    "scratches": 14,
    "fingerprints": 7,
}


def _fractal_noise(
    size: int, rng: np.random.Generator, octaves: int = 5
) -> np.ndarray:
    """Sum Gaussian-blurred white noise at halved scales → 1/f-like fractal."""
    out = np.zeros((size, size), dtype=np.float32)
    amplitude = 1.0
    total = 0.0
    for octave in range(octaves):
        sigma = size / (4.0 * (2**octave))
        layer = gaussian_filter(
            rng.standard_normal((size, size)).astype(np.float32), sigma=sigma
        )
        out += amplitude * layer
        total += amplitude
        amplitude *= 0.5
    out /= total
    out -= out.min()
    denom = float(out.max())
    if denom > 1e-6:
        out /= denom
    return out


def _remap(arr: np.ndarray, low: float, high: float) -> np.ndarray:
    return np.clip(arr * (high - low) + low, 0, 255).astype(np.uint8)


def generate_patina(size: int, rng: np.random.Generator) -> np.ndarray:
    """Bright base with softer darker blotches — simulates tarnish under multiply."""
    noise = _fractal_noise(size, rng, octaves=5)
    # Concave remap pushes the distribution toward bright: most of the texture
    # leaves the coin nearly untouched, with only patches darkening it.
    shaped = 1.0 - (1.0 - noise) ** 2.2
    return _remap(shaped, low=150, high=250)


def generate_dust(size: int, rng: np.random.Generator) -> np.ndarray:
    """High-frequency grain plus sparse dark specks — grime under multiply."""
    grain = gaussian_filter(
        rng.standard_normal((size, size)).astype(np.float32), sigma=0.9
    )
    grain -= grain.min()
    grain_max = float(grain.max())
    if grain_max > 1e-6:
        grain /= grain_max

    canvas = np.ones((size, size), dtype=np.float32)
    n_dots = int(rng.integers(size // 3, size))
    for _ in range(n_dots):
        x = int(rng.integers(0, size))
        y = int(rng.integers(0, size))
        r = int(rng.integers(1, 4))
        intensity = float(rng.uniform(0.55, 0.9))
        cv2.circle(canvas, (x, y), r, intensity, -1)

    combined = 0.55 * grain + 0.45 * canvas
    return _remap(combined, low=165, high=250)


def generate_scratches(size: int, rng: np.random.Generator) -> np.ndarray:
    """Random bright lines on a black canvas — scratches under screen blend."""
    canvas = np.zeros((size, size), dtype=np.uint8)
    n_lines = int(rng.integers(18, 65))

    # 30% chance of a dominant direction — mimics directional wear (swipe wear).
    dominant_angle = (
        float(rng.uniform(0, 2 * np.pi)) if rng.random() < 0.3 else None
    )

    for _ in range(n_lines):
        if dominant_angle is not None and rng.random() < 0.75:
            angle = dominant_angle + float(rng.normal(0, 0.15))
        else:
            angle = float(rng.uniform(0, 2 * np.pi))
        x1 = int(rng.integers(0, size))
        y1 = int(rng.integers(0, size))
        length = int(rng.integers(size // 10, size // 2))
        x2 = int(np.clip(x1 + length * np.cos(angle), 0, size - 1))
        y2 = int(np.clip(y1 + length * np.sin(angle), 0, size - 1))
        brightness = int(rng.integers(150, 255))
        thickness = int(rng.integers(1, 3))
        cv2.line(canvas, (x1, y1), (x2, y2), brightness, thickness)

    return cv2.GaussianBlur(canvas, (3, 3), 0.6)


def generate_fingerprint(size: int, rng: np.random.Generator) -> np.ndarray:
    """Off-center anisotropic concentric ridges on mid-gray — overlay blend."""
    cx = int(rng.uniform(0.3, 0.7) * size)
    cy = int(rng.uniform(0.3, 0.7) * size)
    rx = float(rng.uniform(0.5, 1.0))
    ry = float(rng.uniform(0.5, 1.0))
    rotation = float(rng.uniform(0, 2 * np.pi))
    freq = float(rng.uniform(18.0, 32.0))

    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    dx = (xs - cx) / size
    dy = (ys - cy) / size
    cos_r = np.cos(rotation)
    sin_r = np.sin(rotation)
    u = (dx * cos_r + dy * sin_r) / rx
    v = (-dx * sin_r + dy * cos_r) / ry
    r = np.sqrt(u * u + v * v)

    ridges = np.sin(r * freq * np.pi)
    fade = np.clip(1.0 - (r - 0.4) * 2.5, 0.0, 1.0)

    low_freq_noise = _fractal_noise(size, rng, octaves=3)
    pattern = 0.5 + 0.22 * ridges * fade
    pattern = pattern * 0.8 + low_freq_noise * 0.2
    return _remap(pattern, low=0, high=255)


GENERATORS = {
    "patina": generate_patina,
    "dust": generate_dust,
    "scratches": generate_scratches,
    "fingerprints": generate_fingerprint,
}


def generate_all(
    size: int,
    counts: dict[str, int],
    seed: int,
    clean: bool,
) -> None:
    seed_sequence = np.random.SeedSequence(seed)
    # One independent child stream per category → regenerating only one
    # category keeps the others byte-identical.
    children = seed_sequence.spawn(len(counts))

    for (category, n), child in zip(counts.items(), children, strict=True):
        cat_dir = OVERLAYS_DIR / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        if clean:
            for existing in cat_dir.glob("*.png"):
                existing.unlink()

        rng = np.random.default_rng(child)
        for i in range(n):
            arr = GENERATORS[category](size, rng)
            out_path = cat_dir / f"{category}_{i:03d}.png"
            Image.fromarray(arr, mode="L").save(out_path, "PNG", optimize=True)
        logger.info("Generated %d %s textures in %s", n, category, cat_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Procedurally generate overlay textures for augmentation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing PNGs in each category before generating.",
    )
    for cat, default in DEFAULT_COUNTS.items():
        parser.add_argument(
            f"--{cat}",
            type=int,
            default=default,
            help=f"Number of {cat} textures to generate (default {default}).",
        )
    args = parser.parse_args()
    counts = {cat: getattr(args, cat) for cat in DEFAULT_COUNTS}

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    generate_all(size=args.size, counts=counts, seed=args.seed, clean=args.clean)


if __name__ == "__main__":
    main()
