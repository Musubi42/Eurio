"""Runtime detection — single source of truth for hardware/backend info.

Used by:
  - train_embedder.py at boot, to log structured info
  - lab_routes.py via /lab/runner/runtime-info, to surface in the UI
  - any caller that needs to pick num_workers etc.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache


@dataclass(frozen=True)
class RuntimeInfo:
    host_os: str
    arch: str
    cpu_brand: str
    torch_version: str
    backend: str   # 'cuda' | 'mps' | 'cpu'
    device: str    # 'cuda:0' | 'mps:0' | 'cpu'
    num_cuda_devices: int
    gpu_name: str | None
    cuda_version: str | None
    dataloader_workers: int
    hint: str


def _detect_cpu_brand() -> str:
    sys = platform.system().lower()
    try:
        if sys == "darwin":
            sysctl = shutil.which("sysctl")
            if sysctl:
                out = subprocess.run(
                    [sysctl, "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, timeout=2,
                )
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.strip()
        elif sys == "linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


def _compose_hint(backend: str, gpu_name: str | None, cuda_version: str | None) -> str:
    if backend == "cuda":
        gpu = gpu_name or "CUDA GPU"
        cuda = f" (CUDA {cuda_version})" if cuda_version else ""
        return f"PC + {gpu}{cuda} — fast"
    if backend == "mps":
        return "Apple Silicon (mps) — slower, OK for iterating"
    return "CPU only — very slow, last resort"


@lru_cache(maxsize=1)
def detect() -> RuntimeInfo:
    host_os = platform.system().lower()
    arch = platform.machine().lower()
    cpu_brand = _detect_cpu_brand()
    try:
        import torch
        torch_version = torch.__version__
        if torch.cuda.is_available():
            backend = "cuda"
            device = "cuda:0"
            num_cuda_devices = torch.cuda.device_count()
            gpu_name = torch.cuda.get_device_name(0)
            cuda_version = torch.version.cuda
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            backend = "mps"
            device = "mps:0"
            num_cuda_devices = 0
            gpu_name = None
            cuda_version = None
        else:
            backend = "cpu"
            device = "cpu"
            num_cuda_devices = 0
            gpu_name = None
            cuda_version = None
        dataloader_workers = 4 if backend == "cuda" else 0
        hint = _compose_hint(backend, gpu_name, cuda_version)
        return RuntimeInfo(
            host_os=host_os,
            arch=arch,
            cpu_brand=cpu_brand,
            torch_version=torch_version,
            backend=backend,
            device=device,
            num_cuda_devices=num_cuda_devices,
            gpu_name=gpu_name,
            cuda_version=cuda_version,
            dataloader_workers=dataloader_workers,
            hint=hint,
        )
    except Exception as exc:  # pragma: no cover — torch import guaranteed by venv
        return RuntimeInfo(
            host_os=host_os,
            arch=arch,
            cpu_brand=cpu_brand,
            torch_version="unknown",
            backend="cpu",
            device="cpu",
            num_cuda_devices=0,
            gpu_name=None,
            cuda_version=None,
            dataloader_workers=0,
            hint=f"runtime detection failed: {exc}",
        )


def to_dict(info: RuntimeInfo) -> dict:
    return asdict(info)
