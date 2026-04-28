"""Download missing source images for the Numista review queue.

For each review queue entry with no local image, fetches type details from
the Numista API to get the image URLs, then downloads them.
Updates coin_catalog.json with the cached URLs.

Costs: 1 API call per missing entry (≤ 20 calls for the default 56-item queue).

Usage:
    cd ml && python -m referential.fetch_review_images
    cd ml && python -m referential.fetch_review_images --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from referential.numista_keys import KeyManager
from referential.import_numista import get_type_details, download_image, DATASETS_DIR

REVIEW_PATH  = DATASETS_DIR.parent / "datasets" / "numista_review_queue.json"
CATALOG_PATH = DATASETS_DIR.parent / "datasets" / "coin_catalog.json"

DELAY = 0.5


def has_image(numista_id: int) -> bool:
    d = DATASETS_DIR / str(numista_id)
    if not d.exists():
        return False
    return any(
        f.suffix.lower() in (".jpg", ".jpeg", ".png")
        for f in d.iterdir() if f.is_file()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    queue: list[dict] = json.loads(REVIEW_PATH.read_text())
    missing = [item for item in queue if not has_image(item["numista_id"])]

    print(f"Review queue: {len(queue)} items, {len(missing)} missing images")
    if not missing:
        print("All images present — nothing to do.")
        return 0

    if args.dry_run:
        for item in missing:
            print(f"  Would fetch: {item['numista_id']} {item['numista_name']}")
        return 0

    km = KeyManager()
    quota = km.status()
    remaining = sum(s["remaining"] for s in quota)
    print(f"Numista quota remaining: {remaining} calls")
    if remaining < len(missing):
        print(f"WARNING: only {remaining} calls left for {len(missing)} items")

    catalog = json.loads(CATALOG_PATH.read_text())
    catalog_coins: dict = catalog.get("coins", catalog)

    ok = 0
    failed = 0

    for i, item in enumerate(missing, 1):
        nid = item["numista_id"]
        print(f"[{i:2d}/{len(missing)}] #{nid} {item['numista_name'][:50]}", end="  ")

        try:
            data = km.call(get_type_details, nid)
        except Exception as exc:
            print(f"API error: {exc}")
            failed += 1
            continue

        obverse_url = (data.get("obverse") or {}).get("picture")
        reverse_url = (data.get("reverse") or {}).get("picture")

        if not obverse_url:
            print("no image URL from API")
            failed += 1
            time.sleep(DELAY)
            continue

        coin_dir = DATASETS_DIR / str(nid)
        coin_dir.mkdir(parents=True, exist_ok=True)

        got_obv = download_image(obverse_url, coin_dir / "obverse.jpg")
        got_rev = download_image(reverse_url, coin_dir / "reverse.jpg") if reverse_url else False

        # Cache URLs in catalog
        entry = catalog_coins.get(str(nid), {})
        entry["obverse_image_url"] = obverse_url
        if reverse_url:
            entry["reverse_image_url"] = reverse_url
        catalog_coins[str(nid)] = entry

        status = "✅" if got_obv else "⚠ obverse failed"
        print(f"{status} {'+ reverse' if got_rev else ''}")
        ok += 1 if got_obv else 0

        time.sleep(DELAY)

    # Save updated catalog
    catalog_out = catalog if "coins" in catalog else {"coins": catalog_coins}
    CATALOG_PATH.write_text(json.dumps(catalog_out, indent=2, ensure_ascii=False))

    print(f"\nDone: {ok} downloaded, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
