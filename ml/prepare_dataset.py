"""Prepare the Eurio coin dataset: resize, class-aggregate, and split.

Source layout: ml/datasets/{numista_id}/{*.jpg, augmented/aug_*.jpg}
Output layout: ml/datasets/eurio-poc/{train,val,test}/{class_id}/*.jpg

class_id is COALESCE(design_group_id, eurio_id). Multiple source dirs whose
coins share a design_group_id merge into one output class dir — the model
then learns a single class per design.

The prepared directory also carries a class_manifest.json describing each
class (kind, member numista_ids, member eurio_ids) for downstream scripts.
"""

import argparse
import random
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image

from class_resolver import (
    ClassDescriptor,
    MANIFEST_FILENAME,
    Resolver,
    build_resolver,
    write_manifest,
)


def resize_and_save(src: Path, dst: Path, size: int = 256) -> None:
    with Image.open(src) as img:
        img = img.convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        img.save(dst, "JPEG", quality=95)


def _source_images(coin_dir: Path) -> list[Path]:
    return sorted(
        f for f in coin_dir.iterdir()
        if f.is_file()
        and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        and not f.stem.startswith("aug_")
    )


def _augmented_images(coin_dir: Path) -> list[Path]:
    aug_dir = coin_dir / "augmented"
    if not aug_dir.exists():
        return []
    return sorted(aug_dir.glob("aug_*.jpg"))


def _discover_classes(
    raw_dir: Path,
    resolver: Resolver,
) -> tuple[dict[str, list[Path]], dict[str, list[Path]], list[ClassDescriptor]]:
    """Group source + augmented images by class_id.

    Returns (sources_by_class, augmented_by_class, class_descriptors).
    Coins whose numista_id is unknown to Supabase are skipped (with warning).
    Coins without augmented images are skipped (training requires augmented set).
    """
    sources: dict[str, list[Path]] = defaultdict(list)
    augmented: dict[str, list[Path]] = defaultdict(list)
    active_class_ids: set[str] = set()

    for coin_dir in sorted(raw_dir.iterdir()):
        if not coin_dir.is_dir() or coin_dir.name == "eurio-poc":
            continue
        try:
            nid = int(coin_dir.name)
        except ValueError:
            # Non-numeric source dirs (e.g. legacy slug-named) are skipped; the
            # pipeline is numista_id-keyed on disk.
            continue

        descriptor = resolver.for_numista(nid)
        if descriptor is None:
            print(f"  {coin_dir.name}: no Supabase match for numista_id, skipping")
            continue

        aug = _augmented_images(coin_dir)
        if not aug:
            continue

        src = _source_images(coin_dir)
        sources[descriptor.class_id].extend(src)
        augmented[descriptor.class_id].extend(aug)
        active_class_ids.add(descriptor.class_id)

    descriptors = [
        resolver.for_class(cid) for cid in sorted(active_class_ids)
    ]
    return sources, augmented, [d for d in descriptors if d is not None]


def split_dataset(
    raw_dir: Path,
    output_dir: Path,
    resolver: Resolver,
    size: int = 256,
    train_ratio: float = 0.7,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> None:
    random.seed(seed)

    sources, augmented, descriptors = _discover_classes(raw_dir, resolver)
    if not descriptors:
        print(f"No classes with augmented images found in {raw_dir}")
        return

    for split in ("train", "val", "test"):
        (output_dir / split).mkdir(parents=True, exist_ok=True)

    header = f"{'Class':<55} {'Total':>5} {'Train':>5} {'Val':>5} {'Test':>5}"
    print(header)
    print("-" * 80)

    totals = {"train": 0, "val": 0, "test": 0}

    for descriptor in descriptors:
        class_id = descriptor.class_id
        images = list(sources.get(class_id, []))
        if not images:
            print(f"  {class_id}: no source images found, skipping")
            continue

        random.shuffle(images)

        n = len(images)
        n_train = max(1, round(n * train_ratio))
        n_val = max(1, round(n * val_ratio))
        n_test = max(1, n - n_train - n_val)
        if n_train + n_val + n_test > n:
            n_train = n - n_val - n_test

        assignments = (
            [("train", img) for img in images[:n_train]]
            + [("val", img) for img in images[n_train : n_train + n_val]]
            + [("test", img) for img in images[n_train + n_val :]]
        )

        for split, img_path in assignments:
            split_dir = output_dir / split / class_id
            split_dir.mkdir(parents=True, exist_ok=True)
            # Prefix with source numista dir to avoid collisions when multiple
            # numista members share a class.
            dst = split_dir / f"{img_path.parent.name}__{img_path.stem}.jpg"
            resize_and_save(img_path, dst, size)
            totals[split] += 1

        train_dir = output_dir / "train" / class_id
        train_dir.mkdir(parents=True, exist_ok=True)
        n_aug = 0
        for aug_img in augmented.get(class_id, []):
            dst = train_dir / f"{aug_img.parent.parent.name}__{aug_img.name}"
            resize_and_save(aug_img, dst, size)
            totals["train"] += 1
            n_aug += 1

        aug_suffix = f" +{n_aug} aug" if n_aug > 0 else ""
        print(
            f"  {class_id:<53} {n:>5} {n_train:>5} {n_val:>5} {n_test:>5}{aug_suffix}"
        )

    print("-" * 80)
    grand = sum(totals.values())
    print(
        f"  {'TOTAL':<53} {grand:>5} "
        f"{totals['train']:>5} {totals['val']:>5} {totals['test']:>5}"
    )
    print(f"\nOutput: {output_dir}")

    manifest_path = output_dir / MANIFEST_FILENAME
    write_manifest(manifest_path, descriptors)
    print(f"Manifest: {manifest_path} ({len(descriptors)} classes)")


def main():
    parser = argparse.ArgumentParser(description="Prepare Eurio coin dataset")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(__file__).parent / "datasets",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "datasets" / "eurio-poc",
    )
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.output_dir.exists():
        print(f"Output directory {args.output_dir} already exists. Removing...")
        shutil.rmtree(args.output_dir)

    resolver = build_resolver()
    print(f"Resolver: {len(resolver.classes)} known classes from Supabase")

    split_dataset(args.raw_dir, args.output_dir, resolver, size=args.size, seed=args.seed)


if __name__ == "__main__":
    main()
