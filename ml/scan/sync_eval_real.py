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
    python -m scan.sync_eval_real <debug_pull_dir> --also-write-captures

When ``--also-write-captures`` is set, every successfully normalized image is
*additionally* copied into ``ml/datasets/<numista_id>/captures/<step>.jpg``
(canonical capture store, eurio_id → numista_id via api.coin_lookup). Existing
files in captures/ are not overwritten unless ``--overwrite`` is given.

After running, prepare_dataset.py auto-detects the eval_real_norm/ tree and
populates each class's val/ split with these normalized device snaps,
replacing the (often empty) studio val split.

The :func:`sync` function is also called directly by the FastAPI endpoint
``POST /lab/cohorts/{id}/captures/sync`` and returns a structured report.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
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
    raise FileNotFoundError(
        f"Could not locate eval_real/ under {pull_dir} "
        "(expected <pull>/eurio_debug/eval_real/<class>/<step>_raw.jpg)"
    )


@dataclass
class SyncReport:
    pull_dir: str
    output_dir: str
    total_files: int = 0
    normalized: int = 0
    failures: list[str] = field(default_factory=list)
    per_class: dict[str, dict] = field(default_factory=dict)
    captures_copied: int = 0
    captures_skipped_existing: int = 0
    captures_unmapped_eurio_ids: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "pull_dir": self.pull_dir,
            "output_dir": self.output_dir,
            "total_files": self.total_files,
            "normalized": self.normalized,
            "failures": self.failures,
            "per_class": self.per_class,
            "captures_copied": self.captures_copied,
            "captures_skipped_existing": self.captures_skipped_existing,
            "captures_unmapped_eurio_ids": self.captures_unmapped_eurio_ids,
            "duration_s": round(self.duration_s, 2),
        }


def sync(
    pull_dir: Path,
    *,
    output: Path = DEFAULT_OUTPUT,
    clear: bool = False,
    also_write_captures: bool = False,
    overwrite: bool = False,
) -> SyncReport:
    """Programmatic entry point. Mirrors the CLI flags."""
    started = time.time()
    src_root = _resolve_eval_real(pull_dir)
    if clear and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(src_root.glob("*/*_raw.jpg"))
    report = SyncReport(pull_dir=str(pull_dir), output_dir=str(output))
    report.total_files = len(raw_files)

    if also_write_captures:
        # Lazy import — keep the script usable without FastAPI deps.
        from api import coin_lookup  # noqa: WPS433
    else:
        coin_lookup = None  # type: ignore[assignment]

    by_class: dict[str, list[bool]] = {}
    for raw in raw_files:
        eurio_id = raw.parent.name
        step_id = raw.stem.removesuffix("_raw")
        result = normalize_device_path(raw)
        ok = result.image is not None
        by_class.setdefault(eurio_id, []).append(ok)
        if not ok:
            report.failures.append(str(raw))
            continue
        out_dir = output / eurio_id
        out_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(
            str(out_dir / f"{step_id}.jpg"),
            result.image,
            [cv2.IMWRITE_JPEG_QUALITY, 95],
        )
        report.normalized += 1

        if also_write_captures and coin_lookup is not None:
            nid = coin_lookup.numista_id_for(eurio_id)
            if nid is None:
                if eurio_id not in report.captures_unmapped_eurio_ids:
                    report.captures_unmapped_eurio_ids.append(eurio_id)
            else:
                cap_dir = CAPTURES_BASE / str(nid) / "captures"
                cap_dir.mkdir(parents=True, exist_ok=True)
                cap_path = cap_dir / f"{step_id}.jpg"
                if cap_path.exists() and not overwrite:
                    report.captures_skipped_existing += 1
                else:
                    cv2.imwrite(
                        str(cap_path),
                        result.image,
                        [cv2.IMWRITE_JPEG_QUALITY, 95],
                    )
                    report.captures_copied += 1

    for cls, results in sorted(by_class.items()):
        report.per_class[cls] = {"normalized": sum(results), "total": len(results)}

    report.duration_s = time.time() - started
    return report


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
    ap.add_argument("--also-write-captures", action="store_true",
                    help="Also copy each normalized image to ml/datasets/<numista_id>/captures/")
    ap.add_argument("--overwrite", action="store_true",
                    help="With --also-write-captures, overwrite existing captures/<step>.jpg")
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
    return 0 if not report.failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
