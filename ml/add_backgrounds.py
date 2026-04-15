"""Download a sample of COCO val2017 images as background negatives.

COCO val2017 contains no "coin" category, and includes many round-but-not-coin
objects (plates, clocks, frisbees). Training on them with empty labels teaches
the detector to suppress false positives on those shapes.

Output: ml/datasets/coin_detect_v2/train/{images,labels}/bg_<name>.jpg|txt
"""

from __future__ import annotations

import hashlib
import random
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "datasets" / "coin_detect_v2"
CACHE = Path(__file__).resolve().parent / ".dataset_cache"
COCO_URL = "http://images.cocodataset.org/zips/val2017.zip"
COCO_ZIP = CACHE / "val2017.zip"
COCO_DIR = CACHE / "val2017"
N_BACKGROUNDS = 200
SEED = 42


def download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        print(f"  [cache] {dst.name} already present ({dst.stat().st_size / 1e6:.1f} MB)")
        return
    print(f"  downloading {url} → {dst} (~1 GB, this takes a while)")

    def _hook(block_num: int, block_size: int, total_size: int) -> None:
        done = block_num * block_size
        if total_size > 0:
            pct = min(100, done * 100 // total_size)
            sys.stdout.write(f"\r    {pct:3d}% ({done / 1e6:6.1f} / {total_size / 1e6:6.1f} MB)")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dst, reporthook=_hook)
    sys.stdout.write("\n")


def extract(zip_path: Path, dst_dir: Path) -> None:
    if dst_dir.exists() and any(dst_dir.iterdir()):
        print(f"  [cache] already extracted at {dst_dir}")
        return
    print(f"  extracting {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dst_dir.parent)


def main() -> None:
    random.seed(SEED)
    images_out = ROOT / "train" / "images"
    labels_out = ROOT / "train" / "labels"
    assert images_out.is_dir(), "run merge_coin_datasets.py first"

    download(COCO_URL, COCO_ZIP)
    extract(COCO_ZIP, COCO_DIR)

    source_imgs = sorted(COCO_DIR.glob("*.jpg"))
    print(f"  COCO val2017: {len(source_imgs)} images available")
    assert len(source_imgs) >= N_BACKGROUNDS, "not enough COCO images"

    picked = random.sample(source_imgs, N_BACKGROUNDS)
    for src in picked:
        dst_img = images_out / f"bg_{src.name}"
        dst_lbl = labels_out / f"bg_{src.stem}.txt"
        shutil.copy2(src, dst_img)
        dst_lbl.write_text("")  # empty label = negative sample

    print(f"Added {N_BACKGROUNDS} background images to train split.")


if __name__ == "__main__":
    main()
