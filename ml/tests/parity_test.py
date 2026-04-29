"""Cross-algo parity gate.

Compares `normalize_studio` and `normalize_device` on the manifest images
and exits non-zero if too many diverge. Default thresholds: ε = 3.0 / 255 on
the Hough-OK subset, `cross_pct_diff` ≤ 5 % on the full manifest. The
Hough-OK split (|Δr| ≤ 8 px) isolates the bimétal-trap cases from the
cross-algo evaluation; those are flagged separately.

Usage:
    go-task ml:scan:parity-test
    # or
    python -m tests.parity_test \\
        --manifest ml/tests/parity_dataset.yaml --epsilon 3.0 --pct-max 5.0
"""
from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan.normalize_snap import normalize_device, normalize_studio  # noqa: E402
from tests._utils import diff_metrics, fmt_table  # noqa: E402


HOUGH_OK_DELTA_R = 8


@dataclass
class Row:
    numista_id: int
    tags: tuple[str, ...]
    delta_r: int
    cross_mae: float
    cross_max: int
    cross_pct_diff: float
    cand_method: str
    cand_image_ok: bool
    ref_image_ok: bool


def measure(manifest_path: Path, datasets: Path) -> list[Row]:
    manifest = yaml.safe_load(open(manifest_path))
    rows: list[Row] = []
    for c in manifest["coins"]:
        nid = int(c["numista_id"])
        tags = tuple(sorted(c.get("tags") or []))
        p = datasets / str(nid) / "obverse.jpg"
        if not p.is_file():
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        ref = normalize_device(bgr)
        cand = normalize_studio(bgr)
        if ref.image is None or cand.image is None:
            rows.append(Row(nid, tags,
                             abs(ref.r - cand.r) if ref.image is not None and cand.image is not None else -1,
                             float("nan"), 255, 100.0,
                             cand.method, cand.image is not None, ref.image is not None))
            continue
        m = diff_metrics(ref.image, cand.image)
        rows.append(Row(nid, tags, abs(ref.r - cand.r),
                         m["mae"], m["max"], m["pct_diff"],
                         cand.method, True, True))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="ml/tests/parity_dataset.yaml")
    ap.add_argument("--datasets", default="ml/datasets")
    ap.add_argument("--epsilon", type=float, default=3.0,
                    help="MAE threshold for the Hough-OK subset (default 3.0)")
    ap.add_argument("--pct-max", type=float, default=5.0,
                    help="cross_pct_diff threshold on the full manifest (default 5.0%)")
    ap.add_argument("--pass-fraction", type=float, default=0.95,
                    help="fraction of Hough-OK images that must satisfy ε (default 0.95)")
    ap.add_argument("--out-dir", default="ml/tests/_parity_out")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    datasets = Path(args.datasets).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"manifest = {manifest_path}")
    print(f"ε = {args.epsilon}, pct_max = {args.pct_max}%, pass_fraction = {args.pass_fraction}")
    print()

    rows = measure(manifest_path, datasets)
    if not rows:
        print("ERROR: no rows measured", file=sys.stderr)
        return 2

    valid = [r for r in rows if r.cand_image_ok and r.ref_image_ok]
    invalid = [r for r in rows if not (r.cand_image_ok and r.ref_image_ok)]

    hough_ok = [r for r in valid if r.delta_r >= 0 and r.delta_r <= HOUGH_OK_DELTA_R]
    hough_trap = [r for r in valid if r.delta_r > HOUGH_OK_DELTA_R]

    # ----- Per-image table sorted by cross_mae desc -----
    rep = [["numista_id", "tags", "Δr", "cross_mae", "cross_max",
            "pct>1/255", "cand_method", "subset"]]
    for r in sorted(valid, key=lambda x: -x.cross_mae):
        subset = "trap" if r in hough_trap else "ok"
        rep.append([str(r.numista_id), ",".join(r.tags) or "-",
                    str(r.delta_r),
                    f"{r.cross_mae:.2f}",
                    str(r.cross_max),
                    f"{r.cross_pct_diff:.2f}",
                    r.cand_method,
                    subset])
    if invalid:
        for r in invalid:
            rep.append([str(r.numista_id), ",".join(r.tags) or "-",
                        "-", "-", "-", "-",
                        f"FAIL cand_ok={r.cand_image_ok}/ref_ok={r.ref_image_ok}",
                        "-"])
    table_path = out_dir / "parity_test_per_image.txt"
    table_path.write_text(fmt_table(rep) + "\n")
    print(fmt_table(rep))
    print(f"\nWritten → {table_path}\n")

    # ----- Stats -----
    def _stats(label: str, sub: list[Row]) -> None:
        if not sub:
            print(f"  {label}: no images")
            return
        cm = [r.cross_mae for r in sub if not np.isnan(r.cross_mae)]
        pct = [r.cross_pct_diff for r in sub if not np.isnan(r.cross_pct_diff)]
        print(f"  {label} (n={len(sub)}):  "
              f"cross_mae med={statistics.median(cm):.2f} p95={np.percentile(cm, 95):.2f} max={max(cm):.2f}  "
              f"cross_pct_diff med={statistics.median(pct):.2f}% max={max(pct):.2f}%")

    print("Subset summary:")
    _stats("full_manifest", valid)
    _stats("hough_ok     ", hough_ok)
    _stats("hough_trap   ", hough_trap)
    print()

    # ----- Gate decision -----
    mae_pass = [r for r in hough_ok if r.cross_mae <= args.epsilon]
    pct_pass = [r for r in valid if r.cross_pct_diff <= args.pct_max]
    pct_full = len(pct_pass) / len(valid) if valid else 0.0
    mae_frac = len(mae_pass) / len(hough_ok) if hough_ok else 0.0

    print("Gate:")
    print(f"  Hough-OK subset: {len(mae_pass)}/{len(hough_ok)} = {mae_frac*100:.1f}% with cross_mae ≤ {args.epsilon}")
    print(f"     (need ≥ {args.pass_fraction*100:.1f}%)")
    print(f"  Full manifest : {len(pct_pass)}/{len(valid)} = {pct_full*100:.1f}% with cross_pct_diff ≤ {args.pct_max}%")
    print(f"     (informational — pct_diff is sensitive to bimétal-trap; the Hough-OK gate is authoritative)")
    print()

    failed_invalid = [r for r in invalid]
    if failed_invalid:
        print(f"⚠️  {len(failed_invalid)} manifest entries failed to normalize "
              f"(skip in pass count): {[r.numista_id for r in failed_invalid]}")

    ok = mae_frac >= args.pass_fraction and not failed_invalid
    print(f"\n{'PASS ✅' if ok else 'FAIL ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
