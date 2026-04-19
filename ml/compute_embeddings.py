"""Compute reference (centroid) embeddings for each coin class.

Output:
  - embeddings_v1.json — rich per-class info (class_kind, member eurio_ids,
    embedding). Consumed by seed_supabase and other ML tooling.
  - coin_embeddings.json — flat numista_id → embedding map. Preserved for
    the Android reader (EmbeddingMatcher). For a design_group class the
    same centroid is emitted once per member numista_id.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from class_resolver import MANIFEST_FILENAME, read_manifest
from train_embedder import CoinEmbedder, get_val_transforms

CATALOG_PATH = Path(__file__).parent / "datasets" / "coin_catalog.json"


def load_display_names() -> dict[str, str]:
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            catalog = json.load(f)["coins"]
        return {k: v.get("name", k) for k, v in catalog.items()}
    return {}


@torch.no_grad()
def compute(args: argparse.Namespace) -> None:
    device = torch.device("cpu")

    checkpoint = torch.load(args.model, map_location=device, weights_only=False)
    embedding_dim = checkpoint["embedding_dim"]
    model = CoinEmbedder(embedding_dim=embedding_dim)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    print(f"Model from epoch {checkpoint['epoch']}, dim={embedding_dim}")

    dataset_root = Path(args.dataset)
    manifest = read_manifest(dataset_root / MANIFEST_FILENAME)
    manifest_by_class = {d.class_id: d for d in manifest}
    if not manifest_by_class:
        print(
            f"WARNING: no class manifest at {dataset_root / MANIFEST_FILENAME}; "
            "class_kind will default to eurio_id."
        )

    class_embeddings: dict[str, list[np.ndarray]] = {}
    for split in ("train", "val", "test"):
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue

        dataset = ImageFolder(str(split_dir), transform=get_val_transforms())
        loader = DataLoader(dataset, batch_size=32, shuffle=False, num_workers=0)

        for images, labels in loader:
            emb = model(images).numpy()
            for i, label in enumerate(labels):
                cls_name = dataset.classes[label]
                class_embeddings.setdefault(cls_name, []).append(emb[i])

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    display_names = load_display_names()
    coins_full: dict[str, dict] = {}
    coins_flat: dict[str, list[float]] = {}

    model_version = args.model_version
    if not model_version:
        ckpt_version = checkpoint.get("model_version")
        if ckpt_version:
            model_version = ckpt_version
        else:
            model_version = f"v1-{checkpoint.get('mode', 'unknown')}"

    for class_id, emb_list in sorted(class_embeddings.items()):
        stacked = np.stack(emb_list)
        centroid = stacked.mean(axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        embedding_list = [round(float(x), 6) for x in centroid]

        descriptor = manifest_by_class.get(class_id)
        class_kind = descriptor.class_kind if descriptor else "eurio_id"
        numista_ids = list(descriptor.numista_ids) if descriptor else []
        eurio_ids = list(descriptor.eurio_ids) if descriptor else []
        display_name = display_names.get(class_id, class_id)

        coins_full[class_id] = {
            "name": display_name,
            "class_kind": class_kind,
            "numista_ids": numista_ids,
            "eurio_ids": eurio_ids,
            "n_samples": len(emb_list),
            "embedding": embedding_list,
        }

        for nid in numista_ids:
            coins_flat[str(nid)] = embedding_list
        if not numista_ids:
            # Fallback: no numista mapping available (manifest missing).
            coins_flat[class_id] = embedding_list

        print(f"  {class_id} [{class_kind}]: {len(emb_list)} imgs → centroid")

    full_output = {
        "version": "1.0",
        "model": model_version,
        "embedding_dim": embedding_dim,
        "coins": coins_full,
    }
    full_path = output_dir / "embeddings_v1.json"
    full_path.write_text(json.dumps(full_output, indent=2))
    print(f"\nFull embeddings: {full_path}")

    flat_path = output_dir / "coin_embeddings.json"
    flat_path.write_text(json.dumps(coins_flat))
    print(f"Flat embeddings: {flat_path} ({flat_path.stat().st_size / 1024:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(description="Compute reference embeddings")
    parser.add_argument("--model", type=str, default="./checkpoints/best_model.pth")
    parser.add_argument("--dataset", type=str, default="./datasets/eurio-poc")
    parser.add_argument("--output-dir", type=str, default="./output")
    parser.add_argument(
        "--model-version",
        type=str,
        default="",
        help="Override model version string (else read from checkpoint or derived).",
    )
    args = parser.parse_args()
    compute(args)


if __name__ == "__main__":
    main()
