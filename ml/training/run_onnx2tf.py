"""Wrapper around onnx2tf that bypasses the broken test-image download.

onnx2tf calls `download_test_image_data()` during the output-check phase. The
upstream URL returns a corrupted/HTML blob instead of a valid `.npy`, so the
subsequent `np.load` crashes with UnpicklingError. We replace the function
with a stub that returns a synthetic float32 array of the expected shape
(20, 128, 128, 3) — onnx2tf only uses it for numerical sanity checks, not for
the actual conversion.

Usage: same args as `python -m onnx2tf`, e.g.
    python ml/run_onnx2tf.py -i path/to/best.onnx -o path/to/tflite
"""

from __future__ import annotations

import sys

import numpy as np

import onnx2tf.utils.common_functions as _cf


def _fake_download_test_image_data() -> np.ndarray:
    return np.random.rand(20, 128, 128, 3).astype(np.float32)


_cf.download_test_image_data = _fake_download_test_image_data  # type: ignore[assignment]

# onnx2tf.py imports the function by name at module load, so also patch it there.
from onnx2tf import onnx2tf as _o2t  # noqa: E402

_o2t.download_test_image_data = _fake_download_test_image_data  # type: ignore[assignment]

if __name__ == "__main__":
    sys.argv = ["onnx2tf", *sys.argv[1:]]
    _o2t.main()
