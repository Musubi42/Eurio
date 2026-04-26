"""Generate a preview grid of augmented images for a single design.

Phase 2 of the ML scalability plan (see
``docs/research/ml-scalability-phases/phase-2-augmentation.md``). The CLI
resolves a ``design_group_id`` or ``eurio_id`` to a canonical obverse image,
looks up its zone from ``coin_confusion_map`` (falling back to ``orange`` if
unknown), runs the corresponding recipe, and writes a grid PNG.

Usage:
    .venv/bin/python preview_augmentations.py --eurio-id ad-2014-2eur-standard
    .venv/bin/python preview_augmentations.py --design-group-id be-2euro-albert-ii-ef1
    .venv/bin/python preview_augmentations.py --eurio-id ... --zone red --count 16
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import httpx
from PIL import Image

ML_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ML_DIR))

from api.supabase_client import SupabaseClient, load_env  # noqa: E402
from augmentations.pipeline import AugmentationPipeline  # noqa: E402
from augmentations.recipes import DEFAULT_RECIPE, ZONE_RECIPES  # noqa: E402
from state import Store  # noqa: E402

logger = logging.getLogger("preview_augmentations")

CACHE_DIR = ML_DIR / "cache" / "augmentation_sources"
OUTPUT_DIR = ML_DIR / "output" / "augmentation_previews"
ENCODER_VERSION_PREFERRED = "dinov2-vits14"


# ---------------------------------------------------------------------------
# Supabase lookups
# ---------------------------------------------------------------------------


def _extract_obverse_url(images: dict | list | None) -> str | None:
    if not images:
        return None
    if isinstance(images, dict):
        return images.get("obverse") or images.get("obverse_url")
    if isinstance(images, list):
        match = next((i for i in images if i.get("role") == "obverse"), None)
        if match:
            return match.get("url")
    return None


def _fetch_design_group(sb: SupabaseClient, group_id: str) -> dict | None:
    rows = sb.query(
        "design_groups",
        select="id,designation,shared_obverse_url",
        params={"id": f"eq.{group_id}"},
    )
    return rows[0] if rows else None


def _fetch_coins(
    sb: SupabaseClient,
    *,
    eurio_id: str | None = None,
    design_group_id: str | None = None,
) -> list[dict]:
    params: dict[str, str] = {}
    if eurio_id is not None:
        params["eurio_id"] = f"eq.{eurio_id}"
    if design_group_id is not None:
        params["design_group_id"] = f"eq.{design_group_id}"
    return sb.query(
        "coins",
        select="eurio_id,year,country,images,design_group_id",
        params=params,
    )


def _fetch_zone(sb: SupabaseClient, eurio_ids: list[str]) -> dict[str, str]:
    if not eurio_ids:
        return {}
    joined = ",".join(eurio_ids)
    rows = sb.query(
        "coin_confusion_map",
        select="eurio_id,zone,encoder_version",
        params={"eurio_id": f"in.({joined})"},
    )
    preferred: dict[str, str] = {}
    fallback: dict[str, str] = {}
    for row in rows:
        eid = row["eurio_id"]
        zone = row["zone"]
        if row.get("encoder_version") == ENCODER_VERSION_PREFERRED:
            preferred[eid] = zone
        else:
            fallback.setdefault(eid, zone)
    return {**fallback, **preferred}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


_ZONE_SEVERITY = {"green": 0, "orange": 1, "red": 2}


def _resolve_source(
    sb: SupabaseClient,
    *,
    eurio_id: str | None,
    design_group_id: str | None,
) -> tuple[str, str, str]:
    """Return (label, obverse_url, zone) for the request.

    ``label`` is the filename stem (design_group_id or eurio_id).
    """
    if eurio_id:
        coins = _fetch_coins(sb, eurio_id=eurio_id)
        if not coins:
            raise SystemExit(f"No coin found with eurio_id={eurio_id!r}")
        coin = coins[0]
        url = _extract_obverse_url(coin.get("images"))
        if not url:
            raise SystemExit(f"Coin {eurio_id} has no obverse image")
        zone_map = _fetch_zone(sb, [eurio_id])
        zone = zone_map.get(eurio_id, "orange")
        return eurio_id, url, zone

    assert design_group_id is not None
    group = _fetch_design_group(sb, design_group_id)
    if group is None:
        raise SystemExit(f"No design_group found with id={design_group_id!r}")

    members = _fetch_coins(sb, design_group_id=design_group_id)
    if not members:
        raise SystemExit(f"design_group {design_group_id} has no members")

    url = group.get("shared_obverse_url")
    if not url:
        # Fall back to the oldest member (min year), then alphabetical.
        members_sorted = sorted(
            members,
            key=lambda m: (m.get("year") or 9999, m["eurio_id"]),
        )
        for m in members_sorted:
            candidate = _extract_obverse_url(m.get("images"))
            if candidate:
                url = candidate
                break
    if not url:
        raise SystemExit(
            f"No obverse image available for design_group {design_group_id}"
        )

    zone_map = _fetch_zone(sb, [m["eurio_id"] for m in members])
    zones = {m["eurio_id"]: zone_map.get(m["eurio_id"]) for m in members}
    resolved = [z for z in zones.values() if z is not None]
    if not resolved:
        zone = "orange"
    else:
        if len(set(resolved)) > 1:
            logger.warning(
                "Zone divergence within design_group %s: %s — taking the most severe",
                design_group_id,
                zones,
            )
        zone = max(resolved, key=lambda z: _ZONE_SEVERITY.get(z, -1))

    return design_group_id, url, zone


# ---------------------------------------------------------------------------
# Image download + grid
# ---------------------------------------------------------------------------


def _cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    suffix = Path(url.split("?", 1)[0]).suffix.lower() or ".img"
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".img"
    return CACHE_DIR / f"{digest}{suffix}"


def _download_image(url: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path_for_url(url)
    if path.exists() and path.stat().st_size > 0:
        return path
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def _build_grid(
    images: Iterable[Image.Image],
    tile_size: int = 256,
    padding: int = 8,
    background: tuple[int, int, int] = (245, 245, 245),
) -> Image.Image:
    tiles = [img.resize((tile_size, tile_size), Image.LANCZOS) for img in images]
    n = len(tiles)
    cols = int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols))
    width = cols * tile_size + (cols + 1) * padding
    height = rows * tile_size + (rows + 1) * padding
    grid = Image.new("RGB", (width, height), background)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        x = padding + c * (tile_size + padding)
        y = padding + r * (tile_size + padding)
        grid.paste(tile, (x, y))
    return grid


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate a preview grid of augmented images for a coin design."
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--design-group-id", type=str, help="design_groups.id")
    group.add_argument("--eurio-id", type=str, help="coins.eurio_id")
    p.add_argument(
        "--zone",
        type=str,
        default=None,
        choices=sorted(ZONE_RECIPES.keys()),
        help="Override the zone resolved from coin_confusion_map.",
    )
    p.add_argument(
        "--recipe",
        type=str,
        default=None,
        help="Id or name of a recipe stored in state/training.db. "
             "When set, --zone is ignored.",
    )
    p.add_argument(
        "--count",
        type=int,
        default=16,
        help="Number of variations in the grid (default 16 = 4×4).",
    )
    p.add_argument(
        "--output",
        type=str,
        default=str(OUTPUT_DIR),
        help="Output directory for the grid PNG.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for reproducibility.",
    )
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")

    sb = SupabaseClient(url, key)
    try:
        label, obverse_url, resolved_zone = _resolve_source(
            sb,
            eurio_id=args.eurio_id,
            design_group_id=args.design_group_id,
        )
    finally:
        sb.close()

    if args.recipe:
        store = Store(ML_DIR / "state" / "training.db")
        row = store.get_recipe(args.recipe)
        if row is None:
            raise SystemExit(f"Recipe {args.recipe!r} not found in state/training.db")
        recipe = row.config
        zone = row.zone or (args.zone or resolved_zone)
        logger.info(
            "Label=%s recipe=%s (id=%s zone=%s) count=%d",
            label, row.name, row.id, zone, args.count,
        )
    else:
        zone = args.zone or resolved_zone
        recipe = ZONE_RECIPES.get(zone, DEFAULT_RECIPE)
        logger.info("Label=%s zone=%s (resolved=%s) count=%d", label, zone, resolved_zone, args.count)

    logger.info("Fetching obverse image: %s", obverse_url)
    source_path = _download_image(obverse_url)
    base_img = Image.open(source_path).convert("RGB")

    pipeline = AugmentationPipeline(recipe, seed=args.seed)
    variations = pipeline.generate(base_img, count=args.count)

    grid = _build_grid(variations)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = label.replace("/", "_")
    out_path = output_dir / f"{safe_label}_{zone}_{timestamp}.png"
    grid.save(out_path, "PNG")
    logger.info("Wrote grid: %s", out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
