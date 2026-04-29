"""Prepare the Eurio coin dataset: resize, class-aggregate, and split.

Source layout: ml/datasets/{numista_id}/{*.jpg,*.png,*.webp}
Output layout: ml/datasets/eurio-poc/{train,val,test}/{class_id}/*.jpg

class_id is COALESCE(design_group_id, eurio_id). Multiple source dirs whose
coins share a design_group_id merge into one output class dir — the model
then learns a single class per design.

Augmented images are NOT pre-generated to disk anymore. Augmentation runs
on-the-fly during training (see training/coin_dataset.py +
augmentations/recipes.py). This script only splits the source images into
train/val/test folders so torchvision's ImageFolder can pick them up.

The prepared directory also carries a class_manifest.json describing each
class (kind, member numista_ids, member eurio_ids) for downstream scripts.
"""

import argparse
import random
import shutil
from collections import defaultdict
from pathlib import Path

import cv2
from PIL import Image

from eval.class_resolver import (
    ClassDescriptor,
    MANIFEST_FILENAME,
    Resolver,
    build_resolver,
    write_manifest,
)
from scan.normalize_snap import OUTPUT_SIZE, normalize_studio_path


def normalize_and_save(src: Path, dst: Path) -> bool:
    """Run `normalize_studio` on src and write the 224×224 tight crop to dst.

    Studio pipeline (Otsu + minEnclosingCircle at WR=1024) — sub-pixel rim
    capture and bimétal-aware. The 224×224 contract is identical to the
    device pipeline (`normalize_device`) so train and inference distributions
    align. Returns True on success; False if both contour and Hough fallback
    failed — caller then falls back to a plain LANCZOS resize so the source
    isn't dropped.
    """
    result = normalize_studio_path(src)
    if result.image is None:
        print(f"  ! normalize_studio failed on {src} ({result.debug}), falling back to resize")
        with Image.open(src) as img:
            img.convert("RGB").resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS).save(
                dst, "JPEG", quality=95,
            )
        return False
    cv2.imwrite(str(dst), result.image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return True


_SOURCE_NAME_RE = __import__("re").compile(r"^(obverse|real_)")


def _source_images(coin_dir: Path) -> list[Path]:
    """Strict filter: only obverse/real_ photos count as training sources.

    The reverse face of a 2 EUR coin is shared across every commemorative —
    feeding it to ArcFace as class-specific data poisons the training signal.
    Numbered files (001.jpg, 002.jpg, ...) historically held mixed-content
    real photos; until they are renamed with a known prefix
    (e.g. real_001.jpg) they are filtered out so all classes start from
    equal-quality Numista studio data.

    To extend the source pool for a class, drop a file named
    real_<anything>.{jpg,png} into datasets/<numista_id>/.
    """
    return sorted(
        f for f in coin_dir.iterdir()
        if f.is_file()
        and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        and _SOURCE_NAME_RE.match(f.stem)
    )


def _discover_classes(
    raw_dir: Path,
    resolver: Resolver,
    only_classes: set[str] | None = None,
) -> tuple[dict[str, list[Path]], list[ClassDescriptor]]:
    """Group source images by class_id.

    Returns (sources_by_class, class_descriptors). Coins whose numista_id is
    unknown to Supabase are skipped (with warning). When ``only_classes`` is
    provided, source dirs whose resolved class_id is not in the set are also
    skipped — used by the orchestrator to limit prep to the run's
    ``classes_after`` (so we don't drag the entire datasets/ tree into a
    targeted run).
    """
    sources: dict[str, list[Path]] = defaultdict(list)
    active_class_ids: set[str] = set()

    # When the runner restricts to a specific set of classes, pre-compute
    # the numista_ids that would resolve to those classes so we never even
    # touch the unrelated directories under raw_dir/. Avoids ~1500 lines of
    # "no Supabase match" log noise on a 1-class run.
    candidate_nids: set[int] | None = None
    if only_classes is not None:
        candidate_nids = set()
        for cid in only_classes:
            d = resolver.for_class(cid)
            if d is not None:
                candidate_nids.update(d.numista_ids)

    skipped_no_match = 0
    for coin_dir in sorted(raw_dir.iterdir()):
        if not coin_dir.is_dir() or coin_dir.name == "eurio-poc":
            continue
        try:
            nid = int(coin_dir.name)
        except ValueError:
            # Non-numeric source dirs (e.g. legacy slug-named) are skipped; the
            # pipeline is numista_id-keyed on disk.
            continue

        if candidate_nids is not None and nid not in candidate_nids:
            continue

        descriptor = resolver.for_numista(nid)
        if descriptor is None:
            skipped_no_match += 1
            continue

        if only_classes is not None and descriptor.class_id not in only_classes:
            continue

        src = _source_images(coin_dir)
        if not src:
            continue
        sources[descriptor.class_id].extend(src)
        active_class_ids.add(descriptor.class_id)

    if skipped_no_match:
        print(f"  {skipped_no_match} dir(s) skipped (numista_id absent from Supabase)")

    descriptors = [
        resolver.for_class(cid) for cid in sorted(active_class_ids)
    ]
    return sources, [d for d in descriptors if d is not None]


def split_dataset(
    raw_dir: Path,
    output_dir: Path,
    resolver: Resolver,
    train_ratio: float = 0.7,
    val_ratio: float = 0.2,
    seed: int = 42,
    only_classes: set[str] | None = None,
) -> None:
    random.seed(seed)

    sources, descriptors = _discover_classes(raw_dir, resolver, only_classes)
    if not descriptors:
        raise SystemExit(
            f"No source images found in {raw_dir} — every staged class must have "
            "at least one image in datasets/<numista_id>/. Check that the augment "
            "(now removed) and seed steps succeeded for the staged classes."
        )

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
        # Small-n policy: classes with very few source images cannot afford to
        # reserve validation/test holdouts. Augmentation is on-the-fly so the
        # train pool's effective diversity grows per epoch — feeding all
        # available images into train is always preferable to a 0-train split.
        if n <= 2:
            n_train, n_val, n_test = n, 0, 0
        elif n == 3:
            n_train, n_val, n_test = 2, 1, 0
        else:
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
            normalize_and_save(img_path, dst)
            totals[split] += 1

        print(
            f"  {class_id:<53} {n:>5} {n_train:>5} {n_val:>5} {n_test:>5}"
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

    # Override val/ with the device golden set when available. The device
    # snaps (eval_real_norm/<class>/<step>.jpg) are real photos taken on the
    # phone and pushed through `normalize_device` — they are the only val
    # set whose metric correlates with on-device behavior. With n_sources=1
    # the studio-derived val/ is empty anyway (everything fell into train),
    # so overriding it is lossless.
    eval_real_dir = raw_dir.parent / "datasets" / "eval_real_norm"
    if not eval_real_dir.exists():
        eval_real_dir = Path(__file__).parent.parent / "datasets" / "eval_real_norm"
    if eval_real_dir.exists():
        print(f"\nDevice val set: {eval_real_dir}")
        device_val_total = 0
        for descriptor in descriptors:
            cls_src = eval_real_dir / descriptor.class_id
            if not cls_src.is_dir():
                continue
            cls_dst = output_dir / "val" / descriptor.class_id
            if cls_dst.exists():
                shutil.rmtree(cls_dst)
            cls_dst.mkdir(parents=True, exist_ok=True)
            n = 0
            for f in sorted(cls_src.iterdir()):
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    shutil.copy2(f, cls_dst / f.name)
                    n += 1
            print(f"  {descriptor.class_id:<55} {n:>3} device snaps → val/")
            device_val_total += n
        print(f"Device val total: {device_val_total} images")
    else:
        print(f"\n(no eval_real_norm/ found — val stays studio-derived; "
              f"run `python -m scan.sync_eval_real <debug_pull>` to populate)")


def main():
    parser = argparse.ArgumentParser(description="Prepare Eurio coin dataset")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(__file__).parent.parent / "datasets",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "datasets" / "eurio-poc",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--only-classes",
        type=str,
        default=None,
        help="Comma-separated class_ids to keep. Source dirs resolving to "
             "any other class are skipped. Used by the runner to scope a "
             "training run to its classes_after.",
    )
    args = parser.parse_args()

    from train_embedder import _assert_no_real_photos

    _assert_no_real_photos(str(args.raw_dir), role="raw")
    _assert_no_real_photos(str(args.output_dir), role="prepared-output")

    if args.output_dir.exists():
        print(f"Output directory {args.output_dir} already exists. Removing...")
        shutil.rmtree(args.output_dir)

    resolver = build_resolver()
    print(f"Resolver: {len(resolver.classes)} known classes from Supabase")

    only_classes: set[str] | None = None
    if args.only_classes:
        only_classes = {c.strip() for c in args.only_classes.split(",") if c.strip()}
        print(f"Restricting to {len(only_classes)} class(es) from --only-classes")

    split_dataset(
        args.raw_dir,
        args.output_dir,
        resolver,
        seed=args.seed,
        only_classes=only_classes,
    )


if __name__ == "__main__":
    main()
