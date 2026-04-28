"""On-the-fly augmented dataset for coin embedding training.

Replaces the static ``ml/datasets/<nid>/augmented/*.jpg`` workflow. Each
``__getitem__`` call:

1. Loads the source PIL image from disk.
2. Applies the recipe pipeline (perspective + relighting + overlays) chosen
   for this class's confusion zone — green / orange / red.
3. Applies the legacy torchvision transforms (rotation, color jitter,
   random crop, normalization) on top.

Pipelines are cached per zone (one ``AugmentationPipeline`` per zone, shared
across classes) so we don't re-instantiate per ``__getitem__``. Overlay
texture banks load once at first use.

The legacy transforms (rotation 0–360°, color/brightness jitter, random
crop+resize, gaussian blur) stay applied to every sample regardless of
zone — they cover invariances that the recipe layers don't (camera tilt
is in the recipe, but rotation 0–360° / lighting is not). This is the
"two-layer stack" called out in ``augmentations/recipes.py``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from torch.utils.data import Dataset
from torchvision.datasets.folder import default_loader, IMG_EXTENSIONS

from augmentations import AugmentationPipeline
from augmentations.recipes import ZONE_RECIPES


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMG_EXTENSIONS


def _scan_class_folder(
    root: Path,
    *,
    allow_empty: bool = False,
) -> tuple[list[str], dict[str, int], list[tuple[Path, int]]]:
    """Mimic ImageFolder discovery: alphabetical class order, (path, idx) list.

    With ``allow_empty=True`` an empty / missing folder yields empty lists
    instead of raising — used for val/test splits which can legitimately be
    empty when classes have very few source photos (the small-n policy in
    prepare_dataset.py keeps everything in train).
    """
    if not root.exists() or not root.is_dir():
        if allow_empty:
            return [], {}, []
        raise RuntimeError(f"No directory at {root}")

    classes = sorted(
        d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")
    )
    class_to_idx = {name: i for i, name in enumerate(classes)}
    samples: list[tuple[Path, int]] = []
    for cls_name in classes:
        cls_dir = root / cls_name
        for f in sorted(cls_dir.iterdir()):
            if f.is_file() and _is_image(f):
                samples.append((f, class_to_idx[cls_name]))
    if not samples and not allow_empty:
        raise RuntimeError(f"No images found under {root}")
    return classes, class_to_idx, samples


class EurioCoinDataset(Dataset):
    """Per-class zone-aware augmentation Dataset.

    Args:
        root: directory with one subfolder per class (ImageFolder layout).
        class_zones: mapping ``{class_name: zone}``. Missing entries fall
            back to the default zone (orange).
        legacy_transform: torchvision Compose applied AFTER the recipe.
        recipe_override: if set, this recipe is used for ALL classes,
            ignoring zone resolution. Used when the user explicitly passes
            ``--aug-recipe`` for a custom training experiment.
        samples_per_class: virtual epoch size — every class is repeated to
            this length per epoch (with replacement when source pool is
            smaller). On-the-fly augmentation makes each repeated access
            produce a different variation. Equalizes the contribution of
            classes with few source photos vs. many.
        seed: optional seed for reproducible recipe outputs (None = random).
    """

    def __init__(
        self,
        root: str | Path,
        class_zones: dict[str, str],
        legacy_transform,
        *,
        recipe_override: dict | None = None,
        samples_per_class: int = 50,
        seed: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.legacy_transform = legacy_transform
        self.classes, self.class_to_idx, raw_samples = _scan_class_folder(self.root)

        # Virtually expand to ``samples_per_class`` entries per class. The
        # underlying source images get reused (cycled) — augmentation runs
        # on every __getitem__ so repeated indices yield distinct variations.
        by_class: dict[int, list[tuple[Path, int]]] = {}
        for path, target in raw_samples:
            by_class.setdefault(target, []).append((path, target))

        self.samples: list[tuple[Path, int]] = []
        for target, items in by_class.items():
            if not items:
                continue
            n = max(samples_per_class, len(items))
            for i in range(n):
                self.samples.append(items[i % len(items)])
        self.samples_per_class = samples_per_class

        # One pipeline per distinct zone — shared across classes of that zone.
        self._pipelines: dict[str, AugmentationPipeline] = {}
        if recipe_override is not None:
            self._pipelines["__override__"] = AugmentationPipeline(
                recipe_override, seed=seed
            )
            self._class_zone: dict[str, str] = {c: "__override__" for c in self.classes}
        else:
            self._class_zone = {
                c: class_zones.get(c, "orange") for c in self.classes
            }
            for zone in set(self._class_zone.values()):
                if zone not in ZONE_RECIPES:
                    zone = "orange"
                self._pipelines[zone] = AugmentationPipeline(
                    ZONE_RECIPES[zone], seed=seed
                )

    @property
    def targets(self) -> list[int]:
        """Used by samplers (e.g. MPerClassSampler)."""
        return [t for _, t in self.samples]

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        path, target = self.samples[index]
        img = default_loader(str(path))  # PIL Image, RGB
        zone = self._class_zone[self.classes[target]]
        pipeline = self._pipelines.get(zone) or self._pipelines["orange"]
        img = pipeline.generate(img, count=1)[0]
        img = self.legacy_transform(img)
        return img, target


class EurioValDataset(Dataset):
    """Validation/test variant — no recipe augmentation, only val transform.

    Mirrors ImageFolder for val/test paths so that metrics are computed on
    raw source images (no on-the-fly variations).
    """

    def __init__(self, root: str | Path, transform) -> None:
        self.root = Path(root)
        self.transform = transform
        self.classes, self.class_to_idx, self.samples = _scan_class_folder(
            self.root, allow_empty=True
        )

    @property
    def targets(self) -> list[int]:
        return [t for _, t in self.samples]

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        path, target = self.samples[index]
        img = default_loader(str(path))
        return self.transform(img), target
