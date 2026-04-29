"""Measure cross-algo parity baseline (Phase B).

Procedure (cf. docs/scan-normalization/normalize-rework/parity-contract.md
§"Choix de ε et M_max"):

  1. Run two passes of `wr_1024_tightR` on each manifest image. Their per-pixel
     diff is the deterministic-noise floor (expected ~0 since the algo is
     deterministic). This is the control.
  2. Run `studio_contour` and `wr_1024_tightR` on each image. Their diff is the
     cross-algo dispersion. This is the measurement target.
  3. Aggregate per-tag, isolate the "Hough-OK" subset (where `wr_1024_tightR`
     happens to land within Δr ≤ 8 of the contour result, i.e. picks the outer
     rim like a non-bimetal-trap case), and report ε / M_max recommendations
     for both the full dataset and the "Hough-OK" subset.

The bench code from `ml/tests/bench_normalize.py` is reused so we don't
re-implement the variants. No prod code modified.

Usage:
    python -m ml.tests.measure_parity_baseline \
        --manifest ml/tests/parity_dataset.yaml \
        --datasets ml/datasets \
        --out-dir ml/tests/_parity_out
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan.normalize_snap import normalize_device, normalize_studio  # noqa: E402
from tests.bench_normalize import _diff_metrics, fmt_table, log  # noqa: E402


REF_NAME = "device"      # = normalize_device (Hough WR=1024 + tight)
CAND_NAME = "studio"     # = normalize_studio (contour + fallback to device)
HOUGH_OK_DELTA_R = 8     # |Δr| threshold (px, native res) below which we
                         # declare Hough not affected by the bimétal-trap.


@dataclass
class ImageMeasurement:
    numista_id: int
    tags: tuple[str, ...]
    input_w: int
    input_h: int
    ref_method: str
    cand_method: str
    delta_r_px: int             # |r_ref - r_cand| in native pixels
    control_mae: float          # ref ↔ ref (deterministic noise floor)
    control_max: int
    cross_mae: float            # cand ↔ ref (cross-algo)
    cross_max: int
    cross_pct_diff: float       # % pixels where channel diff > 1/255
    fallback_reason: str | None


def _ref_call(bgr: np.ndarray):
    return normalize_device(bgr)


def _cand_call(bgr: np.ndarray):
    return normalize_studio(bgr)


def measure_one(bgr: np.ndarray, numista_id: int,
                 tags: tuple[str, ...]) -> ImageMeasurement:
    h, w = bgr.shape[:2]

    # Two ref passes for the deterministic-noise control.
    r1 = _ref_call(bgr)
    r2 = _ref_call(bgr)
    if r1.image is None or r2.image is None:
        ctrl = {"mae": float("nan"), "max": 255, "pct_diff": 100.0}
    else:
        ctrl = _diff_metrics(r1.image, r2.image)

    # Cand vs ref cross-algo.
    c = _cand_call(bgr)
    if c.image is None or r1.image is None:
        cross = {"mae": float("nan"), "max": 255, "pct_diff": 100.0}
    else:
        cross = _diff_metrics(c.image, r1.image)

    delta_r = abs(int(r1.r) - int(c.r)) if (c.image is not None and r1.image is not None) else -1

    return ImageMeasurement(
        numista_id=numista_id, tags=tags, input_w=w, input_h=h,
        ref_method=r1.method, cand_method=c.method,
        delta_r_px=delta_r,
        control_mae=ctrl["mae"], control_max=ctrl["max"],
        cross_mae=cross["mae"], cross_max=cross["max"],
        cross_pct_diff=cross["pct_diff"],
        fallback_reason=(c.debug or {}).get("fallback_reason"),
    )


def _agg(values: list[float], pcts: tuple[int, ...] = (50, 95, 99)) -> dict:
    if not values:
        return {f"p{p}": float("nan") for p in pcts} | {"max": float("nan"),
                                                        "n": 0,
                                                        "mean": float("nan")}
    return {f"p{p}": float(np.percentile(values, p)) for p in pcts} | {
        "max": float(max(values)),
        "n": len(values),
        "mean": float(statistics.mean(values)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="ml/tests/parity_dataset.yaml")
    ap.add_argument("--datasets", default="ml/datasets")
    ap.add_argument("--out-dir", default="ml/tests/_parity_out")
    ap.add_argument("--epsilon-floor", type=float, default=3.0,
                    help="lower bound on recommended ε (rounding floor)")
    ap.add_argument("--epsilon-margin", type=float, default=1.2,
                    help="multiplier on p95 to set ε")
    ap.add_argument("--mmax-margin", type=float, default=1.2,
                    help="multiplier on p99 to set M_max")
    args = ap.parse_args()

    manifest = yaml.safe_load(open(args.manifest))
    coins = manifest["coins"]
    datasets = Path(args.datasets).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"Manifest      : {args.manifest} ({len(coins)} entries)")
    log(f"Datasets root : {datasets}")
    log(f"Out dir       : {out_dir}")
    log(f"Reference algo: {REF_NAME} (= normalize_device, Hough WR=1024 + tight)")
    log(f"Candidate algo: {CAND_NAME} (= normalize_studio, contour + fallback)")
    log("")

    measurements: list[ImageMeasurement] = []
    t0 = time.perf_counter()
    for i, c in enumerate(coins, 1):
        nid = int(c["numista_id"])
        tags = tuple(sorted(c.get("tags", []) or []))
        p = datasets / str(nid) / "obverse.jpg"
        if not p.is_file():
            log(f"[{i:2d}/{len(coins)}] id={nid}  SKIP (missing obverse.jpg)")
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            log(f"[{i:2d}/{len(coins)}] id={nid}  SKIP (cv2.imread failed)")
            continue
        m = measure_one(bgr, nid, tags)
        measurements.append(m)
        fb = f" fb={m.fallback_reason}" if m.fallback_reason else ""
        log(f"[{i:2d}/{len(coins)}] id={nid:>6}  {m.input_w}x{m.input_h}  "
            f"Δr={m.delta_r_px:>3}px  ctrl_mae={m.control_mae:5.2f}  "
            f"cross_mae={m.cross_mae:5.2f}  max={m.cross_max:>3}  "
            f"tags=[{','.join(tags)}]{fb}")
    log(f"\nMeasured {len(measurements)} images in {time.perf_counter()-t0:.1f}s\n")

    # ---- Per-image table to disk ----
    rows = [["numista_id", "tags", "input", "Δr", "ctrl_mae", "ctrl_max",
             "cross_mae", "cross_max", "cross_pct>1", "ref_method",
             "cand_method", "fallback_reason"]]
    for m in sorted(measurements, key=lambda x: -x.cross_mae):
        rows.append([
            str(m.numista_id), ",".join(m.tags) or "-",
            f"{m.input_w}x{m.input_h}", str(m.delta_r_px),
            f"{m.control_mae:.2f}", str(m.control_max),
            f"{m.cross_mae:.2f}", str(m.cross_max),
            f"{m.cross_pct_diff:.2f}", m.ref_method, m.cand_method,
            m.fallback_reason or "-",
        ])
    table_path = out_dir / "per_image.txt"
    table_path.write_text(fmt_table(rows) + "\n")
    log(f"Per-image table written → {table_path}")

    # ---- Agg: control noise floor ----
    log("\n=== Deterministic-noise control: ref ↔ ref (expected ≈ 0) ===")
    ctrl_mae = [m.control_mae for m in measurements
                if not np.isnan(m.control_mae)]
    ctrl_max = [m.control_max for m in measurements]
    a = _agg(ctrl_mae)
    rows = [["metric", "n", "mean", "p50", "p95", "p99", "max"],
            ["ctrl_mae", str(a["n"]), f"{a['mean']:.3f}",
             f"{a['p50']:.3f}", f"{a['p95']:.3f}", f"{a['p99']:.3f}",
             f"{a['max']:.3f}"],
            ["ctrl_max", str(len(ctrl_max)),
             f"{statistics.mean(ctrl_max):.1f}",
             f"{np.percentile(ctrl_max, 50):.0f}",
             f"{np.percentile(ctrl_max, 95):.0f}",
             f"{np.percentile(ctrl_max, 99):.0f}",
             f"{max(ctrl_max)}"]]
    log(fmt_table(rows))

    # ---- Agg: cross-algo ----
    log(f"\n=== Cross-algo: {CAND_NAME} ↔ {REF_NAME} (full manifest) ===")
    cross_mae = [m.cross_mae for m in measurements
                 if not np.isnan(m.cross_mae)]
    cross_max = [m.cross_max for m in measurements]
    a = _agg(cross_mae)
    rows = [["metric", "n", "mean", "p50", "p95", "p99", "max"],
            ["cross_mae", str(a["n"]), f"{a['mean']:.3f}",
             f"{a['p50']:.3f}", f"{a['p95']:.3f}", f"{a['p99']:.3f}",
             f"{a['max']:.3f}"],
            ["cross_max", str(len(cross_max)),
             f"{statistics.mean(cross_max):.1f}",
             f"{np.percentile(cross_max, 50):.0f}",
             f"{np.percentile(cross_max, 95):.0f}",
             f"{np.percentile(cross_max, 99):.0f}",
             f"{max(cross_max)}"]]
    log(fmt_table(rows))

    # ---- Hough-OK subset (the rework's value claim isolates this) ----
    hough_ok = [m for m in measurements if m.delta_r_px >= 0
                and m.delta_r_px <= HOUGH_OK_DELTA_R]
    hough_trap = [m for m in measurements if m.delta_r_px > HOUGH_OK_DELTA_R]
    log(f"\n=== Subset breakdown (|Δr| threshold = {HOUGH_OK_DELTA_R} px) ===")
    log(f"  Hough-OK images   : {len(hough_ok)}/{len(measurements)} (cross-algo dispersion driven by sub-pixel + rounding)")
    log(f"  Hough-trap images : {len(hough_trap)} (Hough latent bug; cross-algo dispersion driven by Δr)")

    if hough_ok:
        log(f"\n=== Cross-algo on Hough-OK subset ({len(hough_ok)} images) ===")
        cm = [m.cross_mae for m in hough_ok if not np.isnan(m.cross_mae)]
        cx = [m.cross_max for m in hough_ok]
        a = _agg(cm)
        rows = [["metric", "n", "mean", "p50", "p95", "p99", "max"],
                ["cross_mae_ok", str(a["n"]), f"{a['mean']:.3f}",
                 f"{a['p50']:.3f}", f"{a['p95']:.3f}", f"{a['p99']:.3f}",
                 f"{a['max']:.3f}"],
                ["cross_max_ok", str(len(cx)),
                 f"{statistics.mean(cx):.1f}",
                 f"{np.percentile(cx, 50):.0f}",
                 f"{np.percentile(cx, 95):.0f}",
                 f"{np.percentile(cx, 99):.0f}",
                 f"{max(cx)}"]]
        log(fmt_table(rows))

    if hough_trap:
        log(f"\n=== Hough-trap subset (cross-algo, {len(hough_trap)} images) ===")
        rows = [["numista_id", "tags", "Δr px", "cross_mae", "cross_max"]]
        for m in sorted(hough_trap, key=lambda x: -x.delta_r_px):
            rows.append([str(m.numista_id), ",".join(m.tags) or "-",
                         str(m.delta_r_px), f"{m.cross_mae:.2f}",
                         str(m.cross_max)])
        log(fmt_table(rows))

    # ---- Per-tag ----
    all_tags = sorted({t for m in measurements for t in m.tags})
    log("\n=== Per-tag cross-algo cross_mae ===")
    rows = [["tag", "n", "mean", "p50", "p95", "p99", "max"]]
    for t in ["all"] + all_tags:
        sub = measurements if t == "all" else [m for m in measurements if t in m.tags]
        cm = [m.cross_mae for m in sub if not np.isnan(m.cross_mae)]
        if not cm:
            continue
        a = _agg(cm)
        rows.append([t, str(a["n"]), f"{a['mean']:.2f}", f"{a['p50']:.2f}",
                     f"{a['p95']:.2f}", f"{a['p99']:.2f}", f"{a['max']:.2f}"])
    log(fmt_table(rows))

    # ---- ε / M_max recommendations ----
    log("\n=== Recommended ε / M_max ===")
    log(f"  procedure: ε = max(p95 × {args.epsilon_margin}, {args.epsilon_floor})")
    log(f"             M_max = p99 × {args.mmax_margin}")
    log("")

    def reco(scope: str, mae_list: list[float], max_list: list[int]) -> dict:
        if not mae_list:
            return {}
        eps = max(np.percentile(mae_list, 95) * args.epsilon_margin, args.epsilon_floor)
        mmax = float(np.percentile(max_list, 99)) * args.mmax_margin
        return {"scope": scope, "n": len(mae_list), "epsilon": float(eps),
                "M_max": float(mmax),
                "p95_mae": float(np.percentile(mae_list, 95)),
                "p99_max": float(np.percentile(max_list, 99))}

    recos = []
    if cross_mae:
        recos.append(reco("full_manifest", cross_mae, cross_max))
    if hough_ok:
        recos.append(reco("hough_ok_subset",
                          [m.cross_mae for m in hough_ok if not np.isnan(m.cross_mae)],
                          [m.cross_max for m in hough_ok]))

    rows = [["scope", "n", "p95_mae", "→ ε", "p99_max", "→ M_max"]]
    for r in recos:
        rows.append([r["scope"], str(r["n"]),
                     f"{r['p95_mae']:.2f}", f"{r['epsilon']:.2f}",
                     f"{r['p99_max']:.0f}", f"{r['M_max']:.0f}"])
    log(fmt_table(rows))

    # ---- JSON dump for downstream tooling ----
    json_path = out_dir / "baseline.json"
    payload = {
        "manifest": str(args.manifest),
        "ref": REF_NAME, "cand": CAND_NAME,
        "n_measured": len(measurements),
        "control": {"mae_p95": float(np.percentile(ctrl_mae, 95)) if ctrl_mae else None,
                    "mae_max": float(max(ctrl_mae)) if ctrl_mae else None,
                    "max_max": int(max(ctrl_max)) if ctrl_max else None},
        "cross_full": {"mae_p95": float(np.percentile(cross_mae, 95)) if cross_mae else None,
                        "mae_p99": float(np.percentile(cross_mae, 99)) if cross_mae else None,
                        "max_p99": float(np.percentile(cross_max, 99)) if cross_max else None},
        "hough_ok_count": len(hough_ok),
        "hough_trap_count": len(hough_trap),
        "recommendations": recos,
        "per_image": [
            {"numista_id": m.numista_id, "tags": list(m.tags),
             "delta_r_px": m.delta_r_px,
             "control_mae": m.control_mae, "control_max": m.control_max,
             "cross_mae": m.cross_mae, "cross_max": m.cross_max,
             "fallback_reason": m.fallback_reason}
            for m in measurements
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2))
    log(f"\nJSON dump → {json_path}")


if __name__ == "__main__":
    main()
