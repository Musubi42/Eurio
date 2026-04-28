"""
Per-snap inference report on the device golden set.

Loads the best ArcFace checkpoint, embeds every image under
``ml/datasets/eval_real_norm/<class>/<step>.jpg``, computes cosine similarity
against each centroid, and prints one row per snap with predicted top-1, the
cosine to its true class centroid, and the margin against the runner-up.

Centroid source — defaults to the deployed ``output/embeddings_v1.json``
(what compute_embeddings produced and what gets shipped to Android), so the
metric this script reports is exactly what the device will see. Use
``--from-checkpoint-W`` to read the raw ArcFace W prototypes from the
checkpoint instead — useful for comparing the deployed centroids against
the loss's learned anchors when diagnosing W-misalignment.

Usage:
    python -m scan.eval_real_snaps
    python -m scan.eval_real_snaps --from-checkpoint-W
    python -m scan.eval_real_snaps --model checkpoints/best_model.pth \\
        --eval-dir datasets/eval_real_norm
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image

from training.train_embedder import CoinEmbedder, get_val_transforms


ML_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=ML_DIR / "checkpoints" / "best_model.pth")
    ap.add_argument("--eval-dir", type=Path, default=ML_DIR / "datasets" / "eval_real_norm")
    ap.add_argument(
        "--centroids", type=Path,
        default=ML_DIR / "output" / "embeddings_v1.json",
        help="Path to the deployed centroids JSON (default: ml/output/embeddings_v1.json).",
    )
    ap.add_argument(
        "--from-checkpoint-W", action="store_true",
        help="Use ArcFace W from the checkpoint instead of the deployed JSON. "
             "Reproduces the legacy behavior — useful to compare deployed vs W.",
    )
    args = ap.parse_args()

    device = torch.device("cpu")
    ckpt = torch.load(args.model, map_location=device, weights_only=False)
    embedding_dim = ckpt["embedding_dim"]

    # Build (classes, centroids) from either the deployed JSON or W.
    if args.from_checkpoint_W or not args.centroids.exists():
        if not args.from_checkpoint_W:
            print(f"Note: {args.centroids} not found, falling back to checkpoint W")
        classes = list(ckpt["classes"])
        arcface_W = ckpt["arcface_weights"]
        if isinstance(arcface_W, list):
            arcface_W = torch.tensor(arcface_W)
        # pytorch_metric_learning W is [embedding_size, num_classes] —
        # transpose so each row is one class prototype.
        W = arcface_W.t() if arcface_W.shape[0] == embedding_dim else arcface_W
        centroids = F.normalize(W, p=2, dim=1).to(device)
        centroid_src = "checkpoint ArcFace W"
    else:
        with open(args.centroids) as f:
            payload = json.load(f)
        coins = payload["coins"]                                  # class_id → {embedding, …}
        classes = sorted(coins.keys())
        centroids = torch.tensor(
            [coins[c]["embedding"] for c in classes],
            dtype=torch.float32,
        )
        centroids = F.normalize(centroids, p=2, dim=1).to(device)
        centroid_src = f"deployed ({args.centroids.relative_to(ML_DIR)})"

    model = CoinEmbedder(embedding_dim=embedding_dim).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    transform = get_val_transforms()

    print(f"Model:     epoch {ckpt['epoch']}, dim={embedding_dim}, "
          f"reported R@1 (val)={ckpt.get('recall@1', 0):.2%}")
    print(f"Centroids: {centroid_src}")
    print(f"Eval:      {args.eval_dir}\n")

    snaps = sorted(args.eval_dir.glob("*/*.jpg"))
    if not snaps:
        print(f"no snaps under {args.eval_dir}")
        return 1

    header = f"{'class':<55} {'step':<18} {'pred':<55} {'cos_true':>9} {'cos_top1':>9} {'margin':>8} {'verdict':>8}"
    print(header)
    print("-" * len(header))

    n_total = 0
    n_ok = 0
    misses: list[str] = []

    with torch.no_grad():
        for snap in snaps:
            true_cls = snap.parent.name
            step_id = snap.stem
            if true_cls not in classes:
                continue
            true_idx = classes.index(true_cls)

            img = Image.open(snap).convert("RGB")
            tensor = transform(img).unsqueeze(0).to(device)
            emb = F.normalize(model(tensor), p=2, dim=1)[0]
            sims = (emb @ centroids.t()).cpu()  # [num_classes]

            top_idx = int(torch.argmax(sims).item())
            top2 = torch.topk(sims, k=2).values
            margin = float((top2[0] - top2[1]).item())
            cos_true = float(sims[true_idx].item())
            cos_top1 = float(top2[0].item())
            ok = top_idx == true_idx
            verdict = "OK" if ok else "MISS"
            n_total += 1
            n_ok += int(ok)
            if not ok:
                misses.append(f"{true_cls}/{step_id} → {classes[top_idx]} "
                              f"(cos_true={cos_true:.3f}, cos_pred={cos_top1:.3f})")

            print(f"{true_cls:<55} {step_id:<18} {classes[top_idx]:<55} "
                  f"{cos_true:>9.3f} {cos_top1:>9.3f} {margin:>8.3f} {verdict:>8}")

    print("-" * len(header))
    pct = n_ok / max(n_total, 1) * 100
    print(f"\nTotal: {n_ok}/{n_total} correct ({pct:.2f}%)")
    if misses:
        print("\nMisclassified:")
        for m in misses:
            print(f"  ✗ {m}")
    return 0 if n_ok == n_total else 2


if __name__ == "__main__":
    raise SystemExit(main())
