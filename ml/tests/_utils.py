"""Shared helpers for normalize tests (`bench_normalize`, `parity_test`,
`measure_parity_baseline`). Kept here so the bench module can be
archived/skipped without breaking the parity gate that ships in CI."""
from __future__ import annotations

import numpy as np


def diff_metrics(base: np.ndarray | None, var: np.ndarray | None) -> dict:
    """Per-pixel diff metrics between two BGR uint8 images of identical shape.
    Returns ``{"mae": float, "max": int, "pct_diff": float}``. On shape
    mismatch or missing inputs returns the worst-case sentinel."""
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


def fmt_table(rows: list[list[str]]) -> str:
    """Pretty-print a 2D string table with a header underline. Empty rows
    return ``""``."""
    if not rows:
        return ""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for i, r in enumerate(rows):
        out.append(" | ".join(c.ljust(widths[j]) for j, c in enumerate(r)))
        if i == 0:
            out.append("-+-".join("-" * w for w in widths))
    return "\n".join(out)
