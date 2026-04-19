"""Dirt / patina / scratches / fingerprints overlay augmentor.

Textures live under ``ml/data/overlays/<category>/*.png``. The user populates
these banks independently (scraping libre-de-droits, generating with Blender,
etc.). The augmentor must therefore tolerate an empty bank: when no textures
are available for any of the requested categories, ``apply`` returns the
input unchanged rather than raising, so geometry-only previews still work.

Blend modes per category:

- ``patina``       multiply — tarnishes the metal (copper/brass shades)
- ``dust``         multiply — subtle darkening from particles
- ``fingerprints`` overlay  — localized contrast shift from oily residue
- ``scratches``    screen   — bright micro-lines on metal
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from augmentations.base import Augmentor, circular_mask

logger = logging.getLogger(__name__)

OVERLAYS_DIR = Path(__file__).parent.parent / "data" / "overlays"
CATEGORIES = ("patina", "dust", "scratches", "fingerprints")
_BLEND_MODE = {
    "patina": "multiply",
    "dust": "multiply",
    # Real fingerprint textures are light ridges on a dark background (grease
    # catches ambient light on bright metal). Screen mode lifts only the ridge
    # pattern, leaving the background pixels near-untouched — so the effect
    # stays localized to the fingerprint lines instead of darkening the whole
    # coin with a "dreamy warp".
    "fingerprints": "screen",
    "scratches": "screen",
}

_TEXTURE_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg")


@lru_cache(maxsize=64)
def _load_texture(path: str) -> np.ndarray | None:
    """Load + cache a texture as RGB float array in [0, 255]."""
    try:
        with Image.open(path) as img:
            return np.asarray(img.convert("RGB"), dtype=np.float32)
    except (OSError, ValueError) as exc:
        logger.warning("Failed to load overlay %s: %s", path, exc)
        return None


class OverlayAugmentor(Augmentor):
    """Composite 1..max_layers random textures over the coin."""

    def __init__(
        self,
        categories: list[str],
        opacity_range: tuple[float, float] = (0.10, 0.30),
        max_layers: int = 2,
        probability: float = 0.5,
        **params: object,
    ) -> None:
        super().__init__(probability=probability, **params)
        self.categories = list(categories)
        self.opacity_range = opacity_range
        self.max_layers = max(1, int(max_layers))
        self._paths_by_category = self._scan()
        self._warned_empty = False

    def _scan(self) -> dict[str, list[Path]]:
        paths: dict[str, list[Path]] = {}
        for cat in self.categories:
            cat_dir = OVERLAYS_DIR / cat
            if not cat_dir.exists():
                paths[cat] = []
                continue
            found: list[Path] = []
            for pattern in _TEXTURE_EXTENSIONS:
                found.extend(cat_dir.glob(pattern))
            paths[cat] = sorted(found)
        return paths

    def _any_textures(self) -> bool:
        return any(len(v) > 0 for v in self._paths_by_category.values())

    def apply(
        self,
        img: Image.Image,
        rng: np.random.Generator,
    ) -> Image.Image:
        if not self._any_textures():
            if not self._warned_empty:
                logger.warning(
                    "No overlay textures found under %s for categories %s; "
                    "returning image unchanged",
                    OVERLAYS_DIR,
                    self.categories,
                )
                self._warned_empty = True
            return img

        img = img.convert("RGB")
        base = np.asarray(img, dtype=np.float32)
        h, w = base.shape[:2]
        mask = circular_mask(max(h, w))[:h, :w]

        n_layers = int(rng.integers(1, self.max_layers + 1))
        for _ in range(n_layers):
            # Pick a category that actually has textures available.
            available = [c for c in self.categories if self._paths_by_category[c]]
            if not available:
                break
            category = str(rng.choice(available))
            path = rng.choice(self._paths_by_category[category])
            texture = _load_texture(str(path))
            if texture is None:
                continue

            texture_img = Image.fromarray(texture.astype(np.uint8)).resize(
                (w, h), Image.LANCZOS
            )
            texture = np.asarray(texture_img, dtype=np.float32)

            opacity = float(rng.uniform(*self.opacity_range))
            base = _blend(base, texture, _BLEND_MODE[category], opacity, mask)

        return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


def _blend(
    base: np.ndarray,
    overlay: np.ndarray,
    mode: str,
    opacity: float,
    mask: np.ndarray,
) -> np.ndarray:
    """Apply a named blend mode, weighted by opacity and circular mask."""
    if mode == "multiply":
        blended = base * overlay / 255.0
    elif mode == "screen":
        blended = 255.0 - (255.0 - base) * (255.0 - overlay) / 255.0
    elif mode == "overlay":
        # Standard Photoshop overlay: multiply for dark bases, screen for light.
        low = 2.0 * base * overlay / 255.0
        high = 255.0 - 2.0 * (255.0 - base) * (255.0 - overlay) / 255.0
        blended = np.where(base < 128.0, low, high)
    else:
        return base

    weight = (opacity * mask)[..., None]
    return base * (1.0 - weight) + blended * weight


def sanity_check_textures() -> int:
    """Scan overlay directories and print a Markdown-like status table.

    Returns a shell-style exit code: 0 if at least one texture exists anywhere,
    1 if all banks are empty (the pipeline would still run, but this is the
    signal to the user that they haven't populated the banks yet).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    rows: list[tuple[str, int, str]] = []
    total_count = 0
    for cat in CATEGORIES:
        cat_dir = OVERLAYS_DIR / cat
        if not cat_dir.exists():
            rows.append((cat, 0, "missing-dir"))
            continue
        found: list[Path] = []
        for pattern in _TEXTURE_EXTENSIONS:
            found.extend(cat_dir.glob(pattern))
        paths = sorted(found)
        if not paths:
            rows.append((cat, 0, "empty"))
            continue

        broken = 0
        for path in paths:
            try:
                with Image.open(path) as img:
                    img.verify()
            except (OSError, ValueError):
                broken += 1
        count = len(paths)
        total_count += count
        status = "ok" if broken == 0 else f"warning ({broken} broken)"
        rows.append((cat, count, status))

    print()
    print("| category     | count | status                |")
    print("|--------------|-------|-----------------------|")
    for cat, count, status in rows:
        print(f"| {cat:<12} | {count:>5} | {status:<21} |")
    print()
    print(f"Total textures: {total_count}")
    print(f"Overlays dir:   {OVERLAYS_DIR}")

    if total_count == 0:
        print()
        print(
            "No textures found. Populate at least one category under "
            f"{OVERLAYS_DIR} before running training augmentation."
        )
        return 1
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(sanity_check_textures())
