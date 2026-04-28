"""Download BCE coin images and upload them to Supabase Storage — Phase 2C.8.4.

Always fetch the BCE image when an `observations.bce_comm.image_url` exists,
even when a Numista image is already present — both sources coexist in the
new per-eurio_id storage layout. Storage paths:

    coin-images/{eurio_id}/obverse_bce.webp
    coin-images/{eurio_id}/obverse_bce_thumb.webp

The detail keeps the BCE source's native resolution (typically 270-540px,
varies by year). The thumb is downscaled to 120px for the admin grid.

Usage:
    python ml/referential/fetch_bce_images.py             # all entries with a BCE obs
    python ml/referential/fetch_bce_images.py --limit 20
    python ml/referential/fetch_bce_images.py --dry-run
    python ml/referential/fetch_bce_images.py --no-supabase
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date

import httpx

from referential.eurio_referential import load_referential, save_referential
from referential.coin_image_storage import (
    BUCKET_NAME,
    ImageVariant,
    merge_variant,
    storage_key,
    upload_variant,
)
from export.sync_to_supabase import load_env
from state.sources_runs import record_run

CDN_DELAY = 0.3
USER_AGENT = "Eurio/0.1 bce-image-fetcher (https://github.com/Musubi42/eurio)"


def find_pending(referential: dict[str, dict]) -> list[tuple[str, str]]:
    """Return [(eurio_id, bce_image_url)] for every entry with a BCE observation."""
    pending: list[tuple[str, str]] = []
    for eurio_id, entry in referential.items():
        bce = (entry.get("observations") or {}).get("bce_comm") or {}
        url = bce.get("image_url")
        if isinstance(url, str) and url:
            pending.append((eurio_id, url))
    return pending


def already_uploaded(client: httpx.Client, supabase_url: str, key: str) -> bool:
    """Check whether the BCE detail already exists in Storage. HEAD = no egress."""
    resp = client.head(
        f"{supabase_url}/storage/v1/object/public/{BUCKET_NAME}/{key}",
        timeout=10,
    )
    return resp.status_code == 200


def download_jpg(url: str) -> bytes | None:
    try:
        resp = httpx.get(
            url,
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as e:
        print(f"    download error: {e}")
        return None
    if resp.status_code != 200 or len(resp.content) < 1000:
        print(f"    bad response: HTTP {resp.status_code}, {len(resp.content)} bytes")
        return None
    return resp.content


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-supabase", action="store_true")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-upload even if the BCE webp is already in Storage",
    )
    args = ap.parse_args()

    referential = load_referential()
    pending = find_pending(referential)
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"BCE images candidates: {len(pending)}")
    if not pending:
        print("Nothing to do.")
        return 0

    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    skip_supabase = args.no_supabase or not (supabase_url and supabase_key)
    if skip_supabase and not args.no_supabase:
        print("WARNING: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing — skipping uploads")

    today = date.today().isoformat()
    storage_headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }
    rest_headers = {**storage_headers, "Content-Type": "application/json", "Prefer": "return=minimal"}
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    uploaded = 0
    skipped = 0
    patched = 0
    failed = 0

    with httpx.Client(headers=storage_headers, timeout=60) as storage_client, \
         httpx.Client(headers=rest_headers, timeout=60) as rest_client:

        for eurio_id, src_url in pending:
            print(f"\n  {eurio_id}")
            detail_key = storage_key(eurio_id, "obverse", "bce_comm")

            if not args.force and not skip_supabase:
                if already_uploaded(storage_client, supabase_url, detail_key):
                    print("    ✓ already in storage (use --force to re-upload)")
                    skipped += 1
                    continue

            print(f"    src: {src_url}")
            if args.dry_run:
                print("    (dry-run) would upload + patch")
                continue

            data = download_jpg(src_url)
            if not data:
                failed += 1
                continue
            print(f"    downloaded {len(data) // 1024} KB", end="")

            variant: ImageVariant | None = None
            if not skip_supabase:
                variant = upload_variant(
                    storage_client, supabase_url,
                    eurio_id, "obverse", "bce_comm",
                    data,
                    detail_max_width=None,  # BCE source is already small — no downscale
                )
                if variant is None:
                    print()
                    failed += 1
                    continue
                uploaded += 1
                print(f" → detail {variant['width']}×{variant['height']} "
                      f"({variant['bytes'] // 1024} KB) + thumb")

            entry = referential[eurio_id]
            if variant is not None:
                entry["images"] = merge_variant(entry.get("images") or {}, "obverse", variant)
                entry.setdefault("provenance", {})["last_updated"] = today

            if not skip_supabase and variant is not None:
                resp = rest_client.patch(
                    f"{rest_base}/coins",
                    params={"eurio_id": f"eq.{eurio_id}"},
                    json={"images": entry["images"]},
                )
                if resp.status_code < 400:
                    patched += 1
                else:
                    print(f"    patch FAIL: HTTP {resp.status_code} {resp.text[:200]}")

            time.sleep(CDN_DELAY)

    if not args.dry_run:
        save_referential(referential)
        print(f"\nDone. uploaded={uploaded}  skipped={skipped}  patched={patched}  failed={failed}")
        record_run("bce_images", "fetch", calls=uploaded, added_coins=patched)
    return 0


if __name__ == "__main__":
    sys.exit(main())
