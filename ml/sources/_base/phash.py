"""64-bit DCT perceptual hash.

Compatible with the `hamming()` / `phash_match()` UDFs registered in
`state/store.py::_register_phash_udfs`. Returned as a Python int — the
UDFs handle sign normalization, so the value can be stored directly in
the `phash INTEGER` column (SQLite signed 64-bit).

Algorithm (the standard pHash from Zauner 2010, used by ImageHash):
1. Resize to 32×32 grayscale.
2. 2-D DCT.
3. Take the top-left 8×8 (low frequencies, excluding DC).
4. Threshold against the median.
5. Pack the 64 bits into one int.
"""

from __future__ import annotations

import cv2
import numpy as np


def compute_phash(bgr: np.ndarray) -> int:
    if bgr is None or bgr.size == 0:
        raise ValueError("compute_phash: empty input")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)
    block = dct[:8, :8].copy()
    # Drop the DC term (top-left) before computing the median, as it
    # otherwise dominates and biases all bits.
    flat = block.flatten()
    flat_sans_dc = flat[1:]
    median = float(np.median(flat_sans_dc))
    bits = (flat > median).astype(np.uint8)
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    # SQLite INTEGER is signed 64-bit. Convert the unsigned 64-bit
    # bit-pattern into the equivalent signed int so it round-trips
    # without OverflowError. The hamming UDF re-masks via 0xFF..FF so
    # XOR semantics are preserved.
    if value >= 1 << 63:
        value -= 1 << 64
    return value


def hamming(a: int, b: int) -> int:
    return ((int(a) ^ int(b)) & 0xFFFFFFFFFFFFFFFF).bit_count()
