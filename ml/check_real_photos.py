"""Validate the real-photo benchmark library + regenerate `_manifest.json`.

PRD Bloc 3 companion script. Scans ``ml/data/real_photos/<eurio_id>/*.{jpg,jpeg,png}``,
parses each filename against the 5-axis convention documented in
``docs/augmentation-benchmark/real-photo-criteria.md``, flags common
problems (resolution too low, orphan files, <2 sessions per coin, eurio_id
missing from the Supabase referential), and writes the aggregated manifest
used by the evaluator.

Usage:
    .venv/bin/python check_real_photos.py
    .venv/bin/python check_real_photos.py --strict    # exit 1 on any warning
    .venv/bin/python check_real_photos.py --root /path/to/photos
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from PIL import Image

ML_DIR = Path(__file__).parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.supabase_client import SupabaseClient, load_env  # noqa: E402
from real_photo_meta import parse_filename  # noqa: E402

logger = logging.getLogger("check_real_photos")

DEFAULT_ROOT = ML_DIR / "data" / "real_photos"
MIN_RESOLUTION = 800  # px, both width and height
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}
ENCODER_VERSION_PREFERRED = "dinov2-vits14"


@dataclass
class PhotoMeta:
    path: str  # repo-relative
    size_bytes: int
    width: int
    height: int
    lighting: str | None = None
    background: str | None = None
    angle: str | None = None
    session_key: str | None = None  # synthesized group key


@dataclass
class CoinCoverage:
    eurio_id: str
    zone: str | None
    photos: list[PhotoMeta] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fetch_zones(eurio_ids: list[str]) -> dict[str, str]:
    """Fetch zone per eurio_id from coin_confusion_map. Silent-fail if no env."""
    if not eurio_ids:
        return {}
    try:
        env = load_env()
    except Exception:  # noqa: BLE001
        return {}
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        logger.warning("Supabase env not available — zone coverage will be null")
        return {}

    sb = SupabaseClient(url, key)
    try:
        joined = ",".join(eurio_ids)
        rows = sb.query(
            "coin_confusion_map",
            select="eurio_id,zone,encoder_version",
            params={"eurio_id": f"in.({joined})"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase fetch failed (%s) — zones will be null", exc)
        return {}
    finally:
        sb.close()

    preferred: dict[str, str] = {}
    fallback: dict[str, str] = {}
    for row in rows:
        eid = row["eurio_id"]
        zone = row.get("zone")
        if zone is None:
            continue
        if row.get("encoder_version") == ENCODER_VERSION_PREFERRED:
            preferred[eid] = zone
        else:
            fallback.setdefault(eid, zone)
    return {**fallback, **preferred}


def _scan_coin_dir(
    coin_dir: Path, *, root: Path
) -> tuple[list[PhotoMeta], list[str]]:
    photos: list[PhotoMeta] = []
    warnings: list[str] = []
    for entry in sorted(coin_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in SUPPORTED_EXTS:
            warnings.append(f"Unsupported extension skipped: {entry.name}")
            continue
        try:
            with Image.open(entry) as im:
                w, h = im.size
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Cannot open {entry.name}: {exc}")
            continue
        if w < MIN_RESOLUTION or h < MIN_RESOLUTION:
            warnings.append(
                f"{entry.name}: resolution {w}×{h} below {MIN_RESOLUTION}px"
            )
        conditions = parse_filename(entry.stem)
        photos.append(
            PhotoMeta(
                path=str(entry.relative_to(root.parent)),
                size_bytes=entry.stat().st_size,
                width=w,
                height=h,
                lighting=conditions.lighting,
                background=conditions.background,
                angle=conditions.angle,
                session_key=conditions.session_key(),
            )
        )
    return photos, warnings


def scan_library(root: Path) -> tuple[list[CoinCoverage], dict]:
    if not root.exists():
        return [], {
            "root": str(root),
            "num_coins": 0,
            "num_photos": 0,
            "by_zone": {"green": 0, "orange": 0, "red": 0, "unknown": 0},
        }

    coin_dirs = [
        d for d in sorted(root.iterdir())
        if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("_")
    ]
    coin_ids = [d.name for d in coin_dirs]

    zones = _fetch_zones(coin_ids)

    coverages: list[CoinCoverage] = []
    by_zone = {"green": 0, "orange": 0, "red": 0, "unknown": 0}
    total_photos = 0

    for d in coin_dirs:
        photos, warnings = _scan_coin_dir(d, root=root)
        zone = zones.get(d.name)
        coverage = CoinCoverage(eurio_id=d.name, zone=zone, photos=photos, warnings=warnings)
        if not photos:
            coverage.warnings.append("No photos in folder")
        sessions = {p.session_key for p in photos if p.session_key}
        if photos and len(sessions) < 2:
            coverage.warnings.append(
                f"Only {len(sessions)} distinct session(s) — criteria.md requires ≥ 2"
            )
        coverages.append(coverage)
        total_photos += len(photos)
        by_zone[zone if zone in by_zone else "unknown"] += 1

    missing = [cid for cid in coin_ids if cid not in zones]
    if missing:
        logger.info(
            "%d eurio_id(s) with no zone in coin_confusion_map: %s",
            len(missing),
            ", ".join(missing),
        )

    summary = {
        "root": str(root),
        "num_coins": len(coverages),
        "num_photos": total_photos,
        "by_zone": by_zone,
    }
    return coverages, summary


def _write_manifest(coverages: list[CoinCoverage], summary: dict, root: Path) -> Path:
    manifest = {
        "summary": summary,
        "coins": [
            {
                "eurio_id": c.eurio_id,
                "zone": c.zone,
                "num_photos": len(c.photos),
                "num_sessions": len({p.session_key for p in c.photos if p.session_key}),
                "photos": [asdict(p) for p in c.photos],
                "warnings": c.warnings,
            }
            for c in coverages
        ],
    }
    path = root / "_manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    return path


def _format_coverage(coverages: list[CoinCoverage], summary: dict) -> Iterable[str]:
    yield f"Root:     {summary['root']}"
    yield f"Coins:    {summary['num_coins']}"
    yield f"Photos:   {summary['num_photos']}"
    zone_str = " · ".join(
        f"{k}={v}" for k, v in summary["by_zone"].items() if v > 0
    ) or "—"
    yield f"By zone:  {zone_str}"
    yield ""
    for c in coverages:
        zone_label = c.zone or "?"
        warn_tag = f"  ⚠ {len(c.warnings)}" if c.warnings else ""
        yield f"  [{zone_label}] {c.eurio_id}: {len(c.photos)} photos{warn_tag}"
        for w in c.warnings:
            yield f"      · {w}"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate ml/data/real_photos/ and rebuild _manifest.json",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=str(DEFAULT_ROOT),
        help="Root directory of the real-photo library.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any coin has warnings.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the summary as JSON instead of human-readable text.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(levelname)s %(name)s %(message)s",
    )

    root = Path(args.root).resolve()
    coverages, summary = scan_library(root)

    if coverages:
        manifest_path = _write_manifest(coverages, summary, root)
        logger.info("Manifest written: %s", manifest_path)
    else:
        if not root.exists():
            logger.warning("Real-photo root does not exist yet: %s", root)
        else:
            logger.warning("No coin folders under %s", root)

    if args.json:
        print(json.dumps(
            {
                "summary": summary,
                "coins": [
                    {
                        "eurio_id": c.eurio_id,
                        "zone": c.zone,
                        "num_photos": len(c.photos),
                        "num_sessions": len(
                            {p.session_key for p in c.photos if p.session_key}
                        ),
                        "warnings": c.warnings,
                    }
                    for c in coverages
                ],
            },
            indent=2,
        ))
    else:
        for line in _format_coverage(coverages, summary):
            print(line)

    if args.strict and any(c.warnings for c in coverages):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
