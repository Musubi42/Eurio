"""
Sync golden-set device snaps from a debug pull into ml/datasets/eval_real_norm/.

Walks ``<debug_pull_dir>/eurio_debug/eval_real/<eurio_id>/<step>_raw.jpg``,
runs ``normalize_device`` on each (mirrors the live Android Hough pipeline),
and writes the normalized 224×224 crop to
``ml/datasets/eval_real_norm/<eurio_id>/<step>.jpg`` (a clean ImageFolder
layout consumable as val_dataset by train_embedder).

Usage:
    python -m scan.sync_eval_real <debug_pull_dir>

After running, prepare_dataset.py auto-detects the eval_real_norm/ tree and
populates each class's val/ split with these normalized device snaps,
replacing the (often empty) studio val split.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2

from .normalize_snap import normalize_device_path


ML_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ML_DIR / "datasets" / "eval_real_norm"


def _resolve_eval_real(pull_dir: Path) -> Path:
    """Accept either a raw pull root, the eurio_debug subfolder, or eval_real itself."""
    for candidate in (
        pull_dir / "eurio_debug" / "eval_real",
        pull_dir / "eval_real",
        pull_dir,
    ):
        if candidate.is_dir() and any(candidate.glob("*/*.jpg")):
            return candidate
    raise SystemExit(
        f"Could not locate eval_real/ under {pull_dir} "
        "(expected <pull>/eurio_debug/eval_real/<class>/<step>_raw.jpg)"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pull_dir", type=Path,
                    help="Path to the debug pull (e.g. debug_pull/<ts>/)")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help=f"Output root (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--clear", action="store_true",
                    help="Wipe the output dir before writing (avoids stale classes)")
    args = ap.parse_args()

    src_root = _resolve_eval_real(args.pull_dir)
    print(f"Source: {src_root}")
    print(f"Output: {args.output}")

    if args.clear and args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(src_root.glob("*/*_raw.jpg"))
    if not raw_files:
        print(f"  no *_raw.jpg under {src_root}", file=sys.stderr)
        return 1

    by_class: dict[str, list[bool]] = {}
    failures: list[Path] = []

    for raw in raw_files:
        eurio_id = raw.parent.name
        step_id = raw.stem.removesuffix("_raw")
        result = normalize_device_path(raw)
        ok = result.image is not None
        by_class.setdefault(eurio_id, []).append(ok)
        if not ok:
            failures.append(raw)
            continue
        out_dir = args.output / eurio_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{step_id}.jpg"
        cv2.imwrite(str(out_path), result.image, [cv2.IMWRITE_JPEG_QUALITY, 95])

    print()
    for cls, results in sorted(by_class.items()):
        ok = sum(results)
        n = len(results)
        print(f"  {cls:55s}  {ok}/{n} normalized")

    total_ok = sum(sum(v) for v in by_class.values())
    total = sum(len(v) for v in by_class.values())
    print(f"\nTotal: {total_ok}/{total} → {args.output}")
    if failures:
        print(f"Failures ({len(failures)}):")
        for f in failures:
            print(f"  ✗ {f}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
