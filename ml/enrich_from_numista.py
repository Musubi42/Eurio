"""Enrich the Eurio referential with Numista type IDs and images.

Adds "numista_id" to the cross_refs dict of matching coins in
eurio_referential.json, then optionally patches Supabase directly.

With --images, also fetches official coin photos from Numista API,
resizes them (400px detail + 120px thumbnail as WebP), uploads to
Supabase Storage, and updates the images JSONB column.

Usage:
    python ml/enrich_from_numista.py              # Enrich numista_id only
    python ml/enrich_from_numista.py --images     # + fetch/resize/upload images
    python ml/enrich_from_numista.py --dry-run    # Preview without writing
    python ml/enrich_from_numista.py --no-supabase # Referential only, skip Supabase
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from eurio_referential import load_referential, save_referential
from import_numista import get_type_details
from numista_keys import KeyManager
from sync_to_supabase import load_env

# ---------------------------------------------------------------------------
# Hardcoded mapping: Numista type ID -> matching criteria
#
# For standard coins, one Numista type covers a design era (multiple years).
# For commemoratives, we match by eurio_id directly to avoid ambiguity.
# ---------------------------------------------------------------------------

NUMISTA_MAPPING: list[dict[str, Any]] = [
    {
        "numista_id": 87,
        "description": "1 Euro Spain - Juan Carlos I",
        "country": "ES",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 1999,
        "max_year": 2014,
    },
    {
        "numista_id": 111,
        "description": "1 Euro Germany - Eagle",
        "country": "DE",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 2002,
        "max_year": None,  # same design all years
    },
    {
        "numista_id": 135,
        "description": "1 Euro Italy - Vitruvian Man",
        "country": "IT",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 2002,
        "max_year": None,  # same design all years
    },
    {
        "numista_id": 159,
        "description": "1 Euro Portugal - Royal Seal (old design)",
        "country": "PT",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 2002,
        "max_year": 2007,  # Portugal changed design in 2008
    },
    {
        # Commemorative: match by eurio_id to avoid ambiguity
        # (Germany has 2 commémo 2EUR in 2020: Kniefall + Sanssouci)
        "numista_id": 226447,
        "description": "2 Euro Germany 2020 - Kniefall von Warschau",
        "eurio_id": "de-2020-2eur-50-years-since-the-kniefall-von-warschau",
    },
]

IMAGE_SIZES = {
    "detail": 400,
    "thumb": 120,
}
WEBP_QUALITY = {"detail": 82, "thumb": 78}
BUCKET_NAME = "coin-images"
NUMISTA_CDN_DELAY = 0.5  # seconds between image downloads


def find_matching_entries(
    referential: dict[str, dict[str, Any]],
    mapping: dict[str, Any],
) -> list[str]:
    """Return eurio_ids matching a Numista type mapping entry."""
    # Direct eurio_id match (for commemoratives)
    if "eurio_id" in mapping:
        eid = mapping["eurio_id"]
        return [eid] if eid in referential else []

    # Range match for standard coins
    matches = []
    for eurio_id, entry in referential.items():
        ident = entry.get("identity", {})
        if ident.get("country") != mapping["country"]:
            continue
        if ident.get("face_value") != mapping["face_value"]:
            continue
        if bool(ident.get("is_commemorative")) != mapping["is_commemorative"]:
            continue
        year = ident.get("year")
        if year is None:
            continue
        if mapping.get("min_year") and year < mapping["min_year"]:
            continue
        if mapping.get("max_year") and year > mapping["max_year"]:
            continue
        matches.append(eurio_id)
    return sorted(matches)


def enrich_referential(
    referential: dict[str, dict[str, Any]],
) -> tuple[int, list[tuple[str, int]]]:
    """Add numista_id to cross_refs for all matching entries.

    Returns (total_enriched, list of (eurio_id, numista_id) pairs).
    """
    today = date.today().isoformat()
    enriched: list[tuple[str, int]] = []

    for mapping in NUMISTA_MAPPING:
        numista_id = mapping["numista_id"]
        matched = find_matching_entries(referential, mapping)

        if not matched:
            print(f"  WARNING: no match for Numista {numista_id} ({mapping['description']})")
            continue

        for eurio_id in matched:
            entry = referential[eurio_id]
            if "cross_refs" not in entry:
                entry["cross_refs"] = {}
            entry["cross_refs"]["numista_id"] = numista_id
            entry["provenance"]["last_updated"] = today
            enriched.append((eurio_id, numista_id))

        print(f"  Numista {numista_id:>6} -> {len(matched):>2} coins  ({mapping['description']})")

    return len(enriched), enriched


# ---------------------------------------------------------------------------
# Image pipeline: fetch from Numista → resize → WebP → upload to Storage
# ---------------------------------------------------------------------------


def fetch_numista_image_urls(km: KeyManager) -> dict[int, dict[str, str]]:
    """Fetch obverse/reverse image URLs from Numista API for each mapped type.

    Returns {numista_id: {"obverse": url, "reverse": url}}.
    Uses 1 API call per type (5 total for current mapping).
    """
    urls: dict[int, dict[str, str]] = {}
    for mapping in NUMISTA_MAPPING:
        nid = mapping["numista_id"]
        print(f"  GET /types/{nid} ...", end=" ", flush=True)
        try:
            details = km.call(get_type_details, nid)
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"FAIL ({e})")
            continue

        obverse_url = details.get("obverse", {}).get("picture")
        reverse_url = details.get("reverse", {}).get("picture")
        urls[nid] = {}
        if obverse_url:
            urls[nid]["obverse"] = obverse_url
        if reverse_url:
            urls[nid]["reverse"] = reverse_url
        print(f"OK (obverse={'yes' if obverse_url else 'no'}, reverse={'yes' if reverse_url else 'no'})")
        time.sleep(0.5)  # respect Numista API rate limit

    return urls


def download_image(url: str) -> bytes | None:
    """Download a single image from Numista CDN."""
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
        print(f"    bad response: HTTP {resp.status_code}, {len(resp.content)} bytes")
    except httpx.HTTPError as e:
        print(f"    download error: {e}")
    return None


def resize_to_webp(raw_bytes: bytes, target_width: int, quality: int) -> bytes:
    """Resize image to target width (preserving aspect ratio) and encode as WebP."""
    from PIL import Image

    img = Image.open(io.BytesIO(raw_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    ratio = target_width / img.width
    target_height = round(img.height * ratio)
    img = img.resize((target_width, target_height), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def upload_to_storage(
    client: httpx.Client,
    base_url: str,
    path: str,
    data: bytes,
) -> bool:
    """Upload a file to Supabase Storage. Returns True on success."""
    resp = client.post(
        f"{base_url}/storage/v1/object/{BUCKET_NAME}/{path}",
        content=data,
        headers={
            "Content-Type": "image/webp",
            "x-upsert": "true",
        },
    )
    if resp.status_code >= 400:
        print(f"    upload FAIL {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return False
    return True


def process_images(
    image_urls: dict[int, dict[str, str]],
    enriched: list[tuple[str, int]],
    referential: dict[str, dict[str, Any]],
    dry_run: bool = False,
    skip_supabase: bool = False,
) -> None:
    """Download, resize, upload images and update DB + referential."""
    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not dry_run and not skip_supabase and (not supabase_url or not supabase_key):
        print("  WARNING: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found, skipping upload")
        skip_supabase = True

    public_base = f"{supabase_url}/storage/v1/object/public/{BUCKET_NAME}"
    today = date.today().isoformat()

    # Build image URLs map: numista_id -> images dict for the DB
    images_by_numista: dict[int, dict[str, str]] = {}
    uploaded = 0
    skipped = 0

    storage_headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }

    with httpx.Client(headers=storage_headers, timeout=30) as storage_client:
        for nid, face_urls in image_urls.items():
            print(f"\n  Processing Numista {nid}:")
            nid_images: dict[str, str] = {}

            for face in ("obverse", "reverse"):
                src_url = face_urls.get(face)
                if not src_url:
                    print(f"    {face}: no URL, skipping")
                    continue

                print(f"    {face}: downloading ...", end=" ", flush=True)
                if dry_run:
                    print("(dry-run skip)")
                    nid_images[face] = f"{public_base}/{nid}/{face}-400.webp"
                    nid_images[f"{face}_thumb"] = f"{public_base}/{nid}/{face}-120.webp"
                    continue

                raw = download_image(src_url)
                if not raw:
                    continue
                print(f"{len(raw) // 1024} KB")

                for label, width in IMAGE_SIZES.items():
                    quality = WEBP_QUALITY[label]
                    suffix = str(width)
                    webp_data = resize_to_webp(raw, width, quality)
                    storage_path = f"{nid}/{face}-{suffix}.webp"
                    print(f"      {face}-{suffix}.webp: {len(webp_data) // 1024} KB", end="")

                    if skip_supabase:
                        print(" (skip upload)")
                    else:
                        ok = upload_to_storage(storage_client, supabase_url, storage_path, webp_data)
                        if ok:
                            uploaded += 1
                            print(" -> uploaded")
                        else:
                            skipped += 1

                    url_key = face if label == "detail" else f"{face}_thumb"
                    nid_images[url_key] = f"{public_base}/{nid}/{face}-{suffix}.webp"

                time.sleep(NUMISTA_CDN_DELAY)

            if nid_images:
                images_by_numista[nid] = nid_images

    if not dry_run:
        print(f"\n  Storage: {uploaded} uploaded, {skipped} failed")

    # Update referential and Supabase coins.images
    print("\n  Updating images in referential + Supabase...")
    patched = 0
    rest_headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    with httpx.Client(headers=rest_headers, timeout=60) as rest_client:
        for eurio_id, nid in enriched:
            nid_images = images_by_numista.get(nid)
            if not nid_images:
                continue

            # Update referential
            referential[eurio_id]["images"] = nid_images
            referential[eurio_id]["provenance"]["last_updated"] = today

            if dry_run or skip_supabase:
                patched += 1
                continue

            # Patch Supabase
            resp = rest_client.patch(
                f"{rest_base}/coins",
                params={"eurio_id": f"eq.{eurio_id}"},
                json={"images": nid_images},
            )
            if resp.status_code < 400:
                patched += 1
            else:
                print(f"    FAIL {eurio_id}: HTTP {resp.status_code}")

    action = "would patch" if dry_run else "patched"
    print(f"  {action} images for {patched} coins")


# ---------------------------------------------------------------------------
# Supabase cross_refs update (existing)
# ---------------------------------------------------------------------------


def update_supabase_cross_refs(
    enriched: list[tuple[str, int]], referential: dict[str, dict[str, Any]]
) -> None:
    """Patch cross_refs in Supabase for enriched coins."""
    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("  SKIP Supabase: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found in .env")
        return

    base = url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    patched = 0
    errors = 0
    with httpx.Client(headers=headers, timeout=60) as client:
        for eurio_id, _ in enriched:
            cross_refs = referential[eurio_id].get("cross_refs", {})
            resp = client.patch(
                f"{base}/coins",
                params={"eurio_id": f"eq.{eurio_id}"},
                json={"cross_refs": cross_refs},
            )
            if resp.status_code >= 400:
                print(f"    FAIL {eurio_id}: HTTP {resp.status_code} {resp.text[:200]}")
                errors += 1
            else:
                patched += 1

    print(f"  Supabase: patched {patched} coins" + (f", {errors} errors" if errors else ""))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--no-supabase", action="store_true", help="Skip Supabase updates")
    parser.add_argument("--images", action="store_true", help="Fetch, resize & upload coin images")
    args = parser.parse_args()

    env = load_env()

    print("Loading referential...")
    referential = load_referential()
    print(f"  {len(referential)} entries loaded")

    print("\nMatching Numista IDs:")
    total, enriched = enrich_referential(referential)
    print(f"\n  Total: {total} coins enriched with numista_id")

    if not enriched:
        print("Nothing to do.")
        return 0

    # --- Image pipeline ---
    if args.images:
        try:
            km = KeyManager()
        except RuntimeError as e:
            print(f"\nERROR: {e}")
            return 2

        print("\nFetching image URLs from Numista API (5 calls)...")
        image_urls = fetch_numista_image_urls(km)
        print(f"  Got URLs for {len(image_urls)} types")

        print("\nProcessing images (download → resize → upload)...")
        process_images(
            image_urls,
            enriched,
            referential,
            dry_run=args.dry_run,
            skip_supabase=args.no_supabase,
        )

    # --- Save referential ---
    if args.dry_run:
        print("\n--dry-run: not writing anything.")
        return 0

    print("\nSaving referential...")
    save_referential(referential)
    print("  Done.")

    # --- Patch Supabase cross_refs ---
    if not args.no_supabase:
        print("\nUpdating Supabase cross_refs...")
        update_supabase_cross_refs(enriched, referential)

    print("\nNext steps:")
    print("  go-task android:snapshot   # regenerate catalog_snapshot.json")
    print("  go-task android:build      # rebuild APK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
