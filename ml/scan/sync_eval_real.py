"""
Sync golden-set device snaps from a debug pull into ml/datasets/eval_real_norm/.

Walks ``<debug_pull_dir>/eurio_debug/eval_real/<eurio_id>/<step>_raw.jpg``,
runs ``normalize_device`` on each (mirrors the live Android Hough pipeline),
and writes the normalized 224×224 crop to
``ml/datasets/eval_real_norm/<class_id>/<step>.jpg``.

The output folder is keyed by **class_id** (= ``design_group_id`` when one
exists, otherwise ``eurio_id``), not by raw ``eurio_id``.  This matches the
layout expected by ``prepare_dataset.py``, which looks up val snaps under
``eval_real_norm/<class_id>/``.

The mapping is read from ``class_manifest.json`` produced by
``prepare_dataset.py``.  If the manifest is absent, output folders fall back
to the raw ``eurio_id`` (backward-compatible for commemoratives, where
class_id == eurio_id anyway).

Usage:
    python -m scan.sync_eval_real <debug_pull_dir>

After running, prepare_dataset.py auto-detects the eval_real_norm/ tree and
populates each class's val/ split with these normalized device snaps,
replacing the (often empty) studio val split.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2

from .normalize_snap import normalize_device_path


ML_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ML_DIR / "datasets" / "eval_real_norm"
DEFAULT_MANIFEST = ML_DIR / "datasets" / "eurio-poc" / "class_manifest.json"


def _load_eurio_to_class(manifest_path: Path) -> dict[str, str]:
    """Build eurio_id → class_id map from class_manifest.json."""
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text())
    mapping: dict[str, str] = {}
    for cls in data.get("classes", []):
        class_id = cls["class_id"]
        for eid in cls.get("eurio_ids", []):
            mapping[eid] = class_id
    return mapping


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
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help=f"class_manifest.json for eurio_id→class_id resolution "
                         f"(default: {DEFAULT_MANIFEST})")
    ap.add_argument("--clear", action="store_true",
                    help="Wipe the output dir before writing (avoids stale classes)")
    args = ap.parse_args()

    eurio_to_class = _load_eurio_to_class(args.manifest)
    if eurio_to_class:
        print(f"Manifest: {args.manifest} ({len(eurio_to_class)} eurio_id mappings)")
    else:
        print(f"Manifest: not found at {args.manifest} — output keyed by eurio_id")

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
        class_id = eurio_to_class.get(eurio_id, eurio_id)
        step_id = raw.stem.removesuffix("_raw")
        result = normalize_device_path(raw)
        ok = result.image is not None
        by_class.setdefault(class_id, []).append(ok)
        if not ok:
            failures.append(raw)
            continue
        out_dir = args.output / class_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{step_id}.jpg"
        cv2.imwrite(str(out_path), result.image, [cv2.IMWRITE_JPEG_QUALITY, 95])

    print()
    for class_id, results in sorted(by_class.items()):
        ok = sum(results)
        n = len(results)
        print(f"  {class_id:55s}  {ok}/{n} normalized")

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
