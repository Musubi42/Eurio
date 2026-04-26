"""Fetch a single eBay item to inspect multi-variation listings."""

import json
import sys
from pathlib import Path

import httpx

from tests.test_ebay import get_app_token, load_env

ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/{item_id}"


def get_item(token: str, item_id: str) -> dict:
    resp = httpx.get(
        ITEM_URL.format(item_id=item_id),
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"getItem failed: HTTP {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    return resp.json()


def main() -> None:
    env = load_env()
    token = get_app_token(env["EBAY_CLIENT_ID"], env["EBAY_CLIENT_SECRET"])
    item_id = sys.argv[1] if len(sys.argv) > 1 else "v1|358153628831|626546714266"
    print(f"Fetching {item_id}\n")

    data = get_item(token, item_id)

    print("Top-level keys:")
    for k in data.keys():
        print(f"  - {k}")
    print()

    for key in ("title", "price", "condition", "conditionId", "estimatedAvailabilities"):
        if key in data:
            print(f"{key}: {data[key]}")
    print()

    # Multi-variation indicators
    for key in ("hasMultipleVariations", "priceDisplayCondition"):
        if key in data:
            print(f"{key}: {data[key]}")

    for key in ("localizedAspects", "itemAspects"):
        if key in data:
            print(f"\n{key}:")
            print(json.dumps(data[key], indent=2, ensure_ascii=False)[:2000])

    dump_path = Path(__file__).parent.parent / "output" / f"ebay_item_{item_id.replace('|', '_')}.json"
    dump_path.parent.mkdir(exist_ok=True)
    dump_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nFull response saved to {dump_path}")


if __name__ == "__main__":
    main()
