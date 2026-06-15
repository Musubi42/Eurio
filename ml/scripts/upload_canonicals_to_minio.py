"""Upload canonical images from ``ml/canonical_images/`` to MinIO ``numista-canonical``.

Scans ``ml/canonical_images/**/*.webp`` and uploads each file with key =
relative path from ``ml/canonical_images/``, e.g.
``es-2012-2eur-burgos-cathedral/obverse_bce.webp``.

Idempotent: files already present in the bucket are skipped (HEAD check).
JSON sidecars (``.json``) are intentionally excluded — only ``.webp`` files.

Usage::

    .venv/bin/python -m scripts.upload_canonicals_to_minio [--dry-run] [--limit N] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
CANONICAL_IMAGES_DIR = ML_DIR / "canonical_images"
BUCKET = "numista-canonical"
CACHE_CONTROL = "public, max-age=604800, immutable"

logger = logging.getLogger(__name__)


def _existing_keys(client) -> set[str]:
    """Return the full set of object keys currently in BUCKET.

    We list the whole bucket once (paginated) instead of a per-file HEAD/LIST:
    much fewer round-trips for a bulk upload, and it bypasses the Cloudflare CDN
    cache that can return stale 403/404 for HEAD on the public
    ``numista-canonical`` bucket (which would yield false existence negatives).
    """
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without uploading.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Stop after uploading (or considering, in dry-run) N files.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output (skipped files, per-file status).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    # Verbose only affects our own logger; boto3/botocore stay at WARNING.
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger("botocore").setLevel(logging.WARNING)
        logging.getLogger("boto3").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    if not CANONICAL_IMAGES_DIR.is_dir():
        logger.error("canonical_images dir not found: %s", CANONICAL_IMAGES_DIR)
        return 2

    webp_files = sorted(CANONICAL_IMAGES_DIR.rglob("*.webp"))
    total_found = len(webp_files)
    logger.info("Found %d .webp files in %s", total_found, CANONICAL_IMAGES_DIR.relative_to(ML_DIR.parent))

    if args.dry_run:
        limit = args.limit or total_found
        shown = webp_files[:limit]
        for f in shown:
            key = f.relative_to(CANONICAL_IMAGES_DIR).as_posix()
            print(f"  {key}")
        print(f"\ndry-run: {total_found} .webp total, would process up to {limit}")
        return 0

    # Real upload path
    from shared.storage import _client  # noqa: PLC0415

    client = _client()
    existing = _existing_keys(client)
    logger.info("%d objects already in %s", len(existing), BUCKET)

    uploaded = 0
    skipped = 0
    failed = 0

    candidates = webp_files if args.limit is None else webp_files[: args.limit]

    for path in candidates:
        key = path.relative_to(CANONICAL_IMAGES_DIR).as_posix()
        try:
            if key in existing:
                logger.debug("SKIP  %s (already in bucket)", key)
                skipped += 1
                continue

            data = path.read_bytes()
            client.put_object(
                Bucket=BUCKET,
                Key=key,
                Body=data,
                ContentType="image/webp",
                Metadata={"Cache-Control": CACHE_CONTROL},
                CacheControl=CACHE_CONTROL,
            )
            logger.info("UP    %s (%d bytes)", key, len(data))
            uploaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("FAIL  %s — %s", key, exc)
            failed += 1

    print(
        f"\nDone: {uploaded} uploaded, {skipped} skipped, {failed} failed"
        f"  (total scanned: {len(candidates)} / {total_found} found)"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
