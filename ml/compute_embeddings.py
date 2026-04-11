"""Compute reference (centroid) embeddings for each coin class."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from train_embedder import CoinEmbedder, get_val_transforms

CATALOG_PATH = Path(__file__).parent / "datasets" / "coin_catalog.json"


def load_display_names() -> dict[str, str]:
    """Load display names from coin_catalog.json."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            catalog = json.load(f)["coins"]
        return {k: v["name"] for k, v in catalog.items()}
    return {}


@torch.no_grad()
def compute(args):
    device = torch.device("cpu")  # No need for GPU here

    # Load model
    checkpoint = torch.load(args.model, map_location=device, weights_only=False)
    model = CoinEmbedder(embedding_dim=checkpoint["embedding_dim"])
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    embedding_dim = checkpoint["embedding_dim"]
    print(f"Model from epoch {checkpoint['epoch']}, dim={embedding_dim}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_root = Path(args.dataset)

    # Collect embeddings per class from all splits
    class_embeddings: dict[str, list[np.ndarray]] = {}

    for split in ["train", "val", "test"]:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue

        dataset = ImageFolder(str(split_dir), transform=get_val_transforms())
        loader = DataLoader(dataset, batch_size=32, shuffle=False, num_workers=0)

        for images, labels in loader:
            emb = model(images).numpy()
            for i, label in enumerate(labels):
                cls_name = dataset.classes[label]
                if cls_name not in class_embeddings:
                    class_embeddings[cls_name] = []
                class_embeddings[cls_name].append(emb[i])

    # Compute centroids
    display_names = load_display_names()
    coins_full = {}
    coins_flat = {}

    for cls_name, emb_list in sorted(class_embeddings.items()):
        embeddings = np.stack(emb_list)
        centroid = embeddings.mean(axis=0)
        centroid = centroid / np.linalg.norm(centroid)  # L2 normalize

        display_name = display_names.get(cls_name, cls_name)
        embedding_list = [round(float(x), 6) for x in centroid]

        coins_full[cls_name] = {
            "name": display_name,
            "embedding": embedding_list,
        }
        coins_flat[cls_name] = embedding_list

        print(f"  {cls_name}: {len(emb_list)} images → centroid computed")

    # Full metadata JSON
    full_output = {
        "version": "1.0",
        "model": "eurio_embedder_v1",
        "embedding_dim": embedding_dim,
        "coins": coins_full,
    }

    full_path = output_dir / "embeddings_v1.json"
    with open(full_path, "w") as f:
        json.dump(full_output, f, indent=2)
    print(f"\nFull embeddings: {full_path}")

    # Flat JSON for Android
    flat_path = output_dir / "coin_embeddings.json"
    with open(flat_path, "w") as f:
        json.dump(coins_flat, f)
    print(f"Flat embeddings: {flat_path} ({flat_path.stat().st_size / 1024:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(description="Compute reference embeddings")
    parser.add_argument("--model", type=str, default="./checkpoints/best_model.pth")
    parser.add_argument("--dataset", type=str, default="./datasets/eurio-poc")
    parser.add_argument("--output-dir", type=str, default="./output")
    args = parser.parse_args()
    compute(args)


if __name__ == "__main__":
    main()
