"""
Run a normalizer over a Phase 0 eval_real/ directory. For each input writes
`<stem>_norm.jpg` (and `<stem>_debug.jpg` with --debug) next to the source so
visual inspection is one-glance.

By default uses `normalize_device` (mirrors the Android live pipeline), which
is the relevant view for eval_real captures. Pass `--algo studio` to preview
the training-side `normalize_studio` output on the same input — useful to
visually compare the two on a given source.

Usage:
    python -m scan.preview_normalized <path-to-eval_real> \\
        [--source raw|crop] [--debug] [--algo device|studio]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from .normalize_snap import draw_debug, normalize_device_path, normalize_studio_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_dir", type=Path,
                    help="Path to eval_real/ pulled from Android capture mode")
    ap.add_argument("--source", choices=["raw", "crop"], default="raw",
                    help="Operate on raw camera frame (default) or current masked crop")
    ap.add_argument("--debug", action="store_true",
                    help="Also write <stem>_debug.jpg with the detected circle overlaid")
    ap.add_argument("--algo", choices=["device", "studio"], default="device",
                    help="Which normalizer to run (default: device, matching the Android pipeline)")
    args = ap.parse_args()
    normalize_fn = normalize_device_path if args.algo == "device" else normalize_studio_path

    if not args.eval_dir.exists():
        print(f"not found: {args.eval_dir}", file=sys.stderr)
        return 1

    suffix = "_raw.jpg" if args.source == "raw" else "_crop.jpg"
    inputs = sorted(args.eval_dir.glob(f"*/*{suffix}"))
    if not inputs:
        print(f"no *{suffix} found under {args.eval_dir}", file=sys.stderr)
        return 1

    print(f"normalizing {len(inputs)} {args.source} images from {args.eval_dir}\n")

    by_step: dict[str, list[bool]] = {}
    failures: list[tuple[Path, dict]] = []

    for inp in inputs:
        result = normalize_fn(inp)
        rel = f"{inp.parent.name}/{inp.stem}"
        step_id = inp.stem.replace(suffix.replace(".jpg", ""), "")

        if result.image is None:
            failures.append((inp, result.debug))
            by_step.setdefault(step_id, []).append(False)
            print(f"  ✗ {rel}  {result.debug}")
            continue

        out_path = inp.parent / inp.name.replace(suffix, "_norm.jpg")
        cv2.imwrite(str(out_path), result.image)
        by_step.setdefault(step_id, []).append(True)
        print(f"  ✓ {rel}  r={result.r}px crop_side={result.debug['crop_side']}px")

        if args.debug:
            bgr = cv2.imread(str(inp), cv2.IMREAD_COLOR)
            dbg = draw_debug(bgr, result)
            dbg_path = inp.parent / inp.name.replace(suffix, "_debug.jpg")
            cv2.imwrite(str(dbg_path), dbg)

    success = sum(1 for _, dbg in failures if False) + (len(inputs) - len(failures))
    print(f"\nsuccess: {success}/{len(inputs)}")

    if by_step:
        print("\nper-step success:")
        for step_id, results in sorted(by_step.items()):
            ok = sum(results)
            n = len(results)
            print(f"  {step_id:20s}  {ok}/{n}")

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
