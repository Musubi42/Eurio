"""Validate that the TFLite model produces the same embeddings as PyTorch."""

import argparse
from pathlib import Path

import numpy as np
import torch
from torchvision.datasets import ImageFolder

from training.train_embedder import CoinClassifier, CoinEmbedder, get_val_transforms


def load_tflite_model(model_path: str):
    """Load a TFLite model and return a runner function."""
    from ai_edge_litert.interpreter import Interpreter

    interpreter = Interpreter(model_path=model_path)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    print(f"TFLite input shape:  {input_details[0]['shape']}")
    print(f"TFLite output shape: {output_details[0]['shape']}")

    def run(input_tensor: np.ndarray) -> np.ndarray:
        interpreter.set_tensor(input_details[0]["index"], input_tensor.astype(np.float32))
        interpreter.invoke()
        return interpreter.get_tensor(output_details[0]["index"])

    return run


def validate(args):
    device = torch.device("cpu")  # Compare on CPU for consistency

    # Load PyTorch model (supports classify, embed, and arcface modes)
    checkpoint = torch.load(args.pytorch_model, map_location=device, weights_only=False)
    mode = checkpoint.get("mode", "embed")
    print(f"Mode: {mode}")

    if mode == "classify":
        pytorch_model = CoinClassifier(num_classes=checkpoint["num_classes"])
    else:
        pytorch_model = CoinEmbedder(embedding_dim=checkpoint.get("embedding_dim", 256))

    pytorch_model.load_state_dict(checkpoint["model_state_dict"])
    pytorch_model.eval()

    # Load TFLite model
    tflite_run = load_tflite_model(args.tflite_model)

    # Load test images
    dataset = ImageFolder(args.test_dataset, transform=get_val_transforms())
    n = min(len(dataset), args.num_images)

    print(f"\nComparing {n} images...")
    print(f"{'Image':<30} {'Cosine Sim':>10} {'Max Diff':>10} {'OK':>4}")
    print("-" * 58)

    all_ok = True
    for i in range(n):
        img_tensor, label = dataset[i]
        img_batch = img_tensor.unsqueeze(0)  # (1, 3, 224, 224)

        # PyTorch
        with torch.no_grad():
            pytorch_emb = pytorch_model(img_batch).numpy()[0]

        # TFLite
        tflite_emb = tflite_run(img_batch.numpy())[0]

        # Compare
        cos_sim = np.dot(pytorch_emb, tflite_emb) / (
            np.linalg.norm(pytorch_emb) * np.linalg.norm(tflite_emb)
        )
        max_diff = np.abs(pytorch_emb - tflite_emb).max()
        ok = cos_sim > args.threshold

        if not ok:
            all_ok = False

        img_name = Path(dataset.samples[i][0]).name
        status = "+" if ok else "FAIL"
        print(f"  {img_name:<28} {cos_sim:>10.6f} {max_diff:>10.6f} {status:>4}")

    print("-" * 58)
    if all_ok:
        print(f"All {n} images pass (cosine similarity > {args.threshold})")
    else:
        print(f"SOME IMAGES FAILED (threshold: {args.threshold})")


def main():
    parser = argparse.ArgumentParser(description="Validate TFLite export")
    parser.add_argument(
        "--pytorch-model", type=str,
        default="./checkpoints/best_model.pth",
    )
    parser.add_argument(
        "--tflite-model", type=str,
        default="./output/eurio_embedder_v1.tflite",
    )
    parser.add_argument(
        "--test-dataset", type=str,
        default="./datasets/eurio-poc/test",
    )
    parser.add_argument("--num-images", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.99)
    args = parser.parse_args()
    validate(args)


if __name__ == "__main__":
    main()
