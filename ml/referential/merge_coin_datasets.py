"""Merge euro/ + coin/ Roboflow exports into a flat coin_detect_v2 layout.

Source:
  ml/datasets/coin_detect_v2/euro/{train,valid,test}/{images,labels}   (nc=1)
  ml/datasets/coin_detect_v2/coin/{train,test}/{images,labels}         (nc=14)

Target:
  ml/datasets/coin_detect_v2/{train,val,test}/{images,labels}          (nc=1, class 0)

- Prefixes filenames (`euro_`, `coin_`) to avoid collisions.
- Remaps all classes to 0 (single "coin" class).
- Builds val from: euro/valid + 10% of coin/train (deterministic seed).
- Keeps a `test/` split from euro/test + coin/test for later eval.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "datasets" / "coin_detect_v2"
SEED = 42
COIN_VAL_FRACTION = 0.10
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def remap_label_file(src: Path, dst: Path) -> None:
    """Copy a YOLO label file, forcing class id to 0."""
    lines_out: list[str] = []
    if src.exists():
        for line in src.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                parts[0] = "0"
                lines_out.append(" ".join(parts))
    dst.write_text("\n".join(lines_out) + ("\n" if lines_out else ""))


def copy_pair(img_src: Path, labels_src_dir: Path, img_dst: Path, labels_dst_dir: Path) -> None:
    shutil.copy2(img_src, img_dst)
    label_src = labels_src_dir / f"{img_src.stem}.txt"
    label_dst = labels_dst_dir / f"{img_dst.stem}.txt"
    remap_label_file(label_src, label_dst)


def list_images(images_dir: Path) -> list[Path]:
    return sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMG_EXTS)


def ensure_clean(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)


def main() -> None:
    random.seed(SEED)

    euro = ROOT / "euro"
    coin = ROOT / "coin"
    assert euro.is_dir() and coin.is_dir(), f"missing sources under {ROOT}"

    for split in ("train", "val", "test"):
        ensure_clean(ROOT / split / "images")
        ensure_clean(ROOT / split / "labels")

    counts: dict[str, int] = {"train": 0, "val": 0, "test": 0}

    # --- euro (nc=1) ---
    for src_split, dst_split in (("train", "train"), ("valid", "val"), ("test", "test")):
        imgs_dir = euro / src_split / "images"
        lbls_dir = euro / src_split / "labels"
        if not imgs_dir.is_dir():
            continue
        for img in list_images(imgs_dir):
            dst_img = ROOT / dst_split / "images" / f"euro_{img.name}"
            copy_pair(img, lbls_dir, dst_img, ROOT / dst_split / "labels")
            counts[dst_split] += 1

    # --- coin (nc=14, no valid split) ---
    # test → test
    coin_test_imgs = coin / "test" / "images"
    coin_test_lbls = coin / "test" / "labels"
    if coin_test_imgs.is_dir():
        for img in list_images(coin_test_imgs):
            dst_img = ROOT / "test" / "images" / f"coin_{img.name}"
            copy_pair(img, coin_test_lbls, dst_img, ROOT / "test" / "labels")
            counts["test"] += 1

    # train → 90% train, 10% val (deterministic)
    coin_train_imgs = coin / "train" / "images"
    coin_train_lbls = coin / "train" / "labels"
    train_images = list_images(coin_train_imgs)
    random.shuffle(train_images)
    val_cut = int(len(train_images) * COIN_VAL_FRACTION)
    coin_val_imgs = train_images[:val_cut]
    coin_train_kept = train_images[val_cut:]

    for img in coin_train_kept:
        dst_img = ROOT / "train" / "images" / f"coin_{img.name}"
        copy_pair(img, coin_train_lbls, dst_img, ROOT / "train" / "labels")
        counts["train"] += 1

    for img in coin_val_imgs:
        dst_img = ROOT / "val" / "images" / f"coin_{img.name}"
        copy_pair(img, coin_train_lbls, dst_img, ROOT / "val" / "labels")
        counts["val"] += 1

    print("Merge done.")
    for split in ("train", "val", "test"):
        print(f"  {split}: {counts[split]} images")

    # sanity: verify all labels only contain class 0
    bad = 0
    for txt in (ROOT / "train" / "labels").glob("*.txt"):
        for line in txt.read_text().splitlines():
            parts = line.strip().split()
            if parts and parts[0] != "0":
                bad += 1
                break
    print(f"  class-remap check: {bad} label files with non-zero class (expected 0)")


if __name__ == "__main__":
    main()
