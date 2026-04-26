"""Export the trained coin model from PyTorch to TFLite via litert_torch."""

import argparse
import json
from pathlib import Path

import torch

from training.train_embedder import CoinClassifier, CoinEmbedder


def export(args):
    checkpoint = torch.load(args.model, map_location="cpu", weights_only=False)
    mode = checkpoint.get("mode", "embed")
    print(f"Mode: {mode}")

    if mode == "classify":
        model = CoinClassifier(num_classes=checkpoint["num_classes"])
        print(f"Classes: {checkpoint['classes']}")
    else:
        model = CoinEmbedder(embedding_dim=checkpoint["embedding_dim"])

    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    print(f"Loaded model from epoch {checkpoint['epoch']}")

    import litert_torch

    sample_input = (torch.randn(1, 3, 224, 224),)
    edge_model = litert_torch.convert(model, sample_input)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / args.filename

    edge_model.export(str(output_path))

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Exported: {output_path} ({size_mb:.1f} MB)")

    # Also save a metadata file so Android knows what model type this is
    meta = {
        "mode": mode,
        "classes": checkpoint.get("classes", []),
        "num_classes": checkpoint.get("num_classes"),
        "embedding_dim": checkpoint.get("embedding_dim"),
    }
    meta_path = output_dir / "model_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {meta_path}")


def main():
    parser = argparse.ArgumentParser(description="Export coin model to TFLite")
    parser.add_argument("--model", type=str, default="./checkpoints/best_model.pth")
    parser.add_argument("--output-dir", type=str, default="./output")
    parser.add_argument("--filename", type=str, default="eurio_embedder_v1.tflite")
    args = parser.parse_args()
    export(args)


if __name__ == "__main__":
    main()
