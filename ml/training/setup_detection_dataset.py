"""Download and prepare a coin detection dataset for YOLOv8-nano training.

Downloads a pre-annotated coin detection dataset from Roboflow,
collapses all classes to a single 'coin' class, and adds negative
images (no coins).

Usage:
    .venv/bin/python setup_detection_dataset.py
    .venv/bin/python setup_detection_dataset.py --add-negatives 30
"""

import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image


DETECTION_DIR = Path(__file__).parent.parent / "datasets" / "detection"


def load_env() -> dict[str, str]:
    env = {}
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def download_roboflow_dataset(target_dir: Path) -> Path:
    """Download coin detection dataset from Roboflow in YOLOv8 format.

    Requires ROBOFLOW_API_KEY in .env (free account at app.roboflow.com).
    """
    from roboflow import Roboflow

    env = load_env()
    api_key = env.get("ROBOFLOW_API_KEY", "")

    if not api_key:
        print("ERROR: ROBOFLOW_API_KEY not found in .env")
        print("1. Create free account at https://app.roboflow.com")
        print("2. Copy API key from Settings > API Key")
        print("3. Add to .env: ROBOFLOW_API_KEY=your_key_here")
        raise SystemExit(1)

    print("Downloading coin detection dataset from Roboflow...\n")

    rf = Roboflow(api_key=api_key)

    # Try primary dataset, fall back to alternatives
    datasets_to_try = [
        ("aistudio-bkdjj", "coin-detection-oiawu", 1),
        ("yolocoin", "coin-gva2j", 1),
        ("roboflow-100", "coins-1apki", 1),
    ]

    for workspace, project_name, version_num in datasets_to_try:
        try:
            print(f"  Trying {workspace}/{project_name}...")
            project = rf.workspace(workspace).project(project_name)
            version = project.version(version_num)
            dataset = version.download("yolov8", location=str(target_dir / "roboflow_raw"))
            print(f"  Downloaded from {workspace}/{project_name}\n")
            return Path(dataset.location)
        except Exception as e:
            print(f"  Failed: {e}")
            continue

    print("ERROR: Could not download any coin detection dataset.")
    raise SystemExit(1)


def collapse_to_single_class(dataset_dir: Path, output_dir: Path) -> dict:
    """Collapse multi-class YOLO labels to single class 'coin' (class 0).

    Returns stats about the conversion.
    """
    stats = {"images": 0, "labels_modified": 0}

    for split in ["train", "val", "test"]:
        src_images = dataset_dir / split / "images"
        src_labels = dataset_dir / split / "labels"

        if not src_images.exists():
            continue

        dst_images = output_dir / split / "images"
        dst_labels = output_dir / split / "labels"
        dst_images.mkdir(parents=True, exist_ok=True)
        dst_labels.mkdir(parents=True, exist_ok=True)

        for img_path in sorted(src_images.glob("*")):
            if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue

            # Copy image
            dst_img = dst_images / img_path.name
            if not dst_img.exists():
                dst_img.write_bytes(img_path.read_bytes())
            stats["images"] += 1

            # Collapse labels: change all class IDs to 0
            label_name = img_path.stem + ".txt"
            src_label = src_labels / label_name
            dst_label = dst_labels / label_name

            if src_label.exists():
                lines = src_label.read_text().strip().splitlines()
                collapsed = []
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        # Replace class ID with 0, keep bbox coordinates
                        parts[0] = "0"
                        collapsed.append(" ".join(parts))
                dst_label.write_text("\n".join(collapsed) + "\n")
                stats["labels_modified"] += 1
            else:
                # No label file = negative image (no coins)
                dst_label.write_text("")

    return stats


def generate_negative_images(output_dir: Path, count: int = 30) -> int:
    """Generate simple negative images (no coins) for training.

    Creates varied background images that look like common surfaces
    where someone might scan a coin.
    """
    neg_train = output_dir / "train" / "images"
    neg_labels = output_dir / "train" / "labels"
    neg_train.mkdir(parents=True, exist_ok=True)
    neg_labels.mkdir(parents=True, exist_ok=True)

    generated = 0
    for i in range(count):
        size = 640
        img = Image.new("RGB", (size, size))
        choice = random.random()

        if choice < 0.25:
            # Wood-like gradient
            arr = np.zeros((size, size, 3), dtype=np.uint8)
            base = np.array([random.randint(140, 200), random.randint(100, 160), random.randint(60, 120)])
            noise = np.random.randint(-20, 20, (size, size, 3), dtype=np.int16)
            arr = np.clip(base + noise, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr)

        elif choice < 0.5:
            # Fabric texture
            arr = np.random.randint(40, 120, (size, size, 3), dtype=np.uint8)
            img = Image.fromarray(arr)
            from PIL import ImageFilter
            img = img.filter(ImageFilter.GaussianBlur(radius=3))

        elif choice < 0.75:
            # Desktop / flat color with noise
            color = [random.randint(150, 240)] * 3
            arr = np.full((size, size, 3), color, dtype=np.uint8)
            noise = np.random.randint(-15, 15, (size, size, 3), dtype=np.int16)
            arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr)

        else:
            # Dark surface
            arr = np.random.randint(10, 60, (size, size, 3), dtype=np.uint8)
            img = Image.fromarray(arr)

        img_path = neg_train / f"negative_{i:04d}.jpg"
        img.save(img_path, "JPEG", quality=85)

        # Empty label file = no objects
        label_path = neg_labels / f"negative_{i:04d}.txt"
        label_path.write_text("")
        generated += 1

    return generated


def ensure_val_split(output_dir: Path, val_ratio: float = 0.15, seed: int = 42) -> None:
    """If there's no val split, create one from train images."""
    val_images = output_dir / "val" / "images"
    train_images = output_dir / "train" / "images"
    train_labels = output_dir / "train" / "labels"

    if val_images.exists() and len(list(val_images.glob("*"))) > 0:
        return  # Val split already exists

    print("  No val split found — creating from train (15%)...")
    val_images.mkdir(parents=True, exist_ok=True)
    val_labels = output_dir / "val" / "labels"
    val_labels.mkdir(parents=True, exist_ok=True)

    all_images = sorted([
        f for f in train_images.glob("*")
        if f.suffix.lower() in (".jpg", ".jpeg", ".png")
        and not f.stem.startswith("negative_")  # Keep negatives in train
    ])

    random.seed(seed)
    random.shuffle(all_images)
    n_val = max(1, int(len(all_images) * val_ratio))
    val_images_list = all_images[:n_val]

    for img_path in val_images_list:
        # Move image
        (val_images / img_path.name).write_bytes(img_path.read_bytes())
        img_path.unlink()

        # Move label
        label_name = img_path.stem + ".txt"
        src_label = train_labels / label_name
        dst_label = val_labels / label_name
        if src_label.exists():
            dst_label.write_bytes(src_label.read_bytes())
            src_label.unlink()

    print(f"  Moved {n_val} images to val split")


def write_data_yaml(output_dir: Path) -> None:
    """Write the data.yaml config for YOLOv8 training."""
    yaml_content = f"""train: {output_dir / 'train' / 'images'}
val: {output_dir / 'val' / 'images'}
test: {output_dir / 'test' / 'images'}

nc: 1
names: ['coin']
"""
    yaml_path = output_dir / "data.yaml"
    yaml_path.write_text(yaml_content)
    print(f"Written: {yaml_path}")


def main():
    parser = argparse.ArgumentParser(description="Setup coin detection dataset")
    parser.add_argument("--add-negatives", type=int, default=30, help="Number of negative images to generate")
    parser.add_argument("--skip-download", action="store_true", help="Skip Roboflow download (use existing)")
    args = parser.parse_args()

    DETECTION_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Download dataset
    if not args.skip_download:
        raw_dir = download_roboflow_dataset(DETECTION_DIR)
    else:
        raw_dir = DETECTION_DIR / "roboflow_raw"
        if not raw_dir.exists():
            print(f"ERROR: {raw_dir} does not exist. Run without --skip-download first.")
            return

    # Step 2: Collapse to single class
    print("\nCollapsing to single class 'coin'...")
    output_dir = DETECTION_DIR / "coin_detect"
    stats = collapse_to_single_class(raw_dir, output_dir)
    print(f"  {stats['images']} images, {stats['labels_modified']} labels collapsed")

    # Step 3: Ensure val split exists
    ensure_val_split(output_dir)

    # Step 4: Add negative images
    print(f"\nGenerating {args.add_negatives} negative images...")
    neg_count = generate_negative_images(output_dir, count=args.add_negatives)
    print(f"  {neg_count} negative images added to train set")

    # Step 5: Write data.yaml
    print()
    write_data_yaml(output_dir)

    # Summary
    print(f"\nDataset ready at: {output_dir}")
    for split in ["train", "val", "test"]:
        split_dir = output_dir / split / "images"
        if split_dir.exists():
            count = len(list(split_dir.glob("*")))
            print(f"  {split}: {count} images")


if __name__ == "__main__":
    main()
