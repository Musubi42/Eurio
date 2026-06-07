"""DINO-based distance between captures réelles ↔ augmentations (Sprint 2 / D-006).

For each coin in an iteration's cohort we encode:
- the on-disk capture set (`<numista_id>/captures/*.jpg`) — "real" view
- the persistent augmentation snapshot (`<numista_id>/augmentations/<iid>/*.jpg`)

via a frozen DINOv2 ViT-S/14 (same encoder as the confusion-map pipeline,
which is intentionally external to the iteration's ArcFace — D-006). We
then compute cosine similarity between the two L2-normalized centroids.

Lower cosine = the recipe is producing samples visually distant from real
captures (likely under-augmented or off-manifold).

Results are cached in `iteration_aug_vs_real`. The cache is invalidated
implicitly by the `(num_real, num_aug)` columns: if the user adds new
captures or regenerates the augmentations snapshot, the recompute will
detect the count delta and overwrite the row. A `dino_version` mismatch
also forces a recompute.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from serving import coin_lookup
from store import AugVsRealRow, Store

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).resolve().parent.parent
DATASETS_DIR = ML_DIR / "datasets"

# Lazy imports of confusion_map keep DINOv2 (~80 MB weights, torch.hub
# download) off the API import path — only paid the first time someone
# requests aug-vs-real.
_encoder: torch.nn.Module | None = None
_device: torch.device | None = None


def _get_encoder() -> tuple[torch.nn.Module, torch.device, str]:
    global _encoder, _device
    from foundation.encoder import (
        DEFAULT_ENCODER_VERSION,
        load_encoder,
        pick_device,
    )

    if _encoder is None:
        _device = pick_device()
        _encoder, _device = load_encoder(_device)
        logger.info("DINO encoder ready on %s (version=%s)", _device, DEFAULT_ENCODER_VERSION)
    return _encoder, _device, DEFAULT_ENCODER_VERSION


@dataclass
class _CoinPaths:
    eurio_id: str
    numista_id: int | None
    real_paths: list[Path]
    aug_paths: list[Path]


def _resolve_paths(eurio_id: str, iteration_id: str) -> _CoinPaths:
    nid = coin_lookup.numista_id_for(eurio_id)
    if nid is None:
        return _CoinPaths(eurio_id, None, [], [])
    captures_dir = DATASETS_DIR / str(nid) / "captures"
    aug_dir = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
    real = sorted(captures_dir.glob("*.jpg")) if captures_dir.is_dir() else []
    aug = sorted(aug_dir.glob("sample_*.jpg")) if aug_dir.is_dir() else []
    return _CoinPaths(eurio_id, nid, real, aug)


@torch.no_grad()
def _embed_paths(
    paths: list[Path],
    encoder: torch.nn.Module,
    device: torch.device,
    transform,
) -> np.ndarray | None:
    """Return an L2-normalized centroid (D,) or None if no images load."""
    tensors: list[torch.Tensor] = []
    for p in paths:
        try:
            with Image.open(p) as img:
                tensors.append(transform(img.convert("RGB")))
        except (OSError, ValueError) as exc:
            logger.warning("Skipping %s: %s", p, exc)
    if not tensors:
        return None
    batch = torch.stack(tensors).to(device)
    feats = encoder(batch)
    feats = F.normalize(feats, p=2, dim=1)
    centroid = feats.mean(dim=0)
    centroid = F.normalize(centroid, p=2, dim=0)
    return centroid.detach().cpu().float().numpy()


def compute_aug_vs_real(
    *,
    iteration_id: str,
    store: Store,
    force: bool = False,
) -> tuple[list[AugVsRealRow], str]:
    """Compute (or fetch from cache) per-coin DINO distance for an iteration.

    Returns ``(rows, dino_version)``. Rows are persisted in
    ``iteration_aug_vs_real`` with one entry per cohort coin that has at
    least one real capture *and* one augmentation sample. Coins missing
    either side are silently skipped — the caller can detect this via
    ``len(rows) < len(cohort.eurio_ids)``.
    """
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")

    from foundation.encoder import DEFAULT_ENCODER_VERSION

    if not force:
        cached = {r.eurio_id: r for r in store.list_aug_vs_real(iteration_id)}
        if cached:
            # Validate cache: dino_version + counts must match the on-disk
            # state. If anything drifted, fall through to recompute.
            valid = True
            expected: dict[str, _CoinPaths] = {
                eid: _resolve_paths(eid, iteration_id) for eid in cohort.eurio_ids
            }
            for eid, paths in expected.items():
                if not paths.real_paths or not paths.aug_paths:
                    continue
                row = cached.get(eid)
                if row is None:
                    valid = False
                    break
                if (
                    row.dino_version != DEFAULT_ENCODER_VERSION
                    or row.num_real != len(paths.real_paths)
                    or row.num_aug != len(paths.aug_paths)
                ):
                    valid = False
                    break
            if valid:
                return list(cached.values()), DEFAULT_ENCODER_VERSION

    encoder, device, version = _get_encoder()
    from foundation.encoder import build_transform
    transform = build_transform()

    rows: list[AugVsRealRow] = []
    for eurio_id in cohort.eurio_ids:
        paths = _resolve_paths(eurio_id, iteration_id)
        if not paths.real_paths or not paths.aug_paths:
            continue
        real_centroid = _embed_paths(paths.real_paths, encoder, device, transform)
        aug_centroid = _embed_paths(paths.aug_paths, encoder, device, transform)
        if real_centroid is None or aug_centroid is None:
            continue
        cosine = float(np.dot(real_centroid, aug_centroid))
        rows.append(
            AugVsRealRow(
                iteration_id=iteration_id,
                eurio_id=eurio_id,
                num_real=len(paths.real_paths),
                num_aug=len(paths.aug_paths),
                cosine=cosine,
                dino_version=version,
            )
        )

    if rows:
        store.upsert_aug_vs_real(rows)
        # Re-read so `computed_at` reflects the SQLite-side default.
        rows = store.list_aug_vs_real(iteration_id)
    return rows, version


def list_paths_for_iteration(
    *,
    iteration_id: str,
    store: Store,
) -> list[dict]:
    """Return per-coin (real_paths, aug_paths) for the side-by-side gallery.

    Paths are relative to ``ml/`` so the front can serve them via the
    static endpoints (``/datasets/<nid>/...``).
    """
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")
    out: list[dict] = []
    for eurio_id in cohort.eurio_ids:
        paths = _resolve_paths(eurio_id, iteration_id)
        out.append(
            {
                "eurio_id": eurio_id,
                "numista_id": paths.numista_id,
                "real_samples": [str(p.relative_to(ML_DIR)) for p in paths.real_paths],
                "aug_samples": [str(p.relative_to(ML_DIR)) for p in paths.aug_paths],
            }
        )
    return out


def summarize(rows: list[AugVsRealRow]) -> dict:
    if not rows:
        return {
            "num_coins": 0,
            "mean_cosine": None,
            "min_cosine": None,
            "max_cosine": None,
        }
    cosines = [r.cosine for r in rows]
    return {
        "num_coins": len(rows),
        "mean_cosine": float(sum(cosines) / len(cosines)),
        "min_cosine": float(min(cosines)),
        "max_cosine": float(max(cosines)),
    }
