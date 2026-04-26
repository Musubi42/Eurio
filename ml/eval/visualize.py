"""Visualize embeddings with t-SNE and plot training loss curves."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
from sklearn.manifold import TSNE
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from training.train_embedder import CoinEmbedder, get_val_transforms


@torch.no_grad()
def compute_all_embeddings(model, dataset_dir, device):
    """Compute embeddings for all images in a dataset directory."""
    dataset = ImageFolder(dataset_dir, transform=get_val_transforms())
    loader = DataLoader(dataset, batch_size=32, shuffle=False, num_workers=0)

    all_embeddings = []
    all_labels = []

    for images, labels in loader:
        images = images.to(device)
        emb = model(images)
        all_embeddings.append(emb.cpu().numpy())
        all_labels.append(labels.numpy())

    return (
        np.concatenate(all_embeddings, axis=0),
        np.concatenate(all_labels, axis=0),
        dataset.classes,
    )


def plot_tsne(embeddings, labels, class_names, output_path):
    """Create a t-SNE scatter plot of embeddings."""
    n = len(embeddings)
    perplexity = min(10, n - 1)  # Must be < n

    tsne = TSNE(n_components=2, perplexity=perplexity, random_state=42, n_iter=1000)
    coords = tsne.fit_transform(embeddings)

    fig, ax = plt.subplots(figsize=(10, 8))

    unique_labels = np.unique(labels)
    colors = plt.cm.tab10(np.linspace(0, 1, len(unique_labels)))

    for label_idx, color in zip(unique_labels, colors):
        mask = labels == label_idx
        name = class_names[label_idx]
        # Shorten long names for legend
        short_name = name[:35] + "..." if len(name) > 35 else name
        ax.scatter(coords[mask, 0], coords[mask, 1], c=[color], label=short_name, s=80, alpha=0.8)

    ax.legend(loc="best", fontsize=8)
    ax.set_title("t-SNE — Coin Embeddings")
    ax.set_xlabel("t-SNE 1")
    ax.set_ylabel("t-SNE 2")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"t-SNE plot saved to {output_path}")


def plot_training_curves(log_path, output_path):
    """Plot training loss and recall curves."""
    with open(log_path) as f:
        log = json.load(f)

    epochs = [e["epoch"] for e in log]
    losses = [e["train_loss"] for e in log]
    r1 = [e["recall@1"] for e in log]
    r3 = [e["recall@3"] for e in log]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Loss curve
    ax1.plot(epochs, losses, "b-o", markersize=4)
    ax1.set_title("Training Loss")
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("Triplet Loss")
    ax1.grid(True, alpha=0.3)

    # Recall curves
    ax2.plot(epochs, r1, "g-o", markersize=4, label="Recall@1")
    ax2.plot(epochs, r3, "r-s", markersize=4, label="Recall@3")
    ax2.set_title("Validation Recall")
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Recall")
    ax2.set_ylim(0, 1.05)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Training curves saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Visualize coin embeddings")
    parser.add_argument(
        "--model", type=str,
        default="./checkpoints/best_model.pth",
    )
    parser.add_argument(
        "--dataset", type=str,
        default="./datasets/eurio-poc",
        help="Root dataset dir (will use all splits)",
    )
    parser.add_argument(
        "--training-log", type=str,
        default="./checkpoints/training_log.json",
    )
    parser.add_argument("--output-dir", type=str, default="./output")
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Device
    if args.device == "auto":
        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    else:
        device = torch.device(args.device)

    # Load model
    checkpoint = torch.load(args.model, map_location=device, weights_only=False)
    model = CoinEmbedder(embedding_dim=checkpoint["embedding_dim"]).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    # Collect embeddings from all splits
    all_embeddings = []
    all_labels = []
    class_names = None

    dataset_root = Path(args.dataset)
    for split in ["train", "val", "test"]:
        split_dir = dataset_root / split
        if split_dir.exists():
            emb, lbl, names = compute_all_embeddings(model, str(split_dir), device)
            all_embeddings.append(emb)
            all_labels.append(lbl)
            if class_names is None:
                class_names = names

    embeddings = np.concatenate(all_embeddings, axis=0)
    labels = np.concatenate(all_labels, axis=0)

    print(f"Total embeddings: {len(embeddings)}, classes: {len(class_names)}")

    # t-SNE
    plot_tsne(embeddings, labels, class_names, output_dir / "tsne_plot.png")

    # Training curves
    log_path = Path(args.training_log)
    if log_path.exists():
        plot_training_curves(log_path, output_dir / "training_curves.png")
    else:
        print(f"Training log not found at {log_path}, skipping curves.")


if __name__ == "__main__":
    main()
