"""Per-class validation via fresh on-the-fly augmentations.

For each trained class, we sample N synthetic variations of its source images
through the same per-zone recipe used at training (perspective + relighting +
overlays) plus a 0–360° rotation, then run them through the model and check
whether the nearest ArcFace prototype is the correct class. The choice
matches the scan-time preprocessing more closely than a static train/val
split — see the design discussion in PR / chat for trade-offs.

This eval is meaningful even for classes with very few sources: 50
augmentations × 2 sources still gives 100 distinct samples drawn from the
same distribution the scan path inhabits.

Output: ml/output/per_class_metrics.json — consumed by the training runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from augmentations import AugmentationPipeline
from augmentations.recipes import ZONE_RECIPES
from eval.class_resolver import MANIFEST_FILENAME, build_resolver, read_manifest
from training.train_embedder import CoinEmbedder, get_val_transforms
from training.zone_resolver import fetch_eurio_zones, resolve_class_zones

DEFAULT_N_PER_CLASS = 50
DEFAULT_ZONE = "orange"


def _list_class_sources(train_dir: Path) -> dict[str, list[Path]]:
    """Map each class folder to its list of (source-image) Paths."""
    out: dict[str, list[Path]] = {}
    for cls_dir in sorted(p for p in train_dir.iterdir() if p.is_dir()):
        imgs = sorted(
            f for f in cls_dir.iterdir()
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        )
        if imgs:
            out[cls_dir.name] = imgs
    return out


def _load_arcface_prototypes(
    ckpt: dict,
) -> tuple[np.ndarray, list[str]] | None:
    """Return (W [num_classes, embedding_dim], class_order). None if absent."""
    W = ckpt.get("arcface_weights")
    classes = ckpt.get("classes")
    if W is None or not classes:
        return None
    if isinstance(W, list):
        W = torch.tensor(W)
    embedding_dim = ckpt["embedding_dim"]
    if W.shape[0] == embedding_dim:
        W = W.t()
    W = torch.nn.functional.normalize(W, p=2, dim=1).numpy()
    return W, list(classes)


def _build_eval_transform() -> transforms.Compose:
    """Option C — recipe stays in the per-class loop, here we add only the
    invariances a scan can't avoid (full 360° rotation) and the standard
    inference preprocessing (direct resize 224 + normalize, mirroring
    Android exactly)."""
    return transforms.Compose([
        transforms.RandomRotation(360),
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])


def _augmented_batches(
    sources: list[Path],
    pipeline: AugmentationPipeline,
    eval_transform,
    n_total: int,
    batch_size: int = 16,
) -> Iterable[torch.Tensor]:
    """Yield batches of `n_total` synthetic tensors built on the fly."""
    rng = np.random.default_rng()
    tensors: list[torch.Tensor] = []
    for i in range(n_total):
        src = sources[int(rng.integers(len(sources)))]
        with Image.open(src) as raw:
            pil = raw.convert("RGB")
            augmented = pipeline.generate(pil, count=1)[0]
        tensors.append(eval_transform(augmented))
        if len(tensors) == batch_size:
            yield torch.stack(tensors)
            tensors = []
    if tensors:
        yield torch.stack(tensors)


@torch.no_grad()
def compute(args: argparse.Namespace) -> None:
    device = torch.device("cpu")
    ckpt = torch.load(args.model, map_location=device, weights_only=False)
    embedding_dim = ckpt["embedding_dim"]
    model = CoinEmbedder(embedding_dim=embedding_dim)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    arcface = _load_arcface_prototypes(ckpt)
    if arcface is None:
        raise SystemExit(
            "Checkpoint has no arcface_weights — re-train with the current "
            "train_embedder.py to populate them. Validate now requires "
            "ArcFace prototypes to align with what is deployed on-device."
        )
    centroids, class_order = arcface
    class_index = {cls: i for i, cls in enumerate(class_order)}

    root = Path(args.dataset)
    train_dir = root / "train"
    if not train_dir.exists():
        raise SystemExit(f"No train/ directory under {root}")

    sources_by_class = _list_class_sources(train_dir)
    manifest = {d.class_id: d for d in read_manifest(root / MANIFEST_FILENAME)}

    # Resolve per-class zones — same source of truth as training. Falls back
    # to "orange" for classes missing from the confusion map (e.g. brand-new
    # additions before the next confusion run).
    resolver = build_resolver()
    eurio_zones = fetch_eurio_zones()
    class_zones = resolve_class_zones(
        sources_by_class.keys(), resolver, eurio_zones=eurio_zones
    )

    eval_transform = _build_eval_transform()
    pipelines: dict[str, AugmentationPipeline] = {}

    correct_by_class: dict[str, int] = defaultdict(int)
    total_by_class: dict[str, int] = defaultdict(int)
    n_sources_by_class: dict[str, int] = {}
    # Per-class cosine sim to the correct prototype, and margin to the
    # next-best prototype. R@1 is binary; these tell you HOW confidently
    # the model placed each augmentation, which is the metric that matches
    # what you read off the phone at scan-time.
    sims_by_class: dict[str, list[float]] = defaultdict(list)
    margins_by_class: dict[str, list[float]] = defaultdict(list)

    centroid_tensor = torch.tensor(centroids)  # [C, dim]

    for cls_name, sources in sources_by_class.items():
        if cls_name not in class_index:
            # Class on disk but not in the trained checkpoint — skip silently;
            # the runner will report it elsewhere if needed.
            continue
        zone = class_zones.get(cls_name, DEFAULT_ZONE)
        if zone not in ZONE_RECIPES:
            zone = DEFAULT_ZONE
        if zone not in pipelines:
            pipelines[zone] = AugmentationPipeline(ZONE_RECIPES[zone], seed=None)

        n_sources_by_class[cls_name] = len(sources)
        true_idx = class_index[cls_name]

        for batch in _augmented_batches(
            sources, pipelines[zone], eval_transform, args.n_per_class
        ):
            emb = model(batch)
            sims = emb @ centroid_tensor.T  # [B, C]
            preds = sims.argmax(dim=1).tolist()
            total_by_class[cls_name] += len(preds)
            correct_by_class[cls_name] += sum(1 for p in preds if p == true_idx)
            # cosine sim to the correct prototype
            true_sims = sims[:, true_idx].tolist()
            sims_by_class[cls_name].extend(true_sims)
            # margin = cos(true) - max cos(other)
            mask = torch.ones(sims.shape[1], dtype=torch.bool)
            if sims.shape[1] > 1:
                mask[true_idx] = False
                second_best = sims[:, mask].max(dim=1).values
                margins = (sims[:, true_idx] - second_best).tolist()
                margins_by_class[cls_name].extend(margins)

    def _stats(xs: list[float]) -> dict | None:
        if not xs:
            return None
        arr = np.array(xs)
        return {
            "mean": round(float(arr.mean()), 4),
            "min": round(float(arr.min()), 4),
            "p50": round(float(np.median(arr)), 4),
            "max": round(float(arr.max()), 4),
        }

    classes_out: list[dict] = []
    for cls in class_order:
        if cls not in n_sources_by_class:
            continue
        total = total_by_class.get(cls, 0)
        correct = correct_by_class.get(cls, 0)
        r1 = correct / total if total > 0 else None
        descriptor = manifest.get(cls)
        classes_out.append(
            {
                "class_id": cls,
                "class_kind": descriptor.class_kind if descriptor else "eurio_id",
                "recall_at_1": round(r1, 4) if r1 is not None else None,
                "n_sources": n_sources_by_class[cls],
                "n_augmentations": total,
                "zone": class_zones.get(cls, DEFAULT_ZONE),
                "cosine_to_self": _stats(sims_by_class[cls]),
                "margin_to_runner_up": _stats(margins_by_class[cls]),
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"classes": classes_out}, indent=2))
    print(
        f"Wrote {len(classes_out)} per-class metrics to {output_path}"
    )
    for c in classes_out:
        r1 = c["recall_at_1"]
        r1_str = f"{r1:.2%}" if r1 is not None else "n/a"
        cs = c.get("cosine_to_self") or {}
        mg = c.get("margin_to_runner_up") or {}
        cos_str = (
            f"cos[mean={cs.get('mean')}, p50={cs.get('p50')}, "
            f"min={cs.get('min')}]"
        ) if cs else "cos=n/a"
        margin_str = (
            f"margin[mean={mg.get('mean')}, min={mg.get('min')}]"
        ) if mg else ""
        print(
            f"  {c['class_id']:<55} R@1={r1_str}  "
            f"{cos_str}  {margin_str}  "
            f"(n_augs={c['n_augmentations']}, n_sources={c['n_sources']}, zone={c['zone']})"
        )


def main():
    parser = argparse.ArgumentParser(description="Per-class R@1 over fresh augmentations")
    parser.add_argument("--model", type=str, default="./checkpoints/best_model.pth")
    parser.add_argument("--dataset", type=str, default="./datasets/eurio-poc")
    parser.add_argument("--output", type=str, default="./output/per_class_metrics.json")
    parser.add_argument(
        "--n-per-class",
        type=int,
        default=DEFAULT_N_PER_CLASS,
        help="Number of synthetic augmentations sampled per class (default 50).",
    )
    args = parser.parse_args()
    compute(args)


if __name__ == "__main__":
    main()
