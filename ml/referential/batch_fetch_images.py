"""Batch-fetch images from Numista for all coins with numista_id but no images.

Queries Supabase for unique numista_ids needing images, then for each:
  1. GET /types/{id} from Numista API (extracts image URLs)
  2. Downloads obverse + reverse from Numista CDN
  3. Resizes to 400px (detail) + 120px (thumb) WebP via Pillow
  4. Uploads to Supabase Storage (coin-images bucket)
  5. Patches coins.images JSONB for all eurio_ids sharing that numista_id

Usage:
    python ml/batch_fetch_images.py                # Fetch all pending
    python ml/batch_fetch_images.py --limit 50     # Process max 50 types
    python ml/batch_fetch_images.py --dry-run      # Preview without fetching
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import date
from typing import Any

import httpx

from referential.eurio_referential import load_referential, save_referential
from referential.import_numista import get_type_details
from export.sync_to_supabase import load_env

IMAGE_SIZES = {"detail": 400, "thumb": 120}
WEBP_QUALITY = {"detail": 82, "thumb": 78}
BUCKET_NAME = "coin-images"
API_DELAY = 0.5
CDN_DELAY = 0.3


def get_pending_numista_ids(supabase_url: str, key: str) -> list[int]:
    """Query Supabase for unique numista_ids that need images."""
    base = supabase_url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    # Fetch all coins with numista_id
    all_ids: set[int] = set()
    has_images: set[int] = set()
    offset = 0
    page_size = 1000

    with httpx.Client(headers=headers, timeout=60) as client:
        while True:
            resp = client.get(
                f"{base}/coins",
                params={
                    "select": "cross_refs,images",
                    "cross_refs->>numista_id": "not.is.null",
                },
                headers={"Range": f"{offset}-{offset + page_size - 1}"},
            )
            rows = resp.json()
            if not rows:
                break
            for row in rows:
                cr = row.get("cross_refs") or {}
                nid = cr.get("numista_id")
                if nid is None:
                    continue
                nid = int(nid)
                all_ids.add(nid)
                img = row.get("images")
                if img and isinstance(img, dict) and "obverse" in img and "supabase" in str(img.get("obverse", "")):
                    has_images.add(nid)
            if len(rows) < page_size:
                break
            offset += page_size

    return sorted(all_ids - has_images)


def download_image(url: str) -> bytes | None:
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
    except httpx.HTTPError:
        pass
    return None


def resize_to_webp(raw: bytes, width: int, quality: int) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    ratio = width / img.width
    img = img.resize((width, round(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def upload_to_storage(client: httpx.Client, base_url: str, path: str, data: bytes) -> bool:
    resp = client.post(
        f"{base_url}/storage/v1/object/{BUCKET_NAME}/{path}",
        content=data,
        headers={"Content-Type": "image/webp", "x-upsert": "true"},
    )
    return resp.status_code < 400


def process_type(
    numista_id: int,
    api_key: str,
    storage_client: httpx.Client,
    supabase_url: str,
) -> dict[str, str] | None:
    """Fetch, resize, upload images for one Numista type. Returns images dict or None."""
    # 1. Get image URLs from API
    try:
        details = get_type_details(api_key, numista_id)
    except httpx.HTTPError as e:
        print(f"  API error: {e}")
        return None
    time.sleep(API_DELAY)

    obverse_url = details.get("obverse", {}).get("picture")
    reverse_url = details.get("reverse", {}).get("picture")

    if not obverse_url and not reverse_url:
        return None

    public_base = f"{supabase_url}/storage/v1/object/public/{BUCKET_NAME}"
    images: dict[str, str] = {}

    for face, src_url in [("obverse", obverse_url), ("reverse", reverse_url)]:
        if not src_url:
            continue
        raw = download_image(src_url)
        if not raw:
            continue
        time.sleep(CDN_DELAY)

        for label, width in IMAGE_SIZES.items():
            webp = resize_to_webp(raw, width, WEBP_QUALITY[label])
            path = f"{numista_id}/{face}-{width}.webp"
            ok = upload_to_storage(storage_client, supabase_url, path, webp)
            if not ok:
                continue
            url_key = face if label == "detail" else f"{face}_thumb"
            images[url_key] = f"{public_base}/{numista_id}/{face}-{width}.webp"

    return images if images else None


def patch_coins_images(
    rest_client: httpx.Client,
    rest_base: str,
    numista_id: int,
    images: dict[str, str],
) -> int:
    """Patch images for all coins with this numista_id. Returns count patched."""
    resp = rest_client.get(
        f"{rest_base}/coins",
        params={
            "select": "eurio_id",
            "cross_refs->>numista_id": f"eq.{numista_id}",
        },
    )
    rows = resp.json()
    patched = 0
    for row in rows:
        eid = row["eurio_id"]
        r = rest_client.patch(
            f"{rest_base}/coins",
            params={"eurio_id": f"eq.{eid}"},
            json={"images": images},
        )
        if r.status_code < 400:
            patched += 1
    return patched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max types to process (0 = all)")
    args = parser.parse_args()

    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    api_key = env.get("NUMISTA_API_KEY", "")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY required")
        return 2
    if not api_key:
        print("ERROR: NUMISTA_API_KEY required")
        return 2

    print("Finding types needing images...")
    pending = get_pending_numista_ids(supabase_url, supabase_key)
    print(f"  {len(pending)} types need images")

    if args.limit:
        pending = pending[: args.limit]
        print(f"  Limited to {len(pending)}")

    if not pending:
        print("Nothing to do.")
        return 0

    print(f"  API calls needed: {len(pending)} (GET /types/{{id}})")
    print(f"  Image downloads: ~{len(pending) * 2}")

    if args.dry_run:
        print("\n--dry-run: not fetching.")
        return 0

    # Also update referential
    referential = load_referential()

    storage_headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }
    rest_headers = {
        **storage_headers,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    processed = 0
    failed = 0
    coins_patched = 0
    today = date.today().isoformat()

    with (
        httpx.Client(headers=storage_headers, timeout=30) as storage_client,
        httpx.Client(headers=rest_headers, timeout=60) as rest_client,
    ):
        for i, nid in enumerate(pending):
            print(f"\n[{i + 1}/{len(pending)}] Numista {nid} ...", end=" ", flush=True)

            images = process_type(nid, api_key, storage_client, supabase_url)
            if not images:
                print("SKIP (no images)")
                failed += 1
                continue

            n = patch_coins_images(rest_client, rest_base, nid, images)
            coins_patched += n
            processed += 1
            print(f"OK ({len(images)} urls, {n} coins patched)")

            # Update referential too
            for eid, entry in referential.items():
                cr = entry.get("cross_refs", {})
                if cr.get("numista_id") == nid:
                    entry["images"] = images
                    entry["provenance"]["last_updated"] = today

    print(f"\n\nDone!")
    print(f"  Types processed: {processed}")
    print(f"  Types failed:    {failed}")
    print(f"  Coins patched:   {coins_patched}")

    print("\nSaving referential...")
    save_referential(referential)
    print("  Done.")

    print("\nRun 'go-task android:snapshot' to regenerate the snapshot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
