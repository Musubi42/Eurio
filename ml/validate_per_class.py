"""Compute per-class Recall@1 for the current trained model.

For each trained class, we build its centroid from the train split, then
measure how many val-split samples of that class retrieve it as nearest
among all centroids. This is cheap (one forward pass) and gives an honest
per-class quality signal independent of the overall model R@1.

Output: ml/output/per_class_metrics.json — consumed by the training runner.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from class_resolver import MANIFEST_FILENAME, read_manifest
from train_embedder import CoinEmbedder, get_val_transforms


@torch.no_grad()
def compute(args: argparse.Namespace) -> None:
    device = torch.device("cpu")
    ckpt = torch.load(args.model, map_location=device, weights_only=False)
    model = CoinEmbedder(embedding_dim=ckpt["embedding_dim"])
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    root = Path(args.dataset)
    manifest = {d.class_id: d for d in read_manifest(root / MANIFEST_FILENAME)}

    train_ds = ImageFolder(str(root / "train"), transform=get_val_transforms())
    val_dir = root / "val"

    # Build train-centroid gallery
    train_embs_by_class: dict[str, list[np.ndarray]] = defaultdict(list)
    for images, labels in DataLoader(train_ds, batch_size=32, shuffle=False, num_workers=0):
        emb = model(images).numpy()
        for i, label in enumerate(labels):
            train_embs_by_class[train_ds.classes[label]].append(emb[i])

    class_order = sorted(train_embs_by_class.keys())
    centroids = []
    for cls in class_order:
        c = np.stack(train_embs_by_class[cls]).mean(axis=0)
        n = np.linalg.norm(c)
        centroids.append(c / n if n > 0 else c)
    centroid_matrix = np.stack(centroids) if centroids else np.zeros((0, 256))

    n_val_by_class: dict[str, int] = defaultdict(int)
    correct_by_class: dict[str, int] = defaultdict(int)
    if val_dir.exists() and any(val_dir.iterdir()):
        val_ds = ImageFolder(str(val_dir), transform=get_val_transforms())
        for images, labels in DataLoader(val_ds, batch_size=32, shuffle=False, num_workers=0):
            emb = model(images).numpy()
            if centroid_matrix.size == 0:
                continue
            sims = emb @ centroid_matrix.T
            pred_idx = sims.argmax(axis=1)
            for i, label in enumerate(labels):
                true_class = val_ds.classes[label]
                n_val_by_class[true_class] += 1
                if class_order[pred_idx[i]] == true_class:
                    correct_by_class[true_class] += 1

    classes_out: list[dict] = []
    for cls in class_order:
        n_val = n_val_by_class.get(cls, 0)
        n_train = len(train_embs_by_class[cls])
        r1 = correct_by_class.get(cls, 0) / n_val if n_val > 0 else None
        descriptor = manifest.get(cls)
        classes_out.append(
            {
                "class_id": cls,
                "class_kind": descriptor.class_kind if descriptor else "eurio_id",
                "recall_at_1": round(r1, 4) if r1 is not None else None,
                "n_train_images": n_train,
                "n_val_images": n_val,
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
        print(
            f"  {c['class_id']:<55} R@1={r1_str}  "
            f"n_train={c['n_train_images']}  n_val={c['n_val_images']}"
        )


def main():
    parser = argparse.ArgumentParser(description="Compute per-class Recall@1")
    parser.add_argument("--model", type=str, default="./checkpoints/best_model.pth")
    parser.add_argument("--dataset", type=str, default="./datasets/eurio-poc")
    parser.add_argument("--output", type=str, default="./output/per_class_metrics.json")
    args = parser.parse_args()
    compute(args)


if __name__ == "__main__":
    main()
