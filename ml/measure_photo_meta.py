"""Measure each Numista coin photo's center and effective radius in UV space.

For every 2 € coin in `coin_catalog.json` that has both `obverse` and `reverse`
images on disk, run a luminance-threshold bbox detection to find where the coin
sits in the frame. Output a JSON manifest consumed by the proto's coin 3D viewer
to drive its UV mapping (see `docs/coin-3d-viewer/technical-notes.md`).

We never modify the original photos — see decision D8 in
`docs/coin-3d-viewer/decisions.md`.

Usage:
    uv run --with pillow --with numpy python ml/measure_photo_meta.py

Outputs to `docs/design/prototype/data/coin-3d/coins.json` by default.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO_ROOT / "ml" / "datasets" / "coin_catalog.json"
DEFAULT_DATASETS = REPO_ROOT / "ml" / "datasets"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "design" / "prototype" / "data" / "coin-3d" / "coins.json"


def measure_photo(path: Path) -> dict | None:
    """Return {cx_uv, cy_uv, radius_uv, width, height} for a coin photo.

    Threshold the luminance to separate coin (anything above 25/255) from background,
    then compute the bbox. Center of bbox = coin center, half-diagonal-avg = radius.
    Returns None if the image cannot be opened.
    """
    try:
        img = np.array(Image.open(path).convert("RGB"))
    except Exception:
        return None
    H, W, _ = img.shape
    lum = 0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]
    mask = lum > 25
    if not mask.any():
        return None

    # Bbox of the coin pixels.
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    top = int(np.argmax(rows))
    bottom = H - 1 - int(np.argmax(rows[::-1]))
    left = int(np.argmax(cols))
    right = W - 1 - int(np.argmax(cols[::-1]))

    cx_px = (left + right) / 2
    cy_px = (top + bottom) / 2
    rx = (right - left) / 2
    ry = (bottom - top) / 2

    return {
        "cx_uv": round(cx_px / W, 5),
        "cy_uv": round(cy_px / H, 5),
        # Radius normalized by frame width — assumes ~square frames (Numista is).
        "radius_uv": round((rx + ry) / 2 / W, 5),
        "width": W,
        "height": H,
    }


def find_image(coin_dir: Path, side: str) -> Path | None:
    """Find obverse.png / obverse.jpg (or reverse.*) — Numista mixes formats."""
    for ext in ("png", "jpg", "jpeg"):
        candidate = coin_dir / f"{side}.{ext}"
        if candidate.exists():
            return candidate
    return None


def to_proto_path(absolute: Path) -> str:
    """Express an absolute repo path as a URL the proto server can load.

    The proto's serve.sh runs python http.server from REPO_ROOT, so any repo path
    is reachable as `/<relative-from-root>`.
    """
    rel = absolute.relative_to(REPO_ROOT)
    return "/" + str(rel)


def build_manifest(catalog_path: Path, datasets_dir: Path) -> dict:
    catalog = json.loads(catalog_path.read_text())
    coins_in = catalog["coins"]

    coins_out: list[dict] = []
    skipped_no_pair = 0
    skipped_unmeasurable = 0

    # Sort by (country, year, numista_id) for predictable carousel order.
    items = sorted(
        ((nid, c) for nid, c in coins_in.items() if c.get("face_value") == 2.0),
        key=lambda kv: (kv[1].get("country", ""), kv[1].get("year", 0), int(kv[0])),
    )

    for nid, c in items:
        coin_dir = datasets_dir / nid
        obv_path = find_image(coin_dir, "obverse")
        rev_path = find_image(coin_dir, "reverse")
        if not (obv_path and rev_path):
            skipped_no_pair += 1
            continue

        obv_meta = measure_photo(obv_path)
        rev_meta = measure_photo(rev_path)
        if not (obv_meta and rev_meta):
            skipped_unmeasurable += 1
            continue

        coins_out.append({
            "numista_id": nid,
            "country": c.get("country"),
            "year": c.get("year"),
            "name": c.get("name"),
            "obverse": {"path": to_proto_path(obv_path), **obv_meta},
            "reverse": {"path": to_proto_path(rev_path), **rev_meta},
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_catalog": str(catalog_path.relative_to(REPO_ROOT)),
        "stats": {
            "total_2eur_in_catalog": len(items),
            "with_image_pair": len(coins_out),
            "skipped_no_pair": skipped_no_pair,
            "skipped_unmeasurable": skipped_unmeasurable,
        },
        "coins": coins_out,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--datasets-dir", type=Path, default=DEFAULT_DATASETS)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()

    manifest = build_manifest(args.catalog, args.datasets_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    s = manifest["stats"]
    print(f"Wrote {args.output}")
    print(f"  2€ in catalog       : {s['total_2eur_in_catalog']}")
    print(f"  with image pair     : {s['with_image_pair']}")
    print(f"  skipped (no pair)   : {s['skipped_no_pair']}")
    print(f"  skipped (unreadable): {s['skipped_unmeasurable']}")


if __name__ == "__main__":
    main()
