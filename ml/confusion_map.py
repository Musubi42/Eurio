"""Coin confusion cartography — DINOv2-based visual similarity mapping.

Phase 1 of the ML scalability plan (see docs/research/ml-scalability-phases/
phase-1-cartographie.md). For each coin in the catalogue with a Numista ID and
an obverse image, this script computes the pairwise cosine similarity matrix
using a frozen DINOv2 ViT-S/14 encoder, extracts the top-K nearest neighbors
(excluding coins sharing the same Numista design id — annual re-issues), and
classifies each coin into green/orange/red zones. Results are upserted into
the `coin_confusion_map` Supabase table.

Only the **obverse** (national side) is embedded. The reverse is the common
European side shared by all euro coins and would inflate inter-class similarity.

Usage:
    python confusion_map.py                               # full catalogue run
    python confusion_map.py --dry-run                     # no DB writes
    python confusion_map.py --limit 50                    # first 50 coins only
    python confusion_map.py --eurio-ids eu-fr-1euro-2002,eu-de-2euro-2002
    python confusion_map.py --thresholds green:0.70,red:0.85
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import httpx
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms
from tqdm import tqdm

ML_DIR = Path(__file__).parent
CACHE_DIR = ML_DIR / "cache"
IMAGE_CACHE_DIR = CACHE_DIR / "dinov2_inputs"

sys.path.insert(0, str(ML_DIR))
from api.supabase_client import SupabaseClient, load_env  # noqa: E402

logger = logging.getLogger("confusion_map")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_ENCODER_VERSION = "dinov2-vits14"
DINOV2_REPO = "facebookresearch/dinov2"
DINOV2_MODEL = "dinov2_vits14"

# DINOv2 was pretrained with ImageNet normalization and 14-multiple input sizes.
# 224 is divisible by 14 and matches the standard eval resolution.
INPUT_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

TOP_K = 5
BATCH_SIZE = 32

# Default zone thresholds. Override via --thresholds green:X,red:Y.
# green: nearest_similarity < green_max   (isolated design)
# orange: green_max <= nearest_similarity < red_min
# red:   nearest_similarity >= red_min    (quasi-twin)
ZONE_THRESHOLDS: dict[str, float] = {
    "green_max": 0.70,
    "red_min": 0.85,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CoinEntry:
    """One coin with metadata and its obverse image URL."""

    eurio_id: str
    numista_id: int | str
    obverse_url: str
    design_group_id: str | None = None


# ---------------------------------------------------------------------------
# Supabase fetching
# ---------------------------------------------------------------------------


def _extract_obverse_url(images: dict | list | None) -> str | None:
    """Extract the obverse URL from the coins.images payload (dict or legacy list)."""
    if not images:
        return None
    if isinstance(images, dict):
        return images.get("obverse") or images.get("obverse_url")
    if isinstance(images, list):
        match = next((i for i in images if i.get("role") == "obverse"), None)
        if match:
            return match.get("url")
    return None


def fetch_coins(
    sb: SupabaseClient,
    eurio_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[CoinEntry]:
    """Fetch coins that have a numista_id and an obverse image."""
    rows = sb.query(
        "coins",
        select="eurio_id,images,cross_refs,design_group_id",
        params={"cross_refs->numista_id": "not.is.null"},
    )

    coins: list[CoinEntry] = []
    for row in rows:
        nid = row.get("cross_refs", {}).get("numista_id")
        if nid is None:
            continue
        obverse = _extract_obverse_url(row.get("images"))
        if not obverse:
            continue
        coins.append(
            CoinEntry(
                eurio_id=row["eurio_id"],
                numista_id=nid,
                obverse_url=obverse,
                design_group_id=row.get("design_group_id"),
            )
        )

    if eurio_ids is not None:
        wanted = set(eurio_ids)
        coins = [c for c in coins if c.eurio_id in wanted]

    coins.sort(key=lambda c: c.eurio_id)

    if limit is not None:
        coins = coins[:limit]

    return coins


# ---------------------------------------------------------------------------
# Image cache + embedding
# ---------------------------------------------------------------------------


def _cache_path_for_url(url: str) -> Path:
    """Deterministic local path for a remote image URL."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    suffix = Path(url.split("?", 1)[0]).suffix.lower() or ".img"
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".img"
    return IMAGE_CACHE_DIR / f"{digest}{suffix}"


def _download_image(url: str, client: httpx.Client) -> Path | None:
    """Download (or reuse cached) image. Returns local path, or None on failure."""
    path = _cache_path_for_url(url)
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        resp = client.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def _build_transform() -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize(INPUT_SIZE, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(INPUT_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])


def _load_image_tensor(path: Path, transform: transforms.Compose) -> torch.Tensor | None:
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            return transform(img)
    except (OSError, ValueError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def pick_device() -> torch.device:
    """MPS on Apple Silicon, CPU otherwise. No CUDA (user is Mac-only)."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_encoder(device: torch.device) -> torch.nn.Module:
    """Load DINOv2 ViT-S/14 via torch.hub. First call downloads weights."""
    logger.info("Loading DINOv2 encoder (%s)…", DINOV2_MODEL)
    model = torch.hub.load(DINOV2_REPO, DINOV2_MODEL, pretrained=True)
    model.eval()
    model.to(device)
    return model


@torch.no_grad()
def embed_coins(
    coins: list[CoinEntry],
    encoder: torch.nn.Module,
    device: torch.device,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[str], np.ndarray]:
    """Embed each coin's obverse image.

    Returns:
        eurio_ids:  list[str] of length N (one entry per successfully embedded coin)
        matrix:     (N, D) float32 L2-normalized embeddings
    """
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    transform = _build_transform()

    eurio_ids: list[str] = []
    tensors: list[torch.Tensor] = []

    http_client = httpx.Client(timeout=30, follow_redirects=True)
    try:
        pbar = tqdm(total=len(coins), desc="Download+prep", unit="img")
        try:
            for coin in coins:
                path = _download_image(coin.obverse_url, http_client)
                if path is None:
                    pbar.update(1)
                    continue
                tensor = _load_image_tensor(path, transform)
                if tensor is None:
                    pbar.update(1)
                    continue
                eurio_ids.append(coin.eurio_id)
                tensors.append(tensor)
                pbar.update(1)
        finally:
            pbar.close()
    finally:
        http_client.close()

    if not tensors:
        return [], np.zeros((0, 0), dtype=np.float32)

    embeddings: list[np.ndarray] = []
    batches = range(0, len(tensors), BATCH_SIZE)
    for start in tqdm(batches, desc="DINOv2 embed", unit="batch"):
        batch = torch.stack(tensors[start : start + BATCH_SIZE]).to(device)
        feats = encoder(batch)
        feats = F.normalize(feats, p=2, dim=1)
        embeddings.append(feats.detach().cpu().float().numpy())
        if on_progress is not None:
            on_progress(min(start + BATCH_SIZE, len(tensors)), len(tensors))

    matrix = np.concatenate(embeddings, axis=0).astype(np.float32)
    return eurio_ids, matrix


# ---------------------------------------------------------------------------
# Embedding cache
# ---------------------------------------------------------------------------


def _embedding_cache_path(encoder_version: str) -> Path:
    return CACHE_DIR / f"dinov2_embeddings_{encoder_version}.npz"


def save_embedding_cache(
    encoder_version: str,
    eurio_ids: list[str],
    urls: list[str],
    matrix: np.ndarray,
) -> None:
    """Persist embeddings to npz for reuse across runs."""
    path = _embedding_cache_path(encoder_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        eurio_ids=np.array(eurio_ids, dtype=object),
        urls=np.array(urls, dtype=object),
        vecs=matrix,
    )
    logger.info("Saved %d embeddings to %s", matrix.shape[0], path)


# ---------------------------------------------------------------------------
# Similarity + zoning
# ---------------------------------------------------------------------------


def zone_for_similarity(sim: float, thresholds: dict[str, float]) -> str:
    if sim >= thresholds["red_min"]:
        return "red"
    if sim >= thresholds["green_max"]:
        return "orange"
    return "green"


def compute_pairwise_neighbors(
    coins: list[CoinEntry],
    eurio_ids: list[str],
    matrix: np.ndarray,
    thresholds: dict[str, float],
) -> list[dict]:
    """For each coin, compute its cosine similarity to every other coin,
    filter out same-design neighbors (shared design_group_id, with fallback
    on numista_id when the group is not yet populated), and return one row
    per coin ready for upsert."""
    if matrix.shape[0] < 2:
        if matrix.shape[0] > 0:
            logger.warning("Fewer than 2 coins embedded — nothing to compare.")
        return []

    eurio_to_numista = {c.eurio_id: str(c.numista_id) for c in coins}
    eurio_to_group = {c.eurio_id: c.design_group_id for c in coins}
    eurio_to_obverse = {c.eurio_id: c.obverse_url for c in coins}
    index_by_eid = {eid: i for i, eid in enumerate(eurio_ids)}

    # Full similarity matrix (N, N). With ~500 coins this is 250K floats, trivial.
    sim = matrix @ matrix.T

    rows: list[dict] = []
    for eid_a in eurio_ids:
        i_a = index_by_eid[eid_a]
        nid_a = eurio_to_numista[eid_a]
        gid_a = eurio_to_group[eid_a]

        candidates: list[tuple[str, float]] = []
        for eid_b in eurio_ids:
            if eid_b == eid_a:
                continue
            # Same design → not a real collision. Prefer design_group_id (covers
            # both intra-country re-issues axis A AND cross-country joint issues
            # axis B). Fall back to numista_id when design_group is NULL (pre-
            # bootstrap coins), which keeps the legacy behavior for axis A.
            gid_b = eurio_to_group[eid_b]
            if gid_a is not None and gid_b is not None:
                if gid_a == gid_b:
                    continue
            elif eurio_to_numista[eid_b] == nid_a:
                continue
            i_b = index_by_eid[eid_b]
            candidates.append((eid_b, float(sim[i_a, i_b])))

        if not candidates:
            continue

        candidates.sort(key=lambda t: t[1], reverse=True)
        top_k = candidates[:TOP_K]

        nearest_eid, nearest_sim = top_k[0]
        zone = zone_for_similarity(nearest_sim, thresholds)

        neighbors_json = [
            {
                "eurio_id": neighbor_eid,
                "similarity": round(s, 6),
                "obverse_url": eurio_to_obverse.get(neighbor_eid),
            }
            for neighbor_eid, s in top_k
        ]

        rows.append(
            {
                "eurio_id": eid_a,
                "nearest_eurio_id": nearest_eid,
                "nearest_similarity": round(nearest_sim, 6),
                "top_k_neighbors": neighbors_json,
                "zone": zone,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def parse_thresholds(raw: str | None) -> dict[str, float]:
    """Parse 'green:0.70,red:0.85' into {green_max, red_min}."""
    if not raw:
        return dict(ZONE_THRESHOLDS)
    out = dict(ZONE_THRESHOLDS)
    for chunk in raw.split(","):
        key, _, val = chunk.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if not key or not val:
            raise ValueError(f"Invalid threshold clause: {chunk!r}")
        if key == "green":
            out["green_max"] = float(val)
        elif key == "red":
            out["red_min"] = float(val)
        else:
            raise ValueError(f"Unknown threshold key: {key!r}")
    if out["green_max"] >= out["red_min"]:
        raise ValueError(
            f"green threshold ({out['green_max']}) must be < red threshold ({out['red_min']})"
        )
    return out


def parse_eurio_ids(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def _write_status(status_path: Path | None, **fields: object) -> None:
    """Atomically dump progress JSON for the FastAPI poller."""
    if status_path is None:
        return
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), **fields}
    status_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(status_path)


def run(
    *,
    dry_run: bool,
    eurio_ids: list[str] | None,
    limit: int | None,
    encoder_version: str,
    thresholds: dict[str, float],
    status_path: Path | None = None,
) -> dict:
    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from environment"
        )

    sb = SupabaseClient(url, key)
    try:
        logger.info("Fetching coins from Supabase…")
        _write_status(status_path, stage="fetching", current=0, total=0)
        coins = fetch_coins(sb, eurio_ids=eurio_ids, limit=limit)
        logger.info("Fetched %d candidate coins with obverse image", len(coins))
        if len(coins) < 2:
            logger.warning("Need at least 2 coins to compute confusion — aborting")
            _write_status(
                status_path, stage="done", current=0, total=0, rows=0
            )
            return {"rows": 0, "coins": len(coins)}

        device = pick_device()
        logger.info("Using device: %s", device)

        encoder = load_encoder(device)

        _write_status(
            status_path,
            stage="embedding",
            current=0,
            total=len(coins),
            rows=0,
        )

        def _on_progress(current: int, total: int) -> None:
            _write_status(
                status_path,
                stage="embedding",
                current=current,
                total=total,
                rows=0,
            )

        eurio_ids_out, matrix = embed_coins(
            coins, encoder, device, on_progress=_on_progress
        )
        logger.info("Embedded %d coins (matrix shape: %s)", len(eurio_ids_out), matrix.shape)

        if matrix.shape[0] >= 1:
            url_by_eid = {c.eurio_id: c.obverse_url for c in coins}
            urls_flat = [url_by_eid.get(eid, "") for eid in eurio_ids_out]
            save_embedding_cache(encoder_version, eurio_ids_out, urls_flat, matrix)

        _write_status(
            status_path,
            stage="matrix",
            current=0,
            total=len(coins),
            rows=0,
        )
        rows = compute_pairwise_neighbors(
            coins, eurio_ids_out, matrix, thresholds
        )
        logger.info("Computed %d confusion rows", len(rows))

        zone_counts: dict[str, int] = {"green": 0, "orange": 0, "red": 0}
        for r in rows:
            zone_counts[r["zone"]] = zone_counts.get(r["zone"], 0) + 1
        logger.info(
            "Zones: green=%d orange=%d red=%d",
            zone_counts["green"], zone_counts["orange"], zone_counts["red"],
        )

        if dry_run:
            logger.info("--dry-run: skipping Supabase upsert")
            sample = rows[:5]
            for r in sample:
                logger.info(
                    "  %s → %s @ sim=%.4f [%s]",
                    r["eurio_id"],
                    r["nearest_eurio_id"],
                    r["nearest_similarity"],
                    r["zone"],
                )
            _write_status(
                status_path,
                stage="done",
                current=len(rows),
                total=len(rows),
                rows=len(rows),
                dry_run=True,
            )
            return {"rows": len(rows), "coins": len(coins), "zones": zone_counts}

        _write_status(
            status_path,
            stage="writing",
            current=0,
            total=len(rows),
            rows=0,
        )
        payload = [
            {
                **r,
                "encoder_version": encoder_version,
                "computed_at": datetime.now(timezone.utc).isoformat(),
            }
            for r in rows
        ]
        sb.upsert(
            "coin_confusion_map",
            payload,
            on_conflict="eurio_id,encoder_version",
        )
        logger.info("Upserted %d rows into coin_confusion_map", len(rows))

        _write_status(
            status_path,
            stage="done",
            current=len(rows),
            total=len(rows),
            rows=len(rows),
        )
        return {"rows": len(rows), "coins": len(coins), "zones": zone_counts}
    finally:
        sb.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate the coin confusion map via DINOv2."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be written without touching Supabase.",
    )
    p.add_argument(
        "--eurio-ids",
        type=str,
        default=None,
        help="Comma-separated list of eurio_id values to restrict the cartography to.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only cartograph the first N coins (sorted by eurio_id).",
    )
    p.add_argument(
        "--encoder-version",
        type=str,
        default=DEFAULT_ENCODER_VERSION,
        help=f"Encoder version tag written to DB (default: {DEFAULT_ENCODER_VERSION}).",
    )
    p.add_argument(
        "--thresholds",
        type=str,
        default=None,
        help="Override zone thresholds, e.g. 'green:0.70,red:0.85'.",
    )
    p.add_argument(
        "--status-file",
        type=str,
        default=None,
        help="Optional JSON status file updated during the run (for FastAPI polling).",
    )
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING).",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    thresholds = parse_thresholds(args.thresholds)
    eurio_ids = parse_eurio_ids(args.eurio_ids)
    status_path = Path(args.status_file) if args.status_file else None

    result = run(
        dry_run=args.dry_run,
        eurio_ids=eurio_ids,
        limit=args.limit,
        encoder_version=args.encoder_version,
        thresholds=thresholds,
        status_path=status_path,
    )
    logger.info("Done: %s", json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
