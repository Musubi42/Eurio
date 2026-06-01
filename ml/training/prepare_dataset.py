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
    build_resolver_from_cohort_csv,
    write_manifest,
)
from scan.normalize_snap import CropConfig, OUTPUT_SIZE, normalize_studio_path


def normalize_and_save(src: Path, dst: Path,
                       config: CropConfig | None = None) -> bool:
    """Run `normalize_studio` on src and write the tight crop to dst.

    Studio pipeline (Otsu + minEnclosingCircle at WR=1024) — sub-pixel rim
    capture and bimétal-aware. The output size + crop format are governed by
    `config` ; when None (default), behavior is legacy (224 × hard mask × 2%
    margin) — bit-identique au comportement avant introduction de CropConfig.

    Returns True on success; False if both contour and Hough fallback failed —
    caller then falls back to a plain LANCZOS resize so the source isn't dropped.
    """
    result = normalize_studio_path(src, config=config)
    if result.image is None:
        size = config.output_size if config is not None else OUTPUT_SIZE
        print(f"  ! normalize_studio failed on {src} ({result.debug}), falling back to resize")
        with Image.open(src) as img:
            img.convert("RGB").resize((size, size), Image.LANCZOS).save(
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
    class_kind: str,
    train_ratio: float = 0.7,
    val_ratio: float = 0.2,
    seed: int = 42,
    only_classes: set[str] | None = None,
    skip_train_split: bool = False,
    crop_config: CropConfig | None = None,
) -> None:
    random.seed(seed)

    sources, descriptors = _discover_classes(raw_dir, resolver, only_classes)
    if not descriptors:
        raise SystemExit(
            f"No source images found in {raw_dir} — every staged class must have "
            "at least one image in datasets/<numista_id>/. Check that the augment "
            "(now removed) and seed steps succeeded for the staged classes."
        )

    splits = ("val",) if skip_train_split else ("train", "val", "test")
    for split in splits:
        (output_dir / split).mkdir(parents=True, exist_ok=True)

    if skip_train_split:
        # Lab iteration mode : train/ vient des bakes symlinkés (cf.
        # iteration_runner). On n'écrit que val/ (eval_real_norm override
        # ci-dessous) + manifest. Pas de scan studio train/test.
        manifest_path = output_dir / MANIFEST_FILENAME
        write_manifest(manifest_path, descriptors)
        print(f"Manifest: {manifest_path} ({len(descriptors)} classes)")
        _override_val_with_eval_real(
            raw_dir, output_dir, descriptors, class_kind,
        )
        return

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
            normalize_and_save(img_path, dst, config=crop_config)
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

    _override_val_with_eval_real(raw_dir, output_dir, descriptors, class_kind)


def _override_val_with_eval_real(
    raw_dir: Path,
    output_dir: Path,
    descriptors: list[ClassDescriptor],
    class_kind: str,
) -> None:
    """Replace val/ with device snaps (eval_real_norm/<class>/*).

    Device snaps run through ``normalize_device`` so their distribution
    aligns with on-device inference — the only val set whose metric
    correlates with deployed behavior. In ``eurio_id`` lab mode, a class
    without device snaps is a fail-explicit (silent skip used to mask
    the test-2/test-3 collapse).
    """
    eval_real_dir = raw_dir.parent / "datasets" / "eval_real_norm"
    if not eval_real_dir.exists():
        eval_real_dir = Path(__file__).parent.parent / "datasets" / "eval_real_norm"
    if not eval_real_dir.exists():
        print(f"\n(no eval_real_norm/ found — val stays studio-derived; "
              f"run `python -m scan.sync_eval_real <debug_pull>` to populate)")
        return

    (output_dir / "val").mkdir(parents=True, exist_ok=True)
    print(f"\nDevice val set: {eval_real_dir}")
    device_val_total = 0
    missing: list[str] = []
    for descriptor in descriptors:
        cls_src = eval_real_dir / descriptor.class_id
        if not cls_src.is_dir():
            if class_kind == "eurio_id":
                missing.append(descriptor.class_id)
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
    if missing:
        raise SystemExit(
            "Missing eval_real_norm/<eurio_id>/ for "
            f"{len(missing)} class(es): {', '.join(missing)}. "
            f"Expected under {eval_real_dir}/. Capture device snaps for "
            "these eurio_ids before relaunching, or remove them from the "
            "iteration cohort."
        )
    print(f"Device val total: {device_val_total} images")


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
    parser.add_argument(
        "--class-kind",
        choices=["eurio_id", "design_group"],
        required=True,
        help="Label space pour cette préparation. 'eurio_id' (mode lab "
             "iteration) force chaque coin à être sa propre classe, ignore "
             "design_group_id. 'design_group' (mode legacy) coalesce sur "
             "design_group_id quand présent. Cf. "
             "docs/lab-prod-refacto/phase-1-label-space.md.",
    )
    parser.add_argument(
        "--cohort-csv",
        type=Path,
        default=None,
        help="Build the class resolver from this cohort CSV "
             "(eurio_id;numista_id;display_name) instead of Supabase — offline "
             "source of truth for a capture cohort. The run then trains exactly "
             "the CSV's coins (every other datasets/<nid> dir is skipped). Cf. "
             "docs/operations/crop-ablation-pc-runbook.md.",
    )
    parser.add_argument(
        "--skip-train-split",
        action="store_true",
        help="Mode lab iteration : ne génère que val/ + manifest. train/ "
             "vient des symlinks bakés (cf. iteration_runner). N'efface pas "
             "output_dir préexistant pour préserver le symlink train/.",
    )
    # CropConfig ablation : laisser None pour comportement legacy (2% / hard / 224)
    parser.add_argument(
        "--crop-margin-frac", type=float, default=None,
        help="CropConfig margin_frac (fraction du rayon détecté). Défaut "
             "legacy 0.02. Utiliser ≥0.05 pour préserver le rim/chanfrein.",
    )
    parser.add_argument(
        "--crop-edge-mode", choices=["hard", "feathered", "none"], default=None,
        help="CropConfig edge_mode. Défaut legacy 'hard' (masque circulaire "
             "noir net). 'feathered' = transition douce, 'none' = pas de masque.",
    )
    parser.add_argument(
        "--crop-feather-width-frac", type=float, default=None,
        help="CropConfig feather_width_frac. Largeur du blur du masque "
             "feathered, fraction du rayon. Ignoré si edge_mode != 'feathered'.",
    )
    parser.add_argument(
        "--crop-output-size", type=int, default=None,
        help="CropConfig output_size. Défaut legacy 224. Utiliser 160 ou 128 "
             "pour benchmark résolution mobile (style ArcFace face 112).",
    )
    args = parser.parse_args()

    # Construire CropConfig seulement si AU MOINS un override CLI a été fourni.
    # Sinon None → comportement legacy bit-identique (zero régression).
    crop_config: CropConfig | None = None
    if any(v is not None for v in (
        args.crop_margin_frac, args.crop_edge_mode,
        args.crop_feather_width_frac, args.crop_output_size,
    )):
        defaults = CropConfig()
        crop_config = CropConfig(
            margin_frac=args.crop_margin_frac if args.crop_margin_frac is not None else defaults.margin_frac,
            edge_mode=args.crop_edge_mode if args.crop_edge_mode is not None else defaults.edge_mode,
            feather_width_frac=(args.crop_feather_width_frac
                                if args.crop_feather_width_frac is not None
                                else defaults.feather_width_frac),
            output_size=args.crop_output_size if args.crop_output_size is not None else defaults.output_size,
        )
        print(f"\n[ablation] Using non-default CropConfig: {crop_config}\n")

    from training.train_embedder import _assert_no_real_photos

    _assert_no_real_photos(str(args.raw_dir), role="raw")
    _assert_no_real_photos(str(args.output_dir), role="prepared-output")

    if args.output_dir.exists() and not args.skip_train_split:
        print(f"Output directory {args.output_dir} already exists. Removing...")
        shutil.rmtree(args.output_dir)
    elif args.skip_train_split:
        # Only refresh val/ + manifest ; preserve the train/ symlink set up
        # by iteration_runner.
        val_dir = args.output_dir / "val"
        if val_dir.exists():
            shutil.rmtree(val_dir)
        manifest = args.output_dir / "class_manifest.json"
        if manifest.exists():
            manifest.unlink()
        args.output_dir.mkdir(parents=True, exist_ok=True)

    force_eurio_id = args.class_kind == "eurio_id"
    if args.cohort_csv is not None:
        resolver = build_resolver_from_cohort_csv(
            args.cohort_csv, force_eurio_id=force_eurio_id)
        source = f"cohort CSV {args.cohort_csv.name}"
    else:
        resolver = build_resolver(force_eurio_id=force_eurio_id)
        source = "Supabase"
    print(
        f"Resolver: {len(resolver.classes)} known classes from {source} "
        f"(class_kind={args.class_kind})"
    )

    only_classes: set[str] | None = None
    if args.only_classes:
        only_classes = {c.strip() for c in args.only_classes.split(",") if c.strip()}
        print(f"Restricting to {len(only_classes)} class(es) from --only-classes")

    split_dataset(
        args.raw_dir,
        args.output_dir,
        resolver,
        class_kind=args.class_kind,
        seed=args.seed,
        only_classes=only_classes,
        skip_train_split=args.skip_train_split,
        crop_config=crop_config,
    )


if __name__ == "__main__":
    main()
