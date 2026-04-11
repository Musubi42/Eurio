"""Train YOLOv8-nano for coin detection (single class: 'coin').

Usage:
    .venv/bin/python train_detector.py
    .venv/bin/python train_detector.py --epochs 200 --device mps
    .venv/bin/python train_detector.py --export-only  # Export existing best model to TFLite
"""

import argparse
from pathlib import Path

from ultralytics import YOLO


DETECTION_DIR = Path(__file__).parent / "datasets" / "detection"
DATA_YAML = DETECTION_DIR / "coin_detect" / "data.yaml"
OUTPUT_DIR = Path(__file__).parent / "output"


def train(args):
    if not DATA_YAML.exists():
        print(f"ERROR: {DATA_YAML} not found.")
        print("Run setup_detection_dataset.py first.")
        return

    print(f"Training YOLOv8-nano coin detector")
    print(f"  Data: {DATA_YAML}")
    print(f"  Device: {args.device}")
    print(f"  Image size: {args.imgsz}")
    print(f"  Epochs: {args.epochs}")
    print()

    # Load pretrained YOLOv8-nano (COCO weights)
    model = YOLO("yolov8n.pt")

    # Train
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        patience=args.patience,
        # Freeze backbone for first N epochs for transfer learning
        freeze=args.freeze,
        # Augmentation (coins are rotation-invariant)
        degrees=15.0,
        translate=0.1,
        scale=0.5,
        flipud=0.5,
        fliplr=0.5,
        # Output
        project=str(OUTPUT_DIR / "detection"),
        name="coin_detector",
        exist_ok=True,
        verbose=True,
    )

    print(f"\nTraining complete!")
    print(f"Best model: {OUTPUT_DIR / 'detection' / 'coin_detector' / 'weights' / 'best.pt'}")

    # Auto-export if requested
    if args.export:
        export_model(args)


def export_model(args):
    """Export trained model to TFLite."""
    best_pt = OUTPUT_DIR / "detection" / "coin_detector" / "weights" / "best.pt"

    if not best_pt.exists():
        print(f"ERROR: {best_pt} not found. Train first.")
        return

    print(f"\nExporting to TFLite...")
    model = YOLO(str(best_pt))
    model.export(
        format="tflite",
        imgsz=args.imgsz,
        # INT8 quantization for mobile
        int8=True,
        data=str(DATA_YAML),
        nms=True,  # Bake NMS into the model
    )

    # Find the exported file
    exported = list(best_pt.parent.glob("*.tflite"))
    if exported:
        dest = OUTPUT_DIR / "coin_detector.tflite"
        exported[0].rename(dest)
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"Exported: {dest} ({size_mb:.1f} MB)")
    else:
        print("WARNING: TFLite file not found after export")


def validate_model(args):
    """Run validation on the trained model."""
    best_pt = OUTPUT_DIR / "detection" / "coin_detector" / "weights" / "best.pt"

    if not best_pt.exists():
        print(f"ERROR: {best_pt} not found. Train first.")
        return

    model = YOLO(str(best_pt))
    results = model.val(data=str(DATA_YAML), imgsz=args.imgsz, device=args.device)

    print(f"\nValidation Results:")
    print(f"  mAP@50:    {results.box.map50:.4f}")
    print(f"  mAP@50-95: {results.box.map:.4f}")
    print(f"  Precision:  {results.box.mp:.4f}")
    print(f"  Recall:     {results.box.mr:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8-nano coin detector")
    parser.add_argument("--epochs", type=int, default=150, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=320, help="Image size (320 for mobile)")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--device", type=str, default="mps", help="Device (mps, cuda, cpu)")
    parser.add_argument("--patience", type=int, default=30, help="Early stopping patience")
    parser.add_argument("--freeze", type=int, default=10, help="Freeze backbone for N epochs")
    parser.add_argument("--export", action="store_true", help="Export to TFLite after training")
    parser.add_argument("--export-only", action="store_true", help="Only export existing model")
    parser.add_argument("--validate", action="store_true", help="Only validate existing model")
    args = parser.parse_args()

    if args.export_only:
        export_model(args)
    elif args.validate:
        validate_model(args)
    else:
        train(args)


if __name__ == "__main__":
    main()
