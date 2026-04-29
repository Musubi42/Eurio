"""Sandbox bench for the prod normalizers.

Runs `normalize_studio` and `normalize_device` from `ml/scan/normalize_snap.py`
on a stratified sample (size buckets + explicit bimétal + low-contrast) and
reports wall-clock + cross-algo parity (MAE 224×224, |Δr|, fallback rate).
The cross-algo reference is `normalize_device`; that's the same convention
used by `ml/tests/measure_parity_baseline.py` and the parity-contract.

Usage:
    go-task ml:scan:bench-normalize -- [--per-bucket N] [--variants studio,device]

No prod code modified by this script — it imports the prod functions and
times them. Use it to track wall-clock evolution after micro-tweaks to
`normalize_studio` / `normalize_device`.
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

sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan.normalize_snap import (  # noqa: E402
    NormalizationResult,
    normalize_device,
    normalize_studio,
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


# Phase A explicit IDs. Picked from coin_catalog.json + a contrast-ranking
# script (see implementation-plan.md §Phase A Log). All present in
# ml/datasets/<id>/obverse.jpg.
EXPLICIT_BIMETAL = [64, 9761, 2193, 2163, 5055, 28191]
EXPLICIT_LOW_CONTRAST = [2180, 164656, 3911, 168218]


# ---------------------------------------------------------------------------
# Bench harness
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    variant: str
    image_id: str
    input_w: int
    input_h: int
    wall_ms: float
    success: bool
    tags: tuple[str, ...] = ()
    cx: int = 0
    cy: int = 0
    r: int = 0
    method: str = "failed"
    out: np.ndarray | None = None
    timed_out: bool = False
    fallback_reason: str | None = None


def _time_variant(fn: Callable[[], NormalizationResult], runs: int,
                   warmup: bool, max_seconds: float | None
                   ) -> tuple[float, NormalizationResult, bool]:
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


def sample_dataset(root: Path, per_bucket: int, seed: int = 42,
                    explicit_bimetal: list[int] | None = None,
                    explicit_low_contrast: list[int] | None = None,
                    ) -> list[tuple[Path, tuple[str, ...]]]:
    """Pick `per_bucket` images per size bucket (deterministic seed) plus the
    optional explicit ID lists. Returns (path, tags)."""
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
    bucket_of_path: dict[Path, str] = {}
    for name, lst in by_bucket.items():
        for p in lst:
            bucket_of_path[p] = name

    chosen: dict[Path, set[str]] = {}
    for name, lst in by_bucket.items():
        rng.shuffle(lst)
        for p in lst[:per_bucket]:
            chosen.setdefault(p, set()).add(f"bucket:{name}")
        log(f"    bucket {name:11s}: {len(lst):4d} available, {min(per_bucket, len(lst)):2d} sampled")

    def _add_explicit(ids: list[int], tag: str) -> None:
        added = 0
        missing = []
        for i in ids:
            p = root / str(i) / "obverse.jpg"
            if not p.is_file():
                missing.append(i)
                continue
            chosen.setdefault(p, set()).add(tag)
            b = bucket_of_path.get(p, "?")
            if b != "?":
                chosen[p].add(f"bucket:{b}")
            added += 1
        log(f"    explicit {tag:14s}: {added}/{len(ids)} added"
            + (f" (missing: {missing})" if missing else ""))

    if explicit_bimetal:
        _add_explicit(explicit_bimetal, "bimetal")
    if explicit_low_contrast:
        _add_explicit(explicit_low_contrast, "low_contrast")

    return [(p, tuple(sorted(tags))) for p, tags in chosen.items()]


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-bucket", type=int, default=6)
    ap.add_argument("--datasets", default="ml/datasets")
    ap.add_argument("--out-dir", default="ml/tests/_bench_out")
    ap.add_argument("--max-seconds-per-cell", type=float, default=30.0)
    ap.add_argument("--skip-explicit", action="store_true",
                    help="skip the bimétal + low-contrast explicit IDs")
    ap.add_argument("--variants", default=None,
                    help="comma-separated subset (default: studio,device)")
    args = ap.parse_args()

    root = Path(args.datasets).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"Bench config:")
    log(f"  datasets root        = {root}")
    log(f"  per-bucket           = {args.per_bucket}")
    log(f"  max-seconds-per-cell = {args.max_seconds_per_cell}")
    log(f"  skip-explicit        = {args.skip_explicit}")
    log(f"  out-dir              = {out_dir}")
    log("")
    log("Sampling images…")

    sampled = sample_dataset(
        root, args.per_bucket,
        explicit_bimetal=None if args.skip_explicit else EXPLICIT_BIMETAL,
        explicit_low_contrast=None if args.skip_explicit else EXPLICIT_LOW_CONTRAST,
    )
    log(f"  → {len(sampled)} images selected\n")

    # Two prod variants. Reference for parity = `device`.
    variants: list[tuple[str, Callable[[np.ndarray], NormalizationResult], int, bool]] = [
        # name,    fn,                               runs, warmup
        ("studio", lambda b: normalize_studio(b),    3,    True),
        ("device", lambda b: normalize_device(b),    3,    True),
    ]
    if args.variants:
        wanted = {v.strip() for v in args.variants.split(",") if v.strip()}
        variants = [v for v in variants if v[0] in wanted]
        log(f"  variant filter        = {sorted(wanted)} → {[v[0] for v in variants]}")
    if not variants:
        log("  no variants selected — abort.")
        return

    variant_names = [v[0] for v in variants]
    by_image: dict[str, dict[str, RunResult]] = {}
    tags_of: dict[str, tuple[str, ...]] = {}
    bench_t0 = time.perf_counter()

    for i, (p, tags) in enumerate(sampled, 1):
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            log(f"[{i:2d}/{len(sampled)}] {p.parent.name}  SKIP (cv2.imread failed)")
            continue
        h, w = bgr.shape[:2]
        image_id = p.parent.name
        tags_of[image_id] = tags
        tag_str = ",".join(tags) if tags else "-"
        log(f"[{i:2d}/{len(sampled)}] id={image_id}  {w}x{h}  tags=[{tag_str}]  "
            f"(bench elapsed {time.perf_counter()-bench_t0:.0f}s)")
        by_image[image_id] = {}
        for k, (name, fn, runs, warmup) in enumerate(variants, 1):
            t_cell = time.perf_counter()
            try:
                ms, res, timed_out = _time_variant(
                    lambda: fn(bgr), runs=runs, warmup=warmup,
                    max_seconds=args.max_seconds_per_cell,
                )
            except Exception as e:
                log(f"   [{k}/{len(variants)}] {name:8s}  ERROR: {e}")
                continue
            ok = res.image is not None
            cell_wall = time.perf_counter() - t_cell
            fb = res.debug.get("fallback_reason") if res.debug else None
            by_image[image_id][name] = RunResult(
                variant=name, image_id=image_id, input_w=w, input_h=h,
                wall_ms=ms, success=ok, tags=tags,
                cx=res.cx, cy=res.cy, r=res.r,
                method=res.method, out=res.image, timed_out=timed_out,
                fallback_reason=fb,
            )
            timeout_marker = " TIMEOUT" if timed_out else ""
            fb_marker = f" fb={fb}" if fb else ""
            log(f"   [{k}/{len(variants)}] {name:8s}  median={ms:8.1f}ms  "
                f"cell={cell_wall:5.1f}s  ok={ok}  c=({res.cx:5d},{res.cy:5d}) "
                f"r={res.r:5d}  m={res.method}{timeout_marker}{fb_marker}")

    log(f"\nBench finished in {time.perf_counter()-bench_t0:.1f}s")

    ref_name = "device"
    bucket_of = lambda w, h: (
        "<1200" if max(w, h) < 1200 else
        "1200-1800" if max(w, h) < 1800 else
        "1800-2400" if max(w, h) < 2400 else
        "2400+"
    )

    # ----- Wall-clock per variant per size bucket -----
    log("\n\n=== Median wall-clock per variant per size bucket (ms) ===")
    times_bucket: dict[tuple[str, str], list[float]] = {}
    for img, runs in by_image.items():
        anyr = next(iter(runs.values()), None)
        if anyr is None:
            continue
        b = bucket_of(anyr.input_w, anyr.input_h)
        for name, r in runs.items():
            times_bucket.setdefault((b, name), []).append(r.wall_ms)
    buckets = ["<1200", "1200-1800", "1800-2400", "2400+"]
    rows = [["variant"] + buckets + ["all"]]
    for name in variant_names:
        row = [name]
        all_vals = []
        for b in buckets:
            vals = times_bucket.get((b, name), [])
            all_vals.extend(vals)
            row.append(f"{statistics.median(vals):.0f}" if vals else "-")
        row.append(f"{statistics.median(all_vals):.0f}" if all_vals else "-")
        rows.append(row)
    log(fmt_table(rows))

    # ----- Studio fallback rate -----
    if "studio" in variant_names:
        log("\n=== studio fallback rate per tag ===")
        rows = [["tag", "n", "n_fallback", "fallback %", "ids_fallback"]]
        groups: dict[str, list[RunResult]] = {"all": []}
        for img, runs in by_image.items():
            r = runs.get("studio")
            if r is None:
                continue
            groups["all"].append(r)
            for t in tags_of.get(img, ()):
                groups.setdefault(t, []).append(r)
        for tag in ["all"] + [t for t in sorted(groups) if t != "all"]:
            results = groups.get(tag, [])
            if not results:
                continue
            fb = [r for r in results
                  if r.method.startswith("contour_fallback") or not r.success]
            ids_fb = ",".join(sorted({r.image_id for r in fb}))[:60]
            rows.append([tag, str(len(results)), str(len(fb)),
                         f"{100.0*len(fb)/len(results):.1f}",
                         ids_fb or "-"])
        log(fmt_table(rows))

    # ----- Parity vs device -----
    if ref_name in variant_names and len(variant_names) >= 2:
        log(f"\n=== Parity vs {ref_name} (224×224 output diff + |Δr|) ===")
        rows = [["variant", "n_ok", "miss_vs_ref", "|Δcx| px", "|Δcy| px",
                 "|Δr| px", "mae 224 (med)", "mae 224 (p95)", "max 224 (max)"]]
        for name in variant_names:
            if name == ref_name:
                continue
            d_cx, d_cy, d_r, mae, mx = [], [], [], [], []
            n_ok = 0
            miss = 0
            for img, runs in by_image.items():
                ref = runs.get(ref_name); v = runs.get(name)
                if not (ref and v):
                    continue
                if not ref.success:
                    continue
                if not v.success:
                    miss += 1
                    continue
                n_ok += 1
                d_cx.append(abs(ref.cx - v.cx))
                d_cy.append(abs(ref.cy - v.cy))
                d_r.append(abs(ref.r - v.r))
                m = _diff_metrics(ref.out, v.out)
                mae.append(m["mae"]); mx.append(m["max"])
            med = lambda lst: f"{statistics.median(lst):.2f}" if lst else "-"
            p95 = lambda lst: f"{np.percentile(lst, 95):.2f}" if lst else "-"
            rows.append([name, str(n_ok), str(miss),
                         med(d_cx), med(d_cy), med(d_r),
                         med(mae), p95(mae),
                         f"{max(mx)}" if mx else "-"])
        log(fmt_table(rows))

    # ----- Worst-case triptychs (top-3 MAE) -----
    if "studio" in variant_names and ref_name in variant_names:
        ranked: list[tuple[float, str, RunResult, RunResult]] = []
        for img, runs in by_image.items():
            ref = runs.get(ref_name); v = runs.get("studio")
            if not (ref and v and ref.success and v.success):
                continue
            m = _diff_metrics(ref.out, v.out)
            ranked.append((m["mae"], img, ref, v))
        ranked.sort(key=lambda x: -x[0])
        dumped = 0
        for k, (mae, img, ref, v) in enumerate(ranked[:3]):
            if v.out is None or ref.out is None:
                continue
            row = np.hstack([
                ref.out, v.out,
                np.abs(ref.out.astype(np.int16) - v.out.astype(np.int16))
                  .clip(0, 255).astype(np.uint8),
            ])
            tagstr = "_".join(tags_of.get(img, ())) or "untagged"
            cv2.imwrite(str(out_dir / f"worst_studio_mae{k+1}_{img}_{tagstr}.png"),
                        row)
            dumped += 1
        if dumped:
            log(f"\nWrote {dumped} worst-case triptychs (device | studio | abs_diff) → {out_dir}")


if __name__ == "__main__":
    main()
