"""Generate synthetic augmented images from source coin photos.

Takes existing coin photos and generates augmented versions with varied
backgrounds, lighting, perspectives, and rotations.

Usage:
    .venv/bin/python augment_synthetic.py --coin-ids 135 111 159 87 226447
    .venv/bin/python augment_synthetic.py --all --target-per-class 50
"""

import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def create_circular_mask(size: int) -> Image.Image:
    """Create a circular mask for coin cutout."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    margin = int(size * 0.02)
    draw.ellipse([margin, margin, size - margin, size - margin], fill=255)
    # Slight blur for smoother edges
    mask = mask.filter(ImageFilter.GaussianBlur(radius=2))
    return mask


def random_background(size: int) -> Image.Image:
    """Generate a random background image."""
    bg = Image.new("RGB", (size, size))
    choice = random.random()

    if choice < 0.3:
        # Solid color (wood-ish, grey, white, dark)
        colors = [
            (random.randint(140, 200), random.randint(100, 160), random.randint(60, 120)),  # wood
            (random.randint(180, 230), random.randint(180, 230), random.randint(180, 230)),  # grey
            (random.randint(230, 255), random.randint(230, 255), random.randint(230, 255)),  # white
            (random.randint(20, 60), random.randint(20, 60), random.randint(20, 60)),        # dark
            (random.randint(160, 200), random.randint(140, 180), random.randint(120, 160)),  # beige
        ]
        color = random.choice(colors)
        bg = Image.new("RGB", (size, size), color)

    elif choice < 0.6:
        # Gradient
        arr = np.zeros((size, size, 3), dtype=np.uint8)
        c1 = np.array([random.randint(50, 200) for _ in range(3)])
        c2 = np.array([random.randint(50, 200) for _ in range(3)])
        for y in range(size):
            t = y / size
            arr[y, :] = (c1 * (1 - t) + c2 * t).astype(np.uint8)
        bg = Image.fromarray(arr)

    else:
        # Noisy texture
        arr = np.random.randint(100, 200, (size, size, 3), dtype=np.uint8)
        bg = Image.fromarray(arr)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=random.uniform(2, 5)))

    return bg


def augment_single(img: Image.Image, output_size: int = 256) -> Image.Image:
    """Apply random augmentations to a coin image and paste on random background."""
    # Ensure RGB
    img = img.convert("RGB")

    # Random crop to square (center-ish)
    w, h = img.size
    min_dim = min(w, h)
    left = random.randint(0, max(0, w - min_dim))
    top = random.randint(0, max(0, h - min_dim))
    img = img.crop((left, top, left + min_dim, top + min_dim))

    # Resize coin
    coin_scale = random.uniform(0.5, 0.85)
    coin_size = int(output_size * coin_scale)
    img = img.resize((coin_size, coin_size), Image.LANCZOS)

    # Random rotation (coins are rotation-invariant)
    angle = random.uniform(0, 360)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False)

    # Color jitter
    img = ImageEnhance.Brightness(img).enhance(random.uniform(0.7, 1.4))
    img = ImageEnhance.Contrast(img).enhance(random.uniform(0.7, 1.4))
    img = ImageEnhance.Color(img).enhance(random.uniform(0.7, 1.3))

    # Optional blur
    if random.random() < 0.3:
        img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.3, 1.5)))

    # Create circular mask and paste on background
    mask = create_circular_mask(coin_size)
    bg = random_background(output_size)

    # Random position (centered-ish)
    max_offset = (output_size - coin_size) // 2
    offset_x = output_size // 2 - coin_size // 2 + random.randint(-max_offset // 3, max_offset // 3)
    offset_y = output_size // 2 - coin_size // 2 + random.randint(-max_offset // 3, max_offset // 3)
    offset_x = max(0, min(offset_x, output_size - coin_size))
    offset_y = max(0, min(offset_y, output_size - coin_size))

    bg.paste(img, (offset_x, offset_y), mask)

    return bg


def augment_coin(coin_dir: Path, target_count: int = 50, output_size: int = 256) -> int:
    """Generate augmented images for a single coin. Returns count generated."""
    # Find source images (real photos, not previously augmented)
    source_images = sorted([
        f for f in coin_dir.iterdir()
        if f.suffix.lower() in (".jpg", ".jpeg", ".png")
        and not f.stem.startswith("aug_")
        and f.stem not in ("obverse", "reverse")  # Skip Numista studio images for now
    ])

    # Also include obverse.jpg if it exists (Numista studio image)
    obverse = coin_dir / "obverse.jpg"
    if obverse.exists():
        source_images.append(obverse)

    if not source_images:
        print(f"  {coin_dir.name}: no source images found")
        return 0

    # Create augmented directory
    aug_dir = coin_dir / "augmented"
    aug_dir.mkdir(exist_ok=True)

    # Count existing augmented images
    existing = len(list(aug_dir.glob("aug_*.jpg")))
    to_generate = max(0, target_count - existing)

    if to_generate == 0:
        print(f"  {coin_dir.name}: already has {existing} augmented images")
        return 0

    generated = 0
    for i in range(to_generate):
        # Pick a random source image
        src_path = random.choice(source_images)
        src_img = Image.open(src_path)

        aug_img = augment_single(src_img, output_size=output_size)
        aug_path = aug_dir / f"aug_{existing + i + 1:04d}.jpg"
        aug_img.save(aug_path, "JPEG", quality=90)
        generated += 1

    print(f"  {coin_dir.name}: generated {generated} augmented images (from {len(source_images)} sources)")
    return generated


def main():
    parser = argparse.ArgumentParser(description="Generate augmented coin images")
    parser.add_argument("--coin-ids", nargs="+", type=str, help="Numista IDs to augment")
    parser.add_argument("--all", action="store_true", help="Augment all coins in datasets/")
    parser.add_argument("--target-per-class", type=int, default=50, help="Target augmented images per class")
    parser.add_argument("--size", type=int, default=256, help="Output image size")
    args = parser.parse_args()

    if args.coin_ids:
        coin_dirs = [DATASETS_DIR / cid for cid in args.coin_ids]
    elif args.all:
        coin_dirs = sorted([
            d for d in DATASETS_DIR.iterdir()
            if d.is_dir() and d.name not in ("eurio-poc",)
        ])
    else:
        print("Specify --coin-ids or --all")
        return

    total = 0
    for coin_dir in coin_dirs:
        if not coin_dir.exists():
            print(f"  {coin_dir.name}: directory not found, skipping")
            continue
        total += augment_coin(coin_dir, target_count=args.target_per_class, output_size=args.size)

    print(f"\nTotal: {total} augmented images generated")


if __name__ == "__main__":
    main()
