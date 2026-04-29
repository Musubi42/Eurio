"""
Validate the Phase 4 SnapNormalizer.kt port against ml/scan/normalize_snap.py.

For every device snap pulled into ``<pull_dir>/eurio_debug/eval_real/<class>/``:
1. Run the Python pipeline on ``<step>_raw.jpg`` to produce the reference 224×224.
2. Read the Kotlin pipeline's output written to ``<step>_crop.jpg`` (same algorithm,
   bit-for-bit port).
3. Read the detection metadata Kotlin wrote into ``<step>.json``
   (``normalize`` block: cx, cy, r, method).
4. Compare:
   - **Circle agreement**: |Δcx|, |Δcy|, |Δr| in pixels — divergence here means
     Hough produced a different selection on one side, almost always a sign of
     param drift (someone changed thresholds without updating both ports).
   - **Pixel agreement**: MSE and PSNR between the two 224×224 outputs. JPEG
     re-compression introduces ~quantization noise on both sides, so even a
     mathematically identical pipeline will not be byte-equal — the relevant
     bar is "indistinguishable to the model" (PSNR ≳ 30 dB).

Optional ``--write-diff`` writes a side-by-side ``<step>_diff.jpg`` (Python |
Kotlin | amplified abs-diff) for visual inspection.

Pass criteria (per snap):
- Either both sides reported "no circle" (shared failure — ok),
- OR both sides produced a crop with ``|Δcx|,|Δcy| ≤ 2`` AND ``|Δr| ≤ 2`` AND
  ``PSNR ≥ 30 dB``.

Usage:
    python -m scan.diff_kotlin_python <pull_dir>
    python -m scan.diff_kotlin_python <pull_dir>/eurio_debug/eval_real
    python -m scan.diff_kotlin_python <pull_dir> --write-diff
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .normalize_snap import normalize_device_path


CENTER_TOL_PX = 2          # |Δcx|, |Δcy| ≤ 2 px
RADIUS_TOL_PX = 2          # |Δr| ≤ 2 px
PSNR_PASS_DB = 30.0        # PSNR ≥ 30 dB


@dataclass
class SnapDiff:
    cls: str
    step: str
    py_status: str             # "ok" | "fail"
    kt_status: str             # "ok" | "fail" | "missing"
    dcx: int | None = None
    dcy: int | None = None
    dr: int | None = None
    mse: float | None = None
    psnr: float | None = None
    verdict: str = "?"         # "OK" | "MISS" | "FAIL_BOTH" | "MISMATCH" | "NO_KT"
    reason: str = ""


def _resolve_eval_real(pull_dir: Path) -> Path:
    """Same flexibility as sync_eval_real.py: accept several plausible roots."""
    for candidate in (
        pull_dir / "eurio_debug" / "eval_real",
        pull_dir / "eval_real",
        pull_dir,
    ):
        if candidate.is_dir() and any(candidate.glob("*/*_raw.jpg")):
            return candidate
    raise SystemExit(
        f"Could not locate eval_real/ under {pull_dir} "
        "(expected <pull>/eurio_debug/eval_real/<class>/<step>_raw.jpg)"
    )


def _read_kotlin_meta(meta_path: Path) -> dict | None:
    """Return the ``normalize`` sub-dict from <step>.json, or None if absent.

    Old captures (pre-Phase-4) wrote no normalize block — those snaps cannot
    be diffed and are reported as "no_kt_meta".
    """
    if not meta_path.exists():
        return None
    try:
        payload = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        return None
    return payload.get("normalize")


def _psnr(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """MSE in the 0..255 byte range; PSNR in dB. Identical inputs return (0, inf)."""
    diff = a.astype(np.float64) - b.astype(np.float64)
    mse = float((diff * diff).mean())
    if mse <= 1e-9:
        return 0.0, math.inf
    psnr = 10.0 * math.log10(255.0 * 255.0 / mse)
    return mse, psnr


def _amplified_diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Visual diff: |a - b| × 8, clamped to 0..255 — boosts signal so JPEG
    quantization noise becomes visible at all in the side-by-side output."""
    diff = cv2.absdiff(a, b).astype(np.int32) * 8
    return np.clip(diff, 0, 255).astype(np.uint8)


def _diff_one(
    raw_path: Path,
    crop_path: Path,
    meta_path: Path,
    *,
    write_diff: bool,
) -> SnapDiff:
    cls = raw_path.parent.name
    step = raw_path.stem.removesuffix("_raw")
    out = SnapDiff(cls=cls, step=step, py_status="?", kt_status="?")

    # Python side: re-run the canonical normalizer on the raw frame.
    py_result = normalize_device_path(raw_path)
    out.py_status = "ok" if py_result.image is not None else "fail"

    # Kotlin side: meta.json carries the normalize block produced on device.
    kt_meta = _read_kotlin_meta(meta_path)
    if kt_meta is None:
        out.kt_status = "missing"
    else:
        kt_method = kt_meta.get("method", "?")
        out.kt_status = "fail" if kt_method == "failed" else "ok"

    # Both failed normalisation → consistent (e.g., bad framing on both sides).
    if out.py_status == "fail" and out.kt_status == "fail":
        out.verdict = "FAIL_BOTH"
        out.reason = f"py={py_result.debug.get('error','?')} kt={kt_meta and kt_meta.get('error','?')}"
        return out

    # One side succeeded and the other didn't — divergence in detection.
    if out.py_status == "fail" or out.kt_status in ("fail", "missing"):
        out.verdict = "MISMATCH"
        if out.kt_status == "missing":
            out.reason = "no Kotlin meta (pre-Phase-4 capture?)"
        elif out.py_status == "fail" and out.kt_status == "ok":
            out.reason = "Python failed but Kotlin succeeded"
        else:
            out.reason = "Kotlin failed but Python succeeded"
        return out

    # Both produced a crop — compare circle params and pixel content.
    out.dcx = int(py_result.cx) - int(kt_meta["cx"])
    out.dcy = int(py_result.cy) - int(kt_meta["cy"])
    out.dr = int(py_result.r) - int(kt_meta["r"])

    if not crop_path.exists():
        out.verdict = "NO_KT"
        out.reason = f"meta says ok but {crop_path.name} is missing on disk"
        return out

    kt_img = cv2.imread(str(crop_path), cv2.IMREAD_COLOR)
    py_img = py_result.image
    if kt_img is None or py_img is None:
        out.verdict = "NO_KT"
        out.reason = "could not decode one of the crops"
        return out

    if kt_img.shape != py_img.shape:
        # If the shapes don't match, force-resize the Kotlin one so the diff
        # remains computable. This is unexpected (both sides target 224×224)
        # and almost certainly indicates a port bug — flagged in the reason.
        kt_img = cv2.resize(kt_img, (py_img.shape[1], py_img.shape[0]),
                            interpolation=cv2.INTER_AREA)
        out.reason += f"shape_mismatch py={py_img.shape} kt={kt_img.shape}; "

    out.mse, out.psnr = _psnr(py_img, kt_img)

    if write_diff:
        sep = np.full((py_img.shape[0], 4, 3), 200, dtype=np.uint8)
        canvas = np.hstack([py_img, sep, kt_img, sep, _amplified_diff(py_img, kt_img)])
        cv2.imwrite(str(raw_path.parent / f"{step}_diff.jpg"), canvas,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])

    centers_ok = (
        abs(out.dcx or 0) <= CENTER_TOL_PX
        and abs(out.dcy or 0) <= CENTER_TOL_PX
        and abs(out.dr or 0) <= RADIUS_TOL_PX
    )
    psnr_ok = (out.psnr is not None and (math.isinf(out.psnr) or out.psnr >= PSNR_PASS_DB))

    if centers_ok and psnr_ok:
        out.verdict = "OK"
    else:
        out.verdict = "MISS"
        bad: list[str] = []
        if not centers_ok:
            bad.append(f"Δ=({out.dcx},{out.dcy},{out.dr})")
        if not psnr_ok:
            bad.append(f"psnr={out.psnr:.1f}dB<{PSNR_PASS_DB}")
        out.reason = (out.reason + " ".join(bad)).strip()

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pull_dir", type=Path,
                    help="Path to debug pull (e.g. debug_pull/<ts>/) or eval_real/")
    ap.add_argument("--write-diff", action="store_true",
                    help="Write <step>_diff.jpg (py | kt | abs-diff×8) per snap")
    args = ap.parse_args()

    src_root = _resolve_eval_real(args.pull_dir)
    print(f"Source: {src_root}")
    if args.write_diff:
        print("Writing side-by-side diffs (py | kt | abs-diff×8)")

    snaps = sorted(src_root.glob("*/*_raw.jpg"))
    if not snaps:
        print(f"  no *_raw.jpg under {src_root}", file=sys.stderr)
        return 1

    print(f"\nDiffing {len(snaps)} snap(s)\n")
    header = (
        f"{'class':<55} {'step':<18} "
        f"{'py':<5} {'kt':<8} "
        f"{'Δcx':>5} {'Δcy':>5} {'Δr':>4} "
        f"{'mse':>9} {'psnr':>9} "
        f"{'verdict':<10} reason"
    )
    print(header)
    print("-" * len(header))

    rows: list[SnapDiff] = []
    for raw in snaps:
        step = raw.stem.removesuffix("_raw")
        crop = raw.parent / f"{step}_crop.jpg"
        meta = raw.parent / f"{step}.json"
        d = _diff_one(raw, crop, meta, write_diff=args.write_diff)
        rows.append(d)
        psnr_str = "inf" if d.psnr is not None and math.isinf(d.psnr) else (
            f"{d.psnr:.2f}" if d.psnr is not None else "—"
        )
        mse_str = f"{d.mse:.2f}" if d.mse is not None else "—"
        dcx = f"{d.dcx:+d}" if d.dcx is not None else "—"
        dcy = f"{d.dcy:+d}" if d.dcy is not None else "—"
        dr = f"{d.dr:+d}" if d.dr is not None else "—"
        print(
            f"{d.cls:<55} {d.step:<18} "
            f"{d.py_status:<5} {d.kt_status:<8} "
            f"{dcx:>5} {dcy:>5} {dr:>4} "
            f"{mse_str:>9} {psnr_str:>9} "
            f"{d.verdict:<10} {d.reason}"
        )

    print("-" * len(header))
    by_verdict: dict[str, int] = {}
    for r in rows:
        by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1

    n = len(rows)
    n_ok = by_verdict.get("OK", 0) + by_verdict.get("FAIL_BOTH", 0)
    print(f"\nTotal: {n_ok}/{n} agree "
          f"({(n_ok / max(n, 1)) * 100:.1f}%)")
    for v in ("OK", "FAIL_BOTH", "MISS", "MISMATCH", "NO_KT"):
        if v in by_verdict:
            print(f"  {v:<10} {by_verdict[v]}")

    return 0 if n_ok == n else 2


if __name__ == "__main__":
    raise SystemExit(main())
