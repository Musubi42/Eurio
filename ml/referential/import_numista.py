"""Import all 2€ euro coin types from Numista API v3.

Fetches coin metadata + images for all eurozone countries.
Updates coin_catalog.json and downloads images into datasets/{numista_id}/.

Usage:
    .venv/bin/python import_numista.py                     # Fetch all 2€ coins (uses API quota)
    .venv/bin/python import_numista.py --dry-run            # Preview without downloading
    .venv/bin/python import_numista.py --retry-images       # Re-download failed images (NO API calls)
    .venv/bin/python import_numista.py --retry-delay 3      # Slower retry if CDN rate-limits
    .venv/bin/python import_numista.py --backfill-urls      # Cache image URLs for old entries (uses API quota)

Rate limits:
    - Numista free plan: ~2000 API calls/month (search + get_type combined)
    - Image CDN (en.numista.com): separate rate limit, ~1 req/s seems safe
    - --retry-images does NOT use API quota (URLs are cached in coin_catalog.json)
"""

import argparse
import json
import time
from pathlib import Path

import httpx

from referential.numista_keys import KeyManager

CATALOG_PATH = Path(__file__).parent.parent / "datasets" / "coin_catalog.json"
DATASETS_DIR = Path(__file__).parent.parent / "datasets"

API_BASE = "https://api.numista.com/v3"
DELAY_BETWEEN_CALLS = 0.5  # seconds — be respectful to Numista


def search_types(api_key: str, query: str = "2 euros", page: int = 1) -> dict:
    """Search Numista for coin types."""
    resp = httpx.get(
        f"{API_BASE}/types",
        params={
            "q": query,
            "category": "coin",
            "count": 50,
            "page": page,
            "lang": "en",
        },
        headers={"Numista-API-Key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_type_details(api_key: str, type_id: int) -> dict:
    """Fetch full details for a coin type."""
    resp = httpx.get(
        f"{API_BASE}/types/{type_id}",
        headers={"Numista-API-Key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def download_image(url: str, dest: Path, max_retries: int = 3) -> bool:
    """Download an image to disk with retry/backoff. Returns True on success."""
    if dest.exists():
        return True  # Already downloaded
    for attempt in range(max_retries):
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                return True
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = (attempt + 1) * 2
                print(f"      HTTP {resp.status_code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            return False  # 4xx other than 429
        except httpx.HTTPError as e:
            wait = (attempt + 1) * 2
            print(f"      Network error, retrying in {wait}s... ({e})")
            time.sleep(wait)
    return False


def extract_coin_data(data: dict) -> dict | None:
    """Extract structured coin data from Numista API response.

    Returns None if this isn't a 2€ coin.
    """
    # Filter: must be exactly 2€
    value = data.get("value", {})
    numeric = value.get("numeric_value") if value else None
    currency_name = value.get("currency", {}).get("name", "") if value else ""

    if numeric != 2 or "euro" not in currency_name.lower():
        return None

    issuer = data.get("issuer", {})
    country = issuer.get("name", "Unknown")

    # Determine type
    coin_type = "circulation"
    if data.get("commemorated_topic"):
        coin_type = "commemorative"
    elif "commemorative" in data.get("title", "").lower():
        coin_type = "commemorative"

    obverse = data.get("obverse", {})
    reverse = data.get("reverse", {})

    return {
        "numista_id": data["id"],
        "name": data.get("title", f"2 Euro #{data['id']}"),
        "country": country,
        "year": data.get("min_year"),
        "face_value": 2.0,
        "type": coin_type,
        "diameter_mm": data.get("size"),
        "weight_g": data.get("weight"),
        "composition": data.get("composition", {}).get("text") if data.get("composition") else None,
        "obverse_description": obverse.get("description"),
        "reverse_description": reverse.get("description"),
        "obverse_image_url": obverse.get("picture"),
        "reverse_image_url": reverse.get("picture"),
    }


def is_complete(str_id: str, catalog: dict) -> bool:
    """Return True only when metadata AND both images are present."""
    if str_id not in catalog["coins"]:
        return False
    coin_dir = DATASETS_DIR / str_id
    return (coin_dir / "obverse.jpg").exists() and (coin_dir / "reverse.jpg").exists()


def load_catalog() -> dict:
    """Load existing catalog or create a fresh one."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            data = json.load(f)
        # Migrate: if old format (coins keyed by directory name), keep description/instructions
        return data
    return {
        "description": "Source of truth mapping Numista IDs to coin metadata and local image paths.",
        "coins": {},
    }


def save_catalog(catalog: dict) -> None:
    with open(CATALOG_PATH, "w") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"\nCatalog saved: {CATALOG_PATH} ({len(catalog['coins'])} coins)")


def import_all(km: KeyManager, catalog: dict, dry_run: bool = False) -> int:
    """Import all 2€ coins via global search. Returns count of new coins added."""
    added = 0
    skipped = 0
    filtered = 0
    page = 1

    # First, get total count
    try:
        first_result = km.call(search_types, query="2 euros", page=1)
        total_count = first_result.get("count", 0)
        print(f"  Search returned {total_count} results to scan")
    except (httpx.HTTPError, RuntimeError) as e:
        print(f"  Search error: {e}")
        return 0

    while True:
        time.sleep(DELAY_BETWEEN_CALLS)
        try:
            result = km.call(search_types, query="2 euros", page=page)
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"  Search error page {page}: {e}")
            break

        types_list = result.get("types", [])
        if not types_list:
            break

        for t in types_list:
            type_id = t.get("id")
            str_id = str(type_id)
            title = t.get("title", "")

            # Quick pre-filter: skip results that clearly aren't 2€ coins
            if not title.startswith("2 Euro"):
                filtered += 1
                continue

            # Skip "2 Euro Cents"
            if "Cent" in title:
                filtered += 1
                continue

            # Already fully scraped (catalog + both images) — nothing to do
            if is_complete(str_id, catalog):
                skipped += 1
                continue

            # In catalog but images missing — retry CDN without burning API quota
            if str_id in catalog["coins"]:
                cached = catalog["coins"][str_id]
                coin_dir = DATASETS_DIR / str_id
                coin_dir.mkdir(parents=True, exist_ok=True)
                name = cached.get("name", str_id)
                missing_ob = not (coin_dir / "obverse.jpg").exists()
                missing_rv = not (coin_dir / "reverse.jpg").exists()
                if missing_ob and cached.get("obverse_image_url"):
                    ok = download_image(cached["obverse_image_url"], coin_dir / "obverse.jpg")
                    print(f"    ~ {name} — obverse retry {'OK' if ok else 'FAILED'}")
                if missing_rv and cached.get("reverse_image_url"):
                    ok = download_image(cached["reverse_image_url"], coin_dir / "reverse.jpg")
                    print(f"    ~ {name} — reverse retry {'OK' if ok else 'FAILED'}")
                skipped += 1
                continue

            # Not in catalog — fetch metadata from API then download images
            time.sleep(DELAY_BETWEEN_CALLS)
            try:
                details = km.call(get_type_details, type_id)
            except (httpx.HTTPError, RuntimeError) as e:
                print(f"    Error fetching type {type_id}: {e}")
                continue

            coin_data = extract_coin_data(details)
            if coin_data is None:
                filtered += 1
                continue  # Not a 2€ coin

            if dry_run:
                print(f"    [DRY RUN] {coin_data['name']} | {coin_data['country']} ({coin_data['year']})")
                added += 1
                continue

            # Download images
            coin_dir = DATASETS_DIR / str_id
            coin_dir.mkdir(parents=True, exist_ok=True)

            if coin_data["obverse_image_url"]:
                ok = download_image(coin_data["obverse_image_url"], coin_dir / "obverse.jpg")
                if ok:
                    print(f"    + {coin_data['name']} | {coin_data['country']} ({coin_data['year']})")
                else:
                    print(f"    + {coin_data['name']} — obverse FAILED")

            if coin_data["reverse_image_url"]:
                ok = download_image(coin_data["reverse_image_url"], coin_dir / "reverse.jpg")
                if not ok:
                    print(f"      reverse FAILED")

            # Add to catalog (including image URLs for offline retry)
            catalog["coins"][str_id] = {
                "numista_id": coin_data["numista_id"],
                "name": coin_data["name"],
                "country": coin_data["country"],
                "year": coin_data["year"],
                "face_value": coin_data["face_value"],
                "type": coin_data["type"],
                "diameter_mm": coin_data["diameter_mm"],
                "weight_g": coin_data["weight_g"],
                "composition": coin_data["composition"],
                "obverse_description": coin_data["obverse_description"],
                "reverse_description": coin_data["reverse_description"],
                "obverse_image_url": coin_data["obverse_image_url"],
                "reverse_image_url": coin_data["reverse_image_url"],
            }
            added += 1

            # Save every 20 coins (resume-safe)
            if added % 20 == 0:
                save_catalog(catalog)
                print(f"  --- Progress: {added} added, page {page} ---")

        # Check pagination
        if page * 50 >= total_count:
            break
        page += 1
        print(f"  Page {page} (scanned {page * 50}/{total_count}, added {added}, skipped {skipped}, filtered {filtered})")

    print(f"\n  Summary: {added} added, {skipped} already in catalog, {filtered} filtered out")
    return added


def retry_missing_images(catalog: dict, delay: float = 1.0) -> int:
    """Re-download missing images using URLs cached in coin_catalog.json.

    This does NOT call the Numista API — it uses the image URLs stored
    in the catalog from the initial import. Only hits the Numista CDN
    (en.numista.com) to download the actual image files.
    """
    coins = catalog.get("coins", {})
    retried = 0
    failed = 0
    skipped_no_url = 0
    already_ok = 0

    missing = []
    for str_id, coin in coins.items():
        coin_dir = DATASETS_DIR / str_id
        obverse_exists = (coin_dir / "obverse.jpg").exists()
        reverse_exists = (coin_dir / "reverse.jpg").exists()

        if obverse_exists and reverse_exists:
            already_ok += 1
            continue

        obverse_url = coin.get("obverse_image_url")
        reverse_url = coin.get("reverse_image_url")

        if not obverse_url and not reverse_url:
            skipped_no_url += 1
            continue

        missing.append((str_id, coin, obverse_exists, reverse_exists, obverse_url, reverse_url))

    print(f"  {already_ok} coins OK, {len(missing)} missing images, {skipped_no_url} without cached URLs")
    print(f"  Downloading with {delay}s delay between images...\n")

    for i, (str_id, coin, obverse_exists, reverse_exists, obverse_url, reverse_url) in enumerate(missing):
        coin_dir = DATASETS_DIR / str_id
        coin_dir.mkdir(parents=True, exist_ok=True)

        if not obverse_exists and obverse_url:
            time.sleep(delay)
            ok = download_image(obverse_url, coin_dir / "obverse.jpg")
            if ok:
                print(f"  [{i+1}/{len(missing)}] {coin['name']} — obverse OK")
                retried += 1
            else:
                print(f"  [{i+1}/{len(missing)}] {coin['name']} — obverse FAILED")
                failed += 1

        if not reverse_exists and reverse_url:
            time.sleep(delay)
            ok = download_image(reverse_url, coin_dir / "reverse.jpg")
            if ok:
                retried += 1
            else:
                failed += 1

    print(f"\nRetry complete: {retried} images recovered, {failed} still failed")
    return retried


def backfill_urls(km: KeyManager, catalog: dict) -> int:
    """Fetch image URLs from API for catalog entries that don't have them cached.

    This uses API quota (get_type_details). Run only when you have quota available.
    """
    coins = catalog.get("coins", {})
    updated = 0

    entries_without_urls = [
        (str_id, coin) for str_id, coin in coins.items()
        if not coin.get("obverse_image_url")
    ]

    print(f"  {len(entries_without_urls)} entries missing cached URLs")

    for i, (str_id, coin) in enumerate(entries_without_urls):
        time.sleep(DELAY_BETWEEN_CALLS)
        try:
            details = km.call(get_type_details, int(str_id))
        except RuntimeError as e:
            print(f"  All keys exhausted: {e}")
            break
        except httpx.HTTPError as e:
            print(f"  [{i+1}/{len(entries_without_urls)}] {str_id}: API error — {e}")
            continue

        obverse = details.get("obverse", {})
        reverse = details.get("reverse", {})

        coin["obverse_image_url"] = obverse.get("picture")
        coin["reverse_image_url"] = reverse.get("picture")
        updated += 1

        if updated % 20 == 0:
            save_catalog(catalog)
            print(f"  --- Progress: {updated}/{len(entries_without_urls)} URLs cached ---")

    print(f"\n  Backfilled {updated} URLs")
    return updated


def main():
    parser = argparse.ArgumentParser(description="Import 2€ coins from Numista API")
    parser.add_argument("--dry-run", action="store_true", help="Preview without downloading")
    parser.add_argument("--retry-images", action="store_true", help="Re-download missing images (no API calls)")
    parser.add_argument("--retry-delay", type=float, default=1.0, help="Delay between image downloads in retry mode")
    parser.add_argument("--backfill-urls", action="store_true", help="Fetch missing image URLs from API (uses quota)")
    parser.add_argument("--status", action="store_true", help="Show API key quota status for current month")
    args = parser.parse_args()

    try:
        km = KeyManager()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return

    if args.status:
        print(f"\n{'='*60}")
        print(f"  NUMISTA KEY STATUS")
        print(f"{'='*60}")
        for s in km.status():
            flag = " [EXHAUSTED]" if s["exhausted"] else ""
            print(f"  Slot {s['slot']} ({s['key_hash']}): {s['calls_this_month']} calls, {s['remaining']} remaining{flag}")
        print(f"{'='*60}")
        return

    catalog = load_catalog()

    # Migrate old catalog format: re-key by numista_id
    old_coins = catalog.get("coins", {})
    new_coins = {}
    for key, value in old_coins.items():
        numista_id = str(value.get("numista_id", key))
        if numista_id != key and not key.isdigit():
            print(f"  Migrating: {key} → {numista_id}")
            new_coins[numista_id] = value
        else:
            new_coins[key] = value
    catalog["coins"] = new_coins
    catalog["description"] = "Source of truth mapping Numista IDs to coin metadata and local image paths."
    catalog.pop("instructions", None)

    if args.backfill_urls:
        print(f"\n{'='*60}")
        print(f"  BACKFILLING IMAGE URLs ({len(catalog['coins'])} coins in catalog)")
        print(f"  WARNING: This uses Numista API quota (get_type_details)")
        print(f"{'='*60}")
        backfill_urls(km, catalog)
        save_catalog(catalog)
        return

    if args.retry_images:
        print(f"\n{'='*60}")
        print(f"  RETRYING MISSING IMAGES — NO API CALLS (uses cached URLs)")
        print(f"{'='*60}")
        retry_missing_images(catalog, delay=args.retry_delay)
        return

    print(f"\n{'='*60}")
    print(f"  IMPORTING ALL 2€ COINS FROM NUMISTA")
    print(f"  Already in catalog: {len(catalog['coins'])} coins")
    print(f"{'='*60}")

    total_added = import_all(km, catalog, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"  TOTAL: {total_added} new coins added")
    print(f"  Catalog: {len(catalog['coins'])} coins total")
    print(f"{'='*60}")

    if not args.dry_run:
        save_catalog(catalog)


if __name__ == "__main__":
    main()
