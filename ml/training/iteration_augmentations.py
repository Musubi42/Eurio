"""Generate persistent augmentations for a Lab iteration.

Sprint 1 / D-004 — augmentations are baked once on disk under
``ml/datasets/<numista_id>/augmentations/<iteration_id>/sample_NNN.jpg``.
The training pipeline then reads that snapshot directly (no on-the-fly
recipe), so re-running the same iteration_id yields identical inputs.

Design notes:

- One ``AugmentationPipeline`` per coin, seeded deterministically from
  ``(iteration_seed, numista_id)``. The per-coin seed lets us regenerate
  one coin's snapshot without touching the others (useful when a single
  coin's source images change).
- Source images are pulled exclusively from ``<nid>/obverse.{jpg,png}``.
  Captures are NEVER used as a training source — they are the bench's
  ground truth (`evaluate_real_photos.py` reads them) and using them
  here would (a) leak the eval set into training, gonflant le R@1
  studio, and (b) diverger du baseline historique qui s'est toujours
  entraîné sur obverse uniquement. Reverse n'est pas non plus utilisé
  — décision produit, le modèle ArcFace ne voit que l'avers.
- Output filenames are ``sample_<NNN>.jpg`` zero-padded to 3 digits, as
  documented in ``docs/training-pipeline/filesystem.md``.
- For each iteration we also build a unified training root at
  ``ml/datasets/iterations/<iteration_id>/<eurio_id>/`` whose entries are
  relative symlinks back to the per-coin snapshots. This preserves the
  canonical path while letting torchvision's ImageFolder layout work
  unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from PIL import Image

from api import coin_lookup
from augmentations import AugmentationPipeline
from augmentations.recipes import DEFAULT_RECIPE
from state import Store

DATASETS_DIR = ML_DIR / "datasets"
ITERATION_TRAIN_ROOTS = DATASETS_DIR / "iterations"

OBVERSE_NAMES = ("obverse.jpg", "obverse.png")


@dataclass
class CoinAugReport:
    eurio_id: str
    numista_id: int | None
    written: int
    sources_used: int
    skipped_reason: str | None = None


def _per_coin_seed(iteration_seed: int, numista_id: int) -> int:
    """Stable per-coin seed derived from the iteration seed + numista_id.

    Hashing keeps the coin-level RNG independent of the iteration RNG so
    regenerating one coin's snapshot doesn't shift the others.
    """
    h = hashlib.sha256(f"{iteration_seed}:{numista_id}".encode("utf-8"))
    return int.from_bytes(h.digest()[:4], "big") & 0x7FFFFFFF


def _source_images(numista_id: int) -> list[Path]:
    """Return the canonical obverse source for this coin, if present.

    Strict obverse-only — see module docstring. Captures are off-limits
    here; they belong to the bench.
    """
    coin_dir = DATASETS_DIR / str(numista_id)
    return [
        coin_dir / name
        for name in OBVERSE_NAMES
        if (coin_dir / name).exists()
    ]


def generate_for_iteration(
    *,
    iteration_id: str,
    store: Store | None = None,
) -> list[CoinAugReport]:
    """(Re)generate augmentations for every coin in the iteration's cohort.

    Existing snapshots are reused: if ``<nid>/augmentations/<iid>/`` already
    contains the expected number of files, the coin is left untouched.
    Callers that want a forced rebuild should clear the directory first
    (the regenerate endpoint does that).
    """
    store = store or Store(ML_DIR / "state" / "training.db")
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")

    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")

    if it.augmentations_seed is None:
        raise ValueError(
            f"Iteration {iteration_id!r} has no augmentations_seed — was it created "
            "before the sprint-1 migration?"
        )

    recipe_cfg: dict
    if it.recipe_id:
        recipe = store.get_recipe(it.recipe_id)
        if recipe is None:
            raise ValueError(f"Recipe {it.recipe_id!r} not found")
        recipe_cfg = recipe.config
    else:
        recipe_cfg = DEFAULT_RECIPE

    target = max(int(it.variant_count), 1)
    train_root = ITERATION_TRAIN_ROOTS / iteration_id
    train_root.mkdir(parents=True, exist_ok=True)

    reports: list[CoinAugReport] = []
    for eurio_id in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eurio_id)
        if nid is None:
            reports.append(
                CoinAugReport(
                    eurio_id=eurio_id,
                    numista_id=None,
                    written=0,
                    sources_used=0,
                    skipped_reason="no numista_id mapping",
                )
            )
            continue

        sources = _source_images(nid)
        if not sources:
            reports.append(
                CoinAugReport(
                    eurio_id=eurio_id,
                    numista_id=nid,
                    written=0,
                    sources_used=0,
                    skipped_reason="no obverse image (obverse.jpg or obverse.png)",
                )
            )
            continue

        out_dir = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(out_dir.glob("sample_*.jpg"))
        if len(existing) >= target:
            written = len(existing)
        else:
            # Always start clean when we need to (re)generate so we don't end
            # up with a mix of partial old + new samples.
            for f in existing:
                f.unlink()
            seed = _per_coin_seed(it.augmentations_seed, nid)
            pipeline = AugmentationPipeline(recipe_cfg, seed=seed)
            written = 0
            for i in range(target):
                src_path = sources[i % len(sources)]
                with Image.open(src_path) as raw:
                    base = raw.convert("RGB")
                    img = pipeline.generate(base, count=1)[0]
                out_path = out_dir / f"sample_{i + 1:03d}.jpg"
                img.save(out_path, "JPEG", quality=92)
                written += 1

        # Stage symlinks under the iteration training root so that the
        # standard ImageFolder layout works — one subdir per class.
        class_dir = train_root / eurio_id
        if class_dir.is_symlink() or class_dir.is_file():
            class_dir.unlink()
        elif class_dir.is_dir():
            shutil.rmtree(class_dir)
        class_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(out_dir.glob("sample_*.jpg")):
            link = class_dir / f.name
            os.symlink(os.path.relpath(f, class_dir), link)

        reports.append(
            CoinAugReport(
                eurio_id=eurio_id,
                numista_id=nid,
                written=written,
                sources_used=len(sources),
            )
        )

    return reports


def clear_for_iteration(*, iteration_id: str, store: Store | None = None) -> int:
    """Wipe persistent augmentations + the staging root for an iteration.

    Returns the number of per-coin snapshots removed. Used by the regenerate
    endpoint to force a clean rebuild.
    """
    store = store or Store(ML_DIR / "state" / "training.db")
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")

    removed = 0
    for eurio_id in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eurio_id)
        if nid is None:
            continue
        out_dir = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
        if out_dir.exists():
            shutil.rmtree(out_dir)
            removed += 1
    train_root = ITERATION_TRAIN_ROOTS / iteration_id
    if train_root.exists():
        shutil.rmtree(train_root)
    return removed


def list_for_iteration(
    *,
    iteration_id: str,
    store: Store | None = None,
) -> list[dict]:
    """Return per-coin lists of augmentation paths (relative to ``ml/``)."""
    store = store or Store(ML_DIR / "state" / "training.db")
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")
    out: list[dict] = []
    for eurio_id in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eurio_id)
        samples: list[str] = []
        if nid is not None:
            d = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
            if d.is_dir():
                samples = [
                    str(f.relative_to(ML_DIR)) for f in sorted(d.glob("sample_*.jpg"))
                ]
        out.append(
            {
                "eurio_id": eurio_id,
                "numista_id": nid,
                "samples": samples,
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Bake persistent augmentations for a Lab iteration")
    parser.add_argument("--iteration-id", required=True)
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Wipe existing snapshots before regenerating (force rebuild).",
    )
    args = parser.parse_args()

    if args.clear_first:
        clear_for_iteration(iteration_id=args.iteration_id)
    reports = generate_for_iteration(iteration_id=args.iteration_id)
    total_written = sum(r.written for r in reports)
    print(f"Iteration {args.iteration_id}: wrote {total_written} samples across {len(reports)} coin(s)")
    for r in reports:
        if r.skipped_reason:
            print(f"  {r.eurio_id} → SKIP: {r.skipped_reason}")
        else:
            print(f"  {r.eurio_id} (n{r.numista_id}): {r.written} samples ({r.sources_used} sources)")


if __name__ == "__main__":
    main()
