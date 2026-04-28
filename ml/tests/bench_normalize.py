"""
Bench: working-resolution downscale before Hough vs current full-res Hough.

Goal: measure wall-clock + parity of a `normalize()` variant that downscales
the input to a fixed working resolution before Hough circle detection, then
scales (cx, cy, r) back to full-res coordinates and runs the crop / mask /
224 resize on the full-res image. The 224x224 output that feeds ArcFace is
still produced from full-res pixels — only the detection step sees a smaller
image.

Usage (from repo root, inside the venv):
    python -m ml.tests.bench_normalize

No prod code modified. Variants live inside this file.
"""
from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

# Force line-buffered stdout so progress lines are visible in real time when
# the user runs `python -m ml.tests.bench_normalize` in a terminal (default
# Python stdout is block-buffered when not attached to a tty).
sys.stdout.reconfigure(line_buffering=True)


def log(msg: str = "") -> None:
    print(msg, flush=True)

# Reuse prod constants / dataclasses so parity comparisons are 1:1.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan.normalize_snap import (  # noqa: E402
    BG_COLOR,
    COIN_MARGIN,
    OUTPUT_SIZE,
    NormalizationResult,
    normalize as normalize_baseline,
)


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------

# Cascade presets. Each entry: (pass_name, param1, param2, rmin_frac, rmax_frac).
# `prod` mirrors normalize_snap.py exactly (parity reference).
# `tight_radius` shrinks the radius search range — coin fills the frame on both
# studio sources AND camera frames (capture protocol centers + frames the coin),
# so 0.15..0.55 is much wider than physically necessary. Reducing the range cuts
# the Hough voting + radius-refinement work proportionally.
HOUGH_CASCADES = {
    "prod": (
        ("hough_tight",   100, 30, 0.15, 0.55),
        ("hough_relaxed",  60, 22, 0.10, 0.55),
    ),
    "tight_radius": (
        ("hough_tight",   100, 30, 0.35, 0.55),
        ("hough_relaxed",  60, 22, 0.30, 0.55),
    ),
    "alt": (  # HOUGH_GRADIENT_ALT — param2 is perfectness ratio in [0,1]
        ("hough_alt_tight",   300, 0.85, 0.15, 0.55),
        ("hough_alt_relaxed", 300, 0.70, 0.10, 0.55),
    ),
}


def _hough_passes_on_gray(gray: np.ndarray, short: int, img_cx: float, img_cy: float,
                           center_tol_sq: float, passes, mode: int = cv2.HOUGH_GRADIENT):
    """Run a Hough cascade on a grayscale image. Returns (cx, cy, r, method) or None."""
    for pass_name, p1, p2, rmin_frac, rmax_frac in passes:
        circles = cv2.HoughCircles(
            gray, mode, dp=1.0, minDist=short,
            param1=p1, param2=p2,
            minRadius=int(short * rmin_frac),
            maxRadius=int(short * rmax_frac),
        )
        if circles is None or len(circles[0]) == 0:
            continue
        centered = [
            c for c in circles[0]
            if (c[0] - img_cx) ** 2 + (c[1] - img_cy) ** 2 <= center_tol_sq
        ]
        if not centered:
            continue
        best = max(centered, key=lambda c: c[2])
        return float(best[0]), float(best[1]), float(best[2]), pass_name
    return None


def _crop_mask_resize(bgr: np.ndarray, cx: int, cy: int, r: int,
                      method: str) -> NormalizationResult:
    """Crop tangent square + alpha mask + resize 224. Same logic as prod."""
    h, w = bgr.shape[:2]
    margin = int(r * COIN_MARGIN)
    half = r + margin
    x0 = max(0, cx - half)
    y0 = max(0, cy - half)
    x1 = min(w, cx + half)
    y1 = min(h, cy + half)

    side = min(x1 - x0, y1 - y0)
    x1, y1 = x0 + side, y0 + side

    crop = bgr[y0:y1, x0:x1].copy()
    if crop.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty crop"})

    crop_cx = cx - x0
    crop_cy = cy - y0

    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (crop_cx, crop_cy), r, 255, -1)
    bg = np.full_like(crop, BG_COLOR, dtype=np.uint8)
    crop = np.where(mask[..., None].astype(bool), crop, bg)

    out = cv2.resize(crop, (OUTPUT_SIZE, OUTPUT_SIZE), interpolation=cv2.INTER_AREA)
    return NormalizationResult(
        image=out, cx=cx, cy=cy, r=r, method=method,
        debug={"input_size": (w, h), "crop_side": side, "margin_px": margin},
    )


def normalize_workres(bgr: np.ndarray, work_long_side: int | None,
                       cascade: str = "prod",
                       mode: int = cv2.HOUGH_GRADIENT) -> NormalizationResult:
    """Variant: optionally downscale to fixed working res, run Hough cascade,
    scale detection back to full-res, then crop/mask/resize on full-res.
    `work_long_side=None` → no downscale (full-res Hough)."""
    if bgr is None or bgr.size == 0:
        return NormalizationResult(image=None, debug={"error": "empty input"})

    h, w = bgr.shape[:2]
    long_side = max(h, w)
    if work_long_side is not None and long_side > work_long_side:
        scale = work_long_side / long_side
        small = cv2.resize(bgr, (int(round(w * scale)), int(round(h * scale))),
                           interpolation=cv2.INTER_AREA)
    else:
        scale = 1.0
        small = bgr

    sh, sw = small.shape[:2]
    short = min(sh, sw)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    img_cx, img_cy = sw / 2.0, sh / 2.0
    center_tol_sq = (0.30 * short) ** 2

    passes = HOUGH_CASCADES[cascade]
    det = _hough_passes_on_gray(gray, short, img_cx, img_cy, center_tol_sq, passes, mode)
    if det is None:
        return NormalizationResult(image=None, debug={"error": "no circle"})

    cx_lo, cy_lo, r_lo, method = det
    inv_scale = 1.0 / scale
    cx = int(round(cx_lo * inv_scale))
    cy = int(round(cy_lo * inv_scale))
    r = int(round(r_lo * inv_scale))
    return _crop_mask_resize(bgr, cx, cy, r, method)


def normalize_alt(bgr: np.ndarray) -> NormalizationResult:
    """HOUGH_GRADIENT_ALT, full-res, prod cascade (with ALT-style params)."""
    return normalize_workres(bgr, work_long_side=None, cascade="alt",
                              mode=cv2.HOUGH_GRADIENT_ALT)


# ---------------------------------------------------------------------------
# Bench harness
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    variant: str
    image_id: str
    input_w: int
    input_h: int
    wall_ms: float           # median over RUNS
    success: bool
    cx: int = 0
    cy: int = 0
    r: int = 0
    method: str = "failed"
    out: np.ndarray | None = None  # 224x224 BGR
    timed_out: bool = False


def _time_variant(fn: Callable[[], NormalizationResult], runs: int,
                   warmup: bool, max_seconds: float | None) -> tuple[float, NormalizationResult, bool]:
    """Run `fn` `runs` times (median wall-clock returned in ms). If
    `max_seconds` is set and any single invocation exceeds it, abort and
    return what we have with `timed_out=True`. `warmup` adds an extra
    invocation before timing starts."""
    last = None
    if warmup:
        t0 = time.perf_counter()
        last = fn()
        warm_dt = time.perf_counter() - t0
        if max_seconds is not None and warm_dt > max_seconds:
            return warm_dt * 1000.0, last, True
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        last = fn()
        dt = time.perf_counter() - t0
        times.append(dt * 1000.0)
        if max_seconds is not None and dt > max_seconds:
            return statistics.median(times), last, True
    return statistics.median(times), last, False


def _diff_metrics(base: np.ndarray, var: np.ndarray) -> dict:
    """Compare two 224x224 BGR uint8 outputs."""
    if base is None or var is None:
        return {"mae": float("nan"), "max": 255, "pct_diff": 100.0}
    if base.shape != var.shape:
        return {"mae": float("nan"), "max": 255, "pct_diff": 100.0}
    diff = np.abs(base.astype(np.int16) - var.astype(np.int16))
    return {
        "mae": float(diff.mean()),
        "max": int(diff.max()),
        "pct_diff": float((diff > 1).any(axis=-1).mean() * 100.0),
    }


def sample_dataset(root: Path, per_bucket: int, seed: int = 42) -> list[Path]:
    """Pick `per_bucket` images per size bucket, deterministic (seed)."""
    pool: list[tuple[int, Path]] = []
    for d in sorted(os.listdir(root)):
        p = root / d / "obverse.jpg"
        if p.is_file():
            pool.append((p.stat().st_size, p))
    rng = random.Random(seed)
    by_bucket: dict[str, list[Path]] = {"<1200": [], "1200-1800": [],
                                         "1800-2400": [], "2400+": []}
    log(f"  scanning {len(pool)} candidate images for size bucketing…")
    for _, p in pool:
        try:
            w, h = cv2.imread(str(p), cv2.IMREAD_REDUCED_COLOR_8).shape[1::-1]
            full = max(w * 8, h * 8)
        except Exception:
            continue
        if full < 1200: by_bucket["<1200"].append(p)
        elif full < 1800: by_bucket["1200-1800"].append(p)
        elif full < 2400: by_bucket["1800-2400"].append(p)
        else: by_bucket["2400+"].append(p)
    chosen: list[Path] = []
    for name, lst in by_bucket.items():
        rng.shuffle(lst)
        chosen.extend(lst[:per_bucket])
        log(f"    bucket {name:11s}: {len(lst):4d} available, {min(per_bucket, len(lst)):2d} sampled")
    return chosen


def fmt_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for i, r in enumerate(rows):
        out.append(" | ".join(c.ljust(widths[j]) for j, c in enumerate(r)))
        if i == 0:
            out.append("-+-".join("-" * w for w in widths))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-bucket", type=int, default=6,
                    help="images sampled per size bucket (4 buckets total)")
    ap.add_argument("--datasets", default="ml/datasets")
    ap.add_argument("--out-dir", default="ml/tests/_bench_out")
    ap.add_argument("--max-seconds-per-cell", type=float, default=120.0,
                    help="abort a single (image, variant) if any run exceeds this")
    ap.add_argument("--include-alt", action="store_true",
                    help="also bench HOUGH_GRADIENT_ALT (slow, full-res)")
    args = ap.parse_args()

    root = Path(args.datasets).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"Bench config:")
    log(f"  datasets root        = {root}")
    log(f"  per-bucket           = {args.per_bucket}")
    log(f"  max-seconds-per-cell = {args.max_seconds_per_cell}")
    log(f"  include-alt          = {args.include_alt}")
    log(f"  out-dir              = {out_dir}")
    log("")
    log("Sampling images…")

    paths = sample_dataset(root, args.per_bucket)
    log(f"  → {len(paths)} images selected\n")

    # Order matters: cheap variants first so partial-run cancellation still
    # gives useful workres_* numbers. Per-variant `runs`: workres_* needs
    # tight timing precision (median of 3); baseline / alt_fullres are slow
    # parity-reference variants where we only need the output, not the wall.
    variants: list[tuple[str, Callable[[np.ndarray], NormalizationResult], int, bool]] = [
        # name,                       fn,                                                                runs, warmup
        ("workres_1024_tightR",       lambda b: normalize_workres(b, 1024, cascade="tight_radius"),       3,    True),
        ("workres_1024_prodR",        lambda b: normalize_workres(b, 1024, cascade="prod"),               3,    True),
        ("fullres_tightR",            lambda b: normalize_workres(b, None, cascade="tight_radius"),       3,    True),
    ]
    if args.include_alt:
        variants.append(("alt_fullres", lambda b: normalize_alt(b), 1, False))
    variants.append(("baseline", lambda b: normalize_baseline(b),   1, False))

    variant_names = [v[0] for v in variants]
    by_image: dict[str, dict[str, RunResult]] = {}
    bench_t0 = time.perf_counter()

    for i, p in enumerate(paths, 1):
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            log(f"[{i:2d}/{len(paths)}] {p.parent.name}  SKIP (cv2.imread failed)")
            continue
        h, w = bgr.shape[:2]
        image_id = p.parent.name
        log(f"[{i:2d}/{len(paths)}] id={image_id}  {w}x{h}  (bench elapsed {time.perf_counter()-bench_t0:.0f}s)")
        by_image[image_id] = {}
        for k, (name, fn, runs, warmup) in enumerate(variants, 1):
            t_cell = time.perf_counter()
            try:
                ms, res, timed_out = _time_variant(
                    lambda: fn(bgr), runs=runs, warmup=warmup,
                    max_seconds=args.max_seconds_per_cell,
                )
            except Exception as e:
                log(f"   [{k}/{len(variants)}] {name:14s}  ERROR: {e}")
                continue
            ok = res.image is not None
            cell_wall = time.perf_counter() - t_cell
            by_image[image_id][name] = RunResult(
                variant=name, image_id=image_id, input_w=w, input_h=h,
                wall_ms=ms, success=ok,
                cx=res.cx, cy=res.cy, r=res.r,
                method=res.method, out=res.image, timed_out=timed_out,
            )
            tag = " TIMEOUT" if timed_out else ""
            log(f"   [{k}/{len(variants)}] {name:14s}  median={ms:8.1f}ms  cell={cell_wall:5.1f}s  ok={ok}  c=({res.cx:5d},{res.cy:5d}) r={res.r:5d}  m={res.method}{tag}")

    log(f"\nBench finished in {time.perf_counter()-bench_t0:.1f}s")

    # ----- Aggregate summary -----
    log("\n\n=== Summary: median wall-clock per variant per size bucket (ms) ===")
    bucket_of = lambda w, h: (
        "<1200" if max(w, h) < 1200 else
        "1200-1800" if max(w, h) < 1800 else
        "1800-2400" if max(w, h) < 2400 else
        "2400+"
    )
    times_bucket: dict[tuple[str, str], list[float]] = {}
    for img, runs in by_image.items():
        if "baseline" not in runs:
            continue
        b = bucket_of(runs["baseline"].input_w, runs["baseline"].input_h)
        for name, r in runs.items():
            times_bucket.setdefault((b, name), []).append(r.wall_ms)
    buckets = ["<1200", "1200-1800", "1800-2400", "2400+"]
    rows = [["variant"] + buckets]
    for name in variant_names:
        row = [name]
        for b in buckets:
            vals = times_bucket.get((b, name), [])
            row.append(f"{statistics.median(vals):.0f}" if vals else "-")
        rows.append(row)
    log(fmt_table(rows))

    # ----- Parity vs baseline -----
    log("\n=== Parity vs baseline (224x224 output diff + center/radius delta) ===")
    log("Reported: median over images where both succeeded")
    rows = [["variant", "n_ok", "miss_vs_base", "|Δcx| px", "|Δcy| px", "|Δr| px",
             "mae 224", "max 224", "pct>1/255"]]
    for name in variant_names:
        if name == "baseline":
            continue
        d_cx, d_cy, d_r = [], [], []
        mae, mx, pct = [], [], []
        n_ok = 0
        miss = 0
        for img, runs in by_image.items():
            b = runs.get("baseline")
            v = runs.get(name)
            if not (b and v):
                continue
            if not b.success:
                continue
            if not v.success:
                miss += 1
                continue
            n_ok += 1
            d_cx.append(abs(b.cx - v.cx))
            d_cy.append(abs(b.cy - v.cy))
            d_r.append(abs(b.r - v.r))
            m = _diff_metrics(b.out, v.out)
            mae.append(m["mae"]); mx.append(m["max"]); pct.append(m["pct_diff"])
        med = lambda lst: f"{statistics.median(lst):.2f}" if lst else "-"
        mx_max = lambda lst: f"{max(lst)}" if lst else "-"
        rows.append([
            name, str(n_ok), str(miss),
            med(d_cx), med(d_cy), med(d_r),
            med(mae), mx_max(mx), med(pct),
        ])
    log(fmt_table(rows))

    # ----- Worst-case per variant -----
    log("\n=== Worst-case parity per variant (max |Δr| across all images) ===")
    rows = [["variant", "image_id", "input", "Δcx", "Δcy", "Δr", "mae", "max"]]
    for name in variant_names:
        if name == "baseline":
            continue
        worst = None
        for img, runs in by_image.items():
            b = runs.get("baseline"); v = runs.get(name)
            if not (b and v and b.success and v.success):
                continue
            dr = abs(b.r - v.r)
            if worst is None or dr > worst[0]:
                m = _diff_metrics(b.out, v.out)
                worst = (dr, img, b, v, m)
        if worst:
            dr, img, b, v, m = worst
            rows.append([name, img, f"{b.input_w}x{b.input_h}",
                         str(b.cx - v.cx), str(b.cy - v.cy), str(dr),
                         f"{m['mae']:.2f}", str(m["max"])])
    log(fmt_table(rows))

    # ----- Dump worst diffs to disk -----
    dumped = 0
    for name in variant_names:
        if name == "baseline":
            continue
        worst_dr = -1
        worst = None
        for img, runs in by_image.items():
            b = runs.get("baseline"); v = runs.get(name)
            if not (b and v and b.success and v.success):
                continue
            dr = abs(b.r - v.r)
            if dr > worst_dr:
                worst_dr = dr
                worst = (img, b, v)
        if worst and worst[1].out is not None and worst[2].out is not None:
            img, b, v = worst
            row = np.hstack([b.out, v.out, np.abs(b.out.astype(np.int16) - v.out.astype(np.int16)).clip(0, 255).astype(np.uint8)])
            cv2.imwrite(str(out_dir / f"worst_{name}_{img}.png"), row)
            dumped += 1
    if dumped:
        log(f"\nWrote {dumped} worst-case triptychs (baseline | variant | abs diff) → {out_dir}")


if __name__ == "__main__":
    main()
