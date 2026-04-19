"""Train a coin recognition model (MobileNetV3-Small).

Supports two modes:
  --mode classify   Cross-entropy classification (few classes, few images — stable)
  --mode embed      Metric learning with triplet loss (many classes — future)
"""

import argparse
import json
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import Adam
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader
from torchvision import models, transforms
from torchvision.datasets import ImageFolder
from torchvision.models import MobileNet_V3_Small_Weights
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CoinEmbedder(nn.Module):
    """MobileNetV3-Small backbone + projection head → L2-normalized embeddings."""

    def __init__(self, embedding_dim: int = 256):
        super().__init__()
        backbone = models.mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
        backbone.classifier = nn.Identity()
        self.backbone = backbone  # outputs 576-dim
        self.head = nn.Linear(576, embedding_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.backbone(x)
        embeddings = self.head(features)
        return F.normalize(embeddings, p=2, dim=1)


class CoinClassifier(nn.Module):
    """MobileNetV3-Small backbone + classification head → class logits."""

    def __init__(self, num_classes: int):
        super().__init__()
        backbone = models.mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
        backbone.classifier = nn.Identity()
        self.backbone = backbone  # outputs 576-dim
        self.head = nn.Sequential(
            nn.Linear(576, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.backbone(x)
        return self.head(features)


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def get_train_transforms() -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize((256, 256)),
        transforms.RandomCrop(224),
        transforms.RandomRotation(360),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.RandomPerspective(distortion_scale=0.2, p=0.5),
        transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2, hue=0.05),
        transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 1.0)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])


def get_val_transforms() -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize((256, 256)),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@torch.no_grad()
def compute_accuracy(model, dataloader, device):
    """Compute top-1 and top-3 accuracy for a classifier."""
    model.eval()
    correct_1 = 0
    correct_3 = 0
    total = 0

    for images, labels in dataloader:
        images, labels = images.to(device), labels.to(device)
        logits = model(images)

        # Top-1
        pred = logits.argmax(dim=1)
        correct_1 += (pred == labels).sum().item()

        # Top-3
        _, topk = logits.topk(min(3, logits.size(1)), dim=1)
        correct_3 += (topk == labels.unsqueeze(1)).any(dim=1).sum().item()

        total += labels.size(0)

    return {
        "accuracy": correct_1 / max(total, 1),
        "top3_accuracy": correct_3 / max(total, 1),
    }


@torch.no_grad()
def compute_recall_at_k(model, dataloader, device, k_values=(1, 3)):
    """Compute Recall@K for an embedding model."""
    model.eval()
    all_embeddings = []
    all_labels = []

    for images, labels in dataloader:
        images = images.to(device)
        emb = model(images)
        all_embeddings.append(emb.cpu())
        all_labels.append(labels)

    embeddings = torch.cat(all_embeddings, dim=0)
    labels = torch.cat(all_labels, dim=0)

    sim_matrix = embeddings @ embeddings.T
    sim_matrix.fill_diagonal_(-1.0)

    results = {}
    for k in k_values:
        topk_indices = sim_matrix.topk(k, dim=1).indices
        topk_labels = labels[topk_indices]
        correct = (topk_labels == labels.unsqueeze(1)).any(dim=1)
        results[f"recall@{k}"] = correct.float().mean().item()

    return results


# ---------------------------------------------------------------------------
# Device helper
# ---------------------------------------------------------------------------

def get_device(device_str: str) -> torch.device:
    if device_str == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(device_str)


# ---------------------------------------------------------------------------
# Training — Classification
# ---------------------------------------------------------------------------

def train_classifier(args):
    device = get_device(args.device)
    print(f"Mode: classify | Device: {device}")

    # Data
    train_dataset = ImageFolder(args.dataset, transform=get_train_transforms())
    val_dataset = ImageFolder(args.val_dataset, transform=get_val_transforms())
    num_classes = len(train_dataset.classes)

    print(f"Train: {len(train_dataset)} images, {num_classes} classes")
    print(f"Val:   {len(val_dataset)} images")
    print(f"Classes: {train_dataset.classes}")

    # Oversample: each epoch sees 10x the dataset (augmented differently each time)
    from torch.utils.data import WeightedRandomSampler
    class_counts = [0] * num_classes
    for _, label in train_dataset.samples:
        class_counts[label] += 1
    weights = [1.0 / class_counts[label] for _, label in train_dataset.samples]
    effective_epoch_size = len(train_dataset) * 10
    sampler = WeightedRandomSampler(weights, num_samples=effective_epoch_size, replacement=True)

    use_cuda = device.type == "cuda"
    n_workers = args.num_workers if args.num_workers >= 0 else (4 if use_cuda else 0)

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, sampler=sampler,
        num_workers=n_workers, pin_memory=use_cuda, persistent_workers=n_workers > 0,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False,
        num_workers=n_workers, pin_memory=use_cuda, persistent_workers=n_workers > 0,
    )

    # Model
    model = CoinClassifier(num_classes=num_classes).to(device)
    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    loss_fn = nn.CrossEntropyLoss()

    # Freeze backbone initially
    for param in model.backbone.parameters():
        param.requires_grad = False

    optimizer = Adam(model.head.parameters(), lr=args.lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.lr * 0.01)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    best_acc = 0.0
    training_log = []

    for epoch in range(1, args.epochs + 1):
        if epoch == args.freeze_epochs + 1:
            print(f"\n--- Unfreezing backbone at epoch {epoch} ---")
            for param in model.backbone.parameters():
                param.requires_grad = True
            optimizer = Adam([
                {"params": model.backbone.parameters(), "lr": args.lr * 0.1},
                {"params": model.head.parameters(), "lr": args.lr},
            ])
            scheduler = CosineAnnealingLR(
                optimizer, T_max=args.epochs - args.freeze_epochs, eta_min=args.lr * 0.01
            )

        model.train()
        epoch_loss = 0.0
        epoch_correct = 0
        epoch_total = 0

        pbar = tqdm(train_loader, desc=f"Epoch {epoch:>2}/{args.epochs}")
        for images, labels in pbar:
            images, labels = images.to(device), labels.to(device)

            logits = model(images)
            loss = loss_fn(logits, labels)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            epoch_correct += (logits.argmax(dim=1) == labels).sum().item()
            epoch_total += labels.size(0)
            pbar.set_postfix(loss=f"{loss.item():.4f}")

        scheduler.step()

        train_acc = epoch_correct / max(epoch_total, 1)
        avg_loss = epoch_loss / max(len(train_loader), 1)

        val_metrics = compute_accuracy(model, val_loader, device)

        log_entry = {
            "epoch": epoch,
            "train_loss": round(avg_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_acc": round(val_metrics["accuracy"], 4),
            "val_top3_acc": round(val_metrics["top3_accuracy"], 4),
            "lr": round(scheduler.get_last_lr()[0], 6),
        }
        training_log.append(log_entry)

        frozen_str = " [frozen]" if epoch <= args.freeze_epochs else ""
        print(
            f"  Epoch {epoch:>2} — loss: {avg_loss:.4f}  "
            f"train_acc: {train_acc:.2%}  "
            f"val_acc: {val_metrics['accuracy']:.2%}  "
            f"val_top3: {val_metrics['top3_accuracy']:.2%}"
            f"{frozen_str}"
        )

        if val_metrics["accuracy"] >= best_acc:
            best_acc = val_metrics["accuracy"]
            torch.save({
                "epoch": epoch,
                "mode": "classify",
                "model_state_dict": model.state_dict(),
                "num_classes": num_classes,
                "accuracy": val_metrics["accuracy"],
                "top3_accuracy": val_metrics["top3_accuracy"],
                "classes": train_dataset.classes,
                "model_version": args.model_version,
            }, output_dir / "best_model.pth")
            print(f"  → Saved best model (acc: {best_acc:.2%})")

    with open(output_dir / "training_log.json", "w") as f:
        json.dump(training_log, f, indent=2)

    print(f"\nTraining complete. Best accuracy: {best_acc:.2%}")


# ---------------------------------------------------------------------------
# Training — Embedding (metric learning)
# ---------------------------------------------------------------------------

def train_embedder(args):
    from pytorch_metric_learning.losses import TripletMarginLoss
    from pytorch_metric_learning.miners import BatchHardMiner
    from pytorch_metric_learning.samplers import MPerClassSampler

    device = get_device(args.device)
    print(f"Mode: embed (triplet) | Device: {device}")

    train_dataset = ImageFolder(args.dataset, transform=get_train_transforms())
    val_dataset = ImageFolder(args.val_dataset, transform=get_val_transforms())

    print(f"Train: {len(train_dataset)} images, {len(train_dataset.classes)} classes")
    print(f"Val:   {len(val_dataset)} images")
    print(f"Classes: {train_dataset.classes}")

    effective_epoch_size = len(train_dataset) * 10
    sampler = MPerClassSampler(
        labels=train_dataset.targets,
        m=args.m_per_class,
        length_before_new_iter=effective_epoch_size,
    )

    use_cuda = device.type == "cuda"
    n_workers = args.num_workers if args.num_workers >= 0 else (4 if use_cuda else 0)

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, sampler=sampler,
        num_workers=n_workers, pin_memory=use_cuda, persistent_workers=n_workers > 0,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False,
        num_workers=n_workers, pin_memory=use_cuda, persistent_workers=n_workers > 0,
    )

    model = CoinEmbedder(embedding_dim=args.embedding_dim).to(device)
    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    loss_fn = TripletMarginLoss(margin=args.margin)
    miner = BatchHardMiner()

    for param in model.backbone.parameters():
        param.requires_grad = False

    optimizer = Adam(model.head.parameters(), lr=args.lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.lr * 0.01)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    best_recall = 0.0
    training_log = []

    for epoch in range(1, args.epochs + 1):
        if epoch == args.freeze_epochs + 1:
            print(f"\n--- Unfreezing backbone at epoch {epoch} ---")
            for param in model.backbone.parameters():
                param.requires_grad = True
            optimizer = Adam([
                {"params": model.backbone.parameters(), "lr": args.lr * 0.1},
                {"params": model.head.parameters(), "lr": args.lr},
            ])
            scheduler = CosineAnnealingLR(
                optimizer, T_max=args.epochs - args.freeze_epochs, eta_min=args.lr * 0.01
            )

        model.train()
        epoch_loss = 0.0
        n_batches = 0

        pbar = tqdm(train_loader, desc=f"Epoch {epoch:>2}/{args.epochs}")
        for images, labels in pbar:
            images, labels = images.to(device), labels.to(device)
            embeddings = model(images)
            hard_pairs = miner(embeddings, labels)
            loss = loss_fn(embeddings, labels, hard_pairs)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1
            pbar.set_postfix(loss=f"{loss.item():.4f}")

        scheduler.step()
        avg_loss = epoch_loss / max(n_batches, 1)

        val_metrics = compute_recall_at_k(model, val_loader, device, k_values=(1, 3))

        log_entry = {
            "epoch": epoch,
            "train_loss": round(avg_loss, 4),
            "recall@1": round(val_metrics["recall@1"], 4),
            "recall@3": round(val_metrics["recall@3"], 4),
            "lr": round(scheduler.get_last_lr()[0], 6),
        }
        training_log.append(log_entry)

        frozen_str = " [frozen]" if epoch <= args.freeze_epochs else ""
        print(
            f"  Epoch {epoch:>2} — loss: {avg_loss:.4f}  "
            f"R@1: {val_metrics['recall@1']:.2%}  "
            f"R@3: {val_metrics['recall@3']:.2%}"
            f"{frozen_str}"
        )

        if val_metrics["recall@1"] >= best_recall:
            best_recall = val_metrics["recall@1"]
            torch.save({
                "epoch": epoch,
                "mode": "embed",
                "model_state_dict": model.state_dict(),
                "embedding_dim": args.embedding_dim,
                "recall@1": val_metrics["recall@1"],
                "recall@3": val_metrics["recall@3"],
                "classes": train_dataset.classes,
                "model_version": args.model_version,
            }, output_dir / "best_model.pth")
            print(f"  → Saved best model (R@1: {best_recall:.2%})")

    with open(output_dir / "training_log.json", "w") as f:
        json.dump(training_log, f, indent=2)

    print(f"\nTraining complete. Best Recall@1: {best_recall:.2%}")


# ---------------------------------------------------------------------------
# Training — ArcFace (metric learning, stable with few images)
# ---------------------------------------------------------------------------

def train_arcface(args):
    from pytorch_metric_learning.losses import ArcFaceLoss
    from pytorch_metric_learning.samplers import MPerClassSampler

    device = get_device(args.device)
    print(f"Mode: arcface | Device: {device}")

    train_dataset = ImageFolder(args.dataset, transform=get_train_transforms())
    val_dataset = ImageFolder(args.val_dataset, transform=get_val_transforms())
    num_classes = len(train_dataset.classes)

    print(f"Train: {len(train_dataset)} images, {num_classes} classes")
    print(f"Val:   {len(val_dataset)} images")
    print(f"Classes: {train_dataset.classes}")

    effective_epoch_size = len(train_dataset) * 10
    sampler = MPerClassSampler(
        labels=train_dataset.targets,
        m=args.m_per_class,
        length_before_new_iter=effective_epoch_size,
    )

    # num_workers > 0 parallelizes image loading across CPU cores
    # pin_memory speeds up CPU→GPU transfers on CUDA
    use_cuda = device.type == "cuda"
    n_workers = args.num_workers if args.num_workers >= 0 else (4 if use_cuda else 0)

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        sampler=sampler,
        num_workers=n_workers,
        pin_memory=use_cuda,
        persistent_workers=n_workers > 0,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=n_workers,
        pin_memory=use_cuda,
        persistent_workers=n_workers > 0,
    )

    # Model: same CoinEmbedder backbone + projection → L2-normalized embeddings
    model = CoinEmbedder(embedding_dim=args.embedding_dim).to(device)
    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    # ArcFace loss has its own weight matrix W (num_classes × embedding_dim)
    # It needs a SEPARATE optimizer
    loss_fn = ArcFaceLoss(
        num_classes=num_classes,
        embedding_size=args.embedding_dim,
        margin=args.arcface_margin,
        scale=args.arcface_scale,
    ).to(device)

    print(f"ArcFace: margin={args.arcface_margin}°, scale={args.arcface_scale}")

    # Freeze backbone initially
    for param in model.backbone.parameters():
        param.requires_grad = False

    model_optimizer = Adam(model.head.parameters(), lr=args.lr)
    loss_optimizer = torch.optim.SGD(loss_fn.parameters(), lr=0.01)
    scheduler = CosineAnnealingLR(model_optimizer, T_max=args.epochs, eta_min=args.lr * 0.01)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    best_recall = 0.0
    training_log = []

    for epoch in range(1, args.epochs + 1):
        if epoch == args.freeze_epochs + 1:
            print(f"\n--- Unfreezing backbone at epoch {epoch} ---")
            for param in model.backbone.parameters():
                param.requires_grad = True
            model_optimizer = Adam([
                {"params": model.backbone.parameters(), "lr": args.lr * 0.1},
                {"params": model.head.parameters(), "lr": args.lr},
            ])
            scheduler = CosineAnnealingLR(
                model_optimizer, T_max=args.epochs - args.freeze_epochs, eta_min=args.lr * 0.01
            )

        model.train()
        loss_fn.train()
        epoch_loss = 0.0
        n_batches = 0

        pbar = tqdm(train_loader, desc=f"Epoch {epoch:>2}/{args.epochs}")
        for images, labels in pbar:
            images, labels = images.to(device), labels.to(device)

            embeddings = model(images)
            loss = loss_fn(embeddings, labels)

            model_optimizer.zero_grad()
            loss_optimizer.zero_grad()
            loss.backward()
            model_optimizer.step()
            loss_optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1
            pbar.set_postfix(loss=f"{loss.item():.4f}")

        scheduler.step()
        avg_loss = epoch_loss / max(n_batches, 1)

        val_metrics = compute_recall_at_k(model, val_loader, device, k_values=(1, 3))

        log_entry = {
            "epoch": epoch,
            "train_loss": round(avg_loss, 4),
            "recall@1": round(val_metrics["recall@1"], 4),
            "recall@3": round(val_metrics["recall@3"], 4),
            "lr": round(scheduler.get_last_lr()[0], 6),
        }
        training_log.append(log_entry)

        frozen_str = " [frozen]" if epoch <= args.freeze_epochs else ""
        print(
            f"  Epoch {epoch:>2} — loss: {avg_loss:.4f}  "
            f"R@1: {val_metrics['recall@1']:.2%}  "
            f"R@3: {val_metrics['recall@3']:.2%}"
            f"{frozen_str}"
        )

        if val_metrics["recall@1"] >= best_recall:
            best_recall = val_metrics["recall@1"]
            torch.save({
                "epoch": epoch,
                "mode": "arcface",
                "model_state_dict": model.state_dict(),
                "embedding_dim": args.embedding_dim,
                "num_classes": num_classes,
                "recall@1": val_metrics["recall@1"],
                "recall@3": val_metrics["recall@3"],
                "classes": train_dataset.classes,
                "model_version": args.model_version,
            }, output_dir / "best_model.pth")
            print(f"  → Saved best model (R@1: {best_recall:.2%})")

    with open(output_dir / "training_log.json", "w") as f:
        json.dump(training_log, f, indent=2)

    print(f"\nTraining complete. Best Recall@1: {best_recall:.2%}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train Eurio coin model")
    parser.add_argument("--mode", type=str, default="classify", choices=["classify", "embed", "arcface"])
    parser.add_argument("--dataset", type=str, required=True, help="Train dataset directory")
    parser.add_argument("--val-dataset", type=str, required=True, help="Validation dataset directory")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--m-per-class", type=int, default=8, help="Samples per class per batch (embed mode)")
    parser.add_argument("--margin", type=float, default=0.2, help="Triplet loss margin (embed mode)")
    parser.add_argument("--arcface-margin", type=float, default=28.6, help="ArcFace angular margin in degrees")
    parser.add_argument("--arcface-scale", type=float, default=30.0, help="ArcFace scale factor")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--embedding-dim", type=int, default=256, help="Embedding dim (embed mode)")
    parser.add_argument("--freeze-epochs", type=int, default=5, help="Epochs to freeze backbone")
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--num-workers", type=int, default=-1, help="DataLoader workers (-1=auto: 4 on CUDA, 0 on CPU/MPS)")
    parser.add_argument("--output", type=str, default="./checkpoints/")
    parser.add_argument("--model-version", type=str, default="", help="Version label stored in the checkpoint for downstream tracking.")
    args = parser.parse_args()

    if args.mode == "classify":
        train_classifier(args)
    elif args.mode == "arcface":
        train_arcface(args)
    else:
        train_embedder(args)


if __name__ == "__main__":
    main()
