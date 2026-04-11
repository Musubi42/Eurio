"""Evaluate the trained coin embedder on the test set."""

import argparse
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from train_embedder import CoinEmbedder, get_val_transforms


@torch.no_grad()
def evaluate(args):
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

    classes = checkpoint["classes"]
    print(f"Model from epoch {checkpoint['epoch']}, embedding_dim={checkpoint['embedding_dim']}")
    print(f"Classes: {classes}")

    # Load test dataset
    dataset = ImageFolder(args.test_dataset, transform=get_val_transforms())
    loader = DataLoader(dataset, batch_size=32, shuffle=False, num_workers=0)

    print(f"Test images: {len(dataset)}")

    # Compute all embeddings
    all_embeddings = []
    all_labels = []

    for images, labels in loader:
        images = images.to(device)
        emb = model(images)
        all_embeddings.append(emb.cpu())
        all_labels.append(labels)

    embeddings = torch.cat(all_embeddings, dim=0)
    labels = torch.cat(all_labels, dim=0)

    n = len(labels)
    if n < 2:
        print("Not enough test images for evaluation.")
        return

    # Pairwise similarity
    sim_matrix = embeddings @ embeddings.T
    sim_matrix.fill_diagonal_(-1.0)

    # Global Recall@K
    print(f"\n{'Metric':<15} {'Value':>8}")
    print("-" * 25)
    for k in [1, 3]:
        if k >= n:
            continue
        topk_indices = sim_matrix.topk(k, dim=1).indices
        topk_labels = labels[topk_indices]
        correct = (topk_labels == labels.unsqueeze(1)).any(dim=1)
        recall = correct.float().mean().item()
        print(f"  Recall@{k:<6} {recall:>8.2%}")

    # Per-class accuracy (nearest-neighbor classification)
    print(f"\n{'Class':<55} {'N':>3} {'R@1':>6}")
    print("-" * 68)
    nn_indices = sim_matrix.argmax(dim=1)
    nn_labels = labels[nn_indices]

    for cls_idx, cls_name in enumerate(dataset.classes):
        mask = labels == cls_idx
        if mask.sum() == 0:
            continue
        cls_correct = (nn_labels[mask] == cls_idx).float().mean().item()
        cls_n = mask.sum().item()
        print(f"  {cls_name:<53} {cls_n:>3} {cls_correct:>6.2%}")

    # Show individual predictions
    print(f"\n{'Image':<30} {'True':<25} {'Predicted':<25} {'Sim':>6} {'OK':>3}")
    print("-" * 92)
    for i in range(n):
        true_cls = dataset.classes[labels[i]]
        pred_idx = nn_indices[i]
        pred_cls = dataset.classes[labels[pred_idx]]
        sim = sim_matrix[i, pred_idx].item()
        ok = "+" if true_cls == pred_cls else "X"
        img_name = Path(dataset.samples[i][0]).name
        print(f"  {img_name:<28} {true_cls:<25} {pred_cls:<25} {sim:>6.3f} {ok:>3}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate coin embedder")
    parser.add_argument(
        "--model", type=str,
        default="./checkpoints/best_model.pth",
        help="Path to model checkpoint",
    )
    parser.add_argument(
        "--test-dataset", type=str,
        default="./datasets/eurio-poc/test",
        help="Test dataset directory",
    )
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()
    evaluate(args)


if __name__ == "__main__":
    main()
