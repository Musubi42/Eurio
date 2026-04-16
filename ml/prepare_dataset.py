"""Prepare the Eurio coin dataset: resize and split into train/val/test."""

import argparse
import random
import shutil
from pathlib import Path

from PIL import Image


def resize_and_save(src: Path, dst: Path, size: int = 256) -> None:
    """Resize image to size×size and save as JPEG."""
    with Image.open(src) as img:
        img = img.convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        img.save(dst, "JPEG", quality=95)


def split_dataset(
    raw_dir: Path,
    output_dir: Path,
    size: int = 256,
    train_ratio: float = 0.7,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> None:
    """Read raw images, resize, and split into train/val/test."""
    random.seed(seed)

    classes = sorted([d for d in raw_dir.iterdir() if d.is_dir()])
    if not classes:
        print(f"No class directories found in {raw_dir}")
        return

    splits = ["train", "val", "test"]
    for split in splits:
        (output_dir / split).mkdir(parents=True, exist_ok=True)

    print(f"{'Class':<55} {'Total':>5} {'Train':>5} {'Val':>5} {'Test':>5}")
    print("-" * 80)

    total_counts = {"train": 0, "val": 0, "test": 0}

    for cls_dir in classes:
        cls_name = cls_dir.name
        # Source images (not augmented, not in augmented/ subdir)
        images = sorted([
            f for f in cls_dir.iterdir()
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            and not f.stem.startswith("aug_")
            and f.is_file()
        ])

        if not images:
            print(f"  {cls_name}: no images found, skipping")
            continue

        random.shuffle(images)

        n = len(images)
        n_train = max(1, round(n * train_ratio))
        n_val = max(1, round(n * val_ratio))
        n_test = max(1, n - n_train - n_val)

        # Adjust if rounding caused overflow
        if n_train + n_val + n_test > n:
            n_train = n - n_val - n_test

        assignments = (
            [("train", img) for img in images[:n_train]]
            + [("val", img) for img in images[n_train : n_train + n_val]]
            + [("test", img) for img in images[n_train + n_val :]]
        )

        for split, img_path in assignments:
            split_cls_dir = output_dir / split / cls_name
            split_cls_dir.mkdir(parents=True, exist_ok=True)
            dst = split_cls_dir / f"{img_path.stem}.jpg"
            resize_and_save(img_path, dst, size)
            total_counts[split] += 1

        # Add augmented images to train set only
        aug_dir = cls_dir / "augmented"
        n_aug = 0
        if aug_dir.exists():
            train_cls_dir = output_dir / "train" / cls_name
            train_cls_dir.mkdir(parents=True, exist_ok=True)
            for aug_img in sorted(aug_dir.glob("aug_*.jpg")):
                dst = train_cls_dir / aug_img.name
                resize_and_save(aug_img, dst, size)
                total_counts["train"] += 1
                n_aug += 1

        aug_str = f" +{n_aug} aug" if n_aug > 0 else ""
        print(
            f"  {cls_name:<53} {n:>5} {n_train:>5} {n_val:>5} {n_test:>5}{aug_str}"
        )

    print("-" * 80)
    total = sum(total_counts.values())
    print(
        f"  {'TOTAL':<53} {total:>5} "
        f"{total_counts['train']:>5} {total_counts['val']:>5} {total_counts['test']:>5}"
    )
    print(f"\nOutput: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Prepare Eurio coin dataset")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(__file__).parent / "datasets",
        help="Directory with raw class subdirectories (default: ml/datasets/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "datasets" / "eurio-poc",
        help="Output directory for train/val/test split",
    )
    parser.add_argument("--size", type=int, default=256, help="Resize dimension")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    if args.output_dir.exists():
        print(f"Output directory {args.output_dir} already exists. Removing...")
        shutil.rmtree(args.output_dir)

    split_dataset(args.raw_dir, args.output_dir, size=args.size, seed=args.seed)


if __name__ == "__main__":
    main()
