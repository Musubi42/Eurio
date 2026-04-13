"""Aggregate eBay Browse API search results to measure usable price data volume.

Strategy:
  1. Paginated search on a broad query (euro commemorative category).
  2. For each result, detect multi-variation listings via primaryItemGroup.
  3. Expand unique item groups via get_items_by_item_group (deduped).
  4. Report: listings vs. groups, total variations, sold distribution, price stats.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median

import httpx

from test_ebay import get_app_token, load_env

SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
GROUP_URL = "https://api.ebay.com/buy/browse/v1/item/get_items_by_item_group"
CATEGORY_EURO_COINS = "32650"  # "Pièces euro"


def search_page(token: str, query: str, offset: int, limit: int = 50) -> dict:
    resp = httpx.get(
        SEARCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
        },
        params={
            "q": query,
            "category_ids": CATEGORY_EURO_COINS,
            "limit": limit,
            "offset": offset,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_group(token: str, group_id: str) -> dict:
    resp = httpx.get(
        GROUP_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
        },
        params={"item_group_id": group_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def extract_variation_row(item: dict) -> dict:
    availabilities = item.get("estimatedAvailabilities") or [{}]
    avail = availabilities[0]
    aspects = {a["name"]: a["value"] for a in item.get("localizedAspects", []) if "name" in a}
    price = item.get("price") or {}
    return {
        "itemId": item.get("itemId"),
        "price": float(price["value"]) if price.get("value") else None,
        "currency": price.get("currency"),
        "sold": avail.get("estimatedSoldQuantity", 0),
        "available": avail.get("estimatedAvailableQuantity", 0),
        "origin": item.get("itemOriginDate"),
        "seller": (item.get("seller") or {}).get("username"),
        "aspects": aspects,
    }


def aggregate(token: str, query: str, total_items: int = 200) -> dict:
    page_size = 50
    seen_groups: dict[str, dict] = {}
    simple_listings: list[dict] = []
    api_calls = 0

    # Paginated search
    for offset in range(0, total_items, page_size):
        page = search_page(token, query, offset, page_size)
        api_calls += 1
        summaries = page.get("itemSummaries") or []
        print(f"  search offset={offset} → {len(summaries)} items (total available: {page.get('total')})")
        if not summaries:
            break
        for it in summaries:
            pig = it.get("primaryItemGroup")
            if pig and pig.get("itemGroupId"):
                gid = pig["itemGroupId"]
                if gid not in seen_groups:
                    seen_groups[gid] = {"title": pig.get("itemGroupTitle"), "variations": None}
            else:
                simple_listings.append(extract_variation_row(it))
        if len(summaries) < page_size:
            break

    # Expand groups
    print(f"\nExpanding {len(seen_groups)} unique item groups...")
    for i, (gid, meta) in enumerate(seen_groups.items(), 1):
        try:
            data = fetch_group(token, gid)
            api_calls += 1
            variations = [extract_variation_row(it) for it in (data.get("items") or [])]
            meta["variations"] = variations
            print(f"  [{i}/{len(seen_groups)}] {gid} → {len(variations)} variations")
        except httpx.HTTPError as e:
            print(f"  [{i}/{len(seen_groups)}] {gid} → FAILED: {e}")
            meta["variations"] = []

    # Flatten
    all_rows = list(simple_listings)
    for meta in seen_groups.values():
        all_rows.extend(meta["variations"] or [])

    return {
        "query": query,
        "api_calls": api_calls,
        "simple_listings": simple_listings,
        "groups": seen_groups,
        "all_rows": all_rows,
    }


def report(agg: dict) -> None:
    rows = agg["all_rows"]
    simple = agg["simple_listings"]
    groups = agg["groups"]

    prices = [r["price"] for r in rows if r["price"] is not None]
    sold_counts = [r["sold"] for r in rows]
    with_sales = [r for r in rows if r["sold"] > 0]

    print("\n" + "=" * 60)
    print(f"REPORT — query={agg['query']!r}")
    print("=" * 60)
    print(f"API calls used:           {agg['api_calls']}")
    print(f"Simple listings:          {len(simple)}")
    print(f"Multi-variation groups:   {len(groups)}")
    print(f"Total variations:         {sum(len(g['variations'] or []) for g in groups.values())}")
    print(f"Total data rows:          {len(rows)}")
    print()
    if prices:
        prices_sorted = sorted(prices)
        n = len(prices_sorted)
        print("PRICE DISTRIBUTION (all rows)")
        print(f"  min={min(prices):.2f}  max={max(prices):.2f}")
        print(f"  mean={mean(prices):.2f}  median={median(prices):.2f}")
        print(f"  P25={prices_sorted[n//4]:.2f}  P75={prices_sorted[3*n//4]:.2f}")
    print()
    print("SOLD SIGNAL")
    print(f"  Rows with ≥1 sold: {len(with_sales)}/{len(rows)} ({100*len(with_sales)/max(1,len(rows)):.1f}%)")
    print(f"  Total sold units:  {sum(sold_counts)}")
    if with_sales:
        sold_prices = [r["price"] for r in with_sales if r["price"] is not None]
        if sold_prices:
            sold_sorted = sorted(sold_prices)
            n = len(sold_sorted)
            print(f"  Price of sold rows: min={min(sold_prices):.2f} max={max(sold_prices):.2f} median={median(sold_prices):.2f}")
            print(f"  P25={sold_sorted[n//4]:.2f}  P75={sold_sorted[3*n//4]:.2f}")
    print()
    # Aspect coverage
    aspect_keys = Counter()
    for r in rows:
        for k in r.get("aspects", {}):
            aspect_keys[k] += 1
    print("TOP ASPECT KEYS (structured metadata)")
    for k, c in aspect_keys.most_common(10):
        print(f"  {c:4d} × {k}")


def main() -> None:
    env = load_env()
    query = sys.argv[1] if len(sys.argv) > 1 else "2 euro commemorative"
    total = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    token = get_app_token(env["EBAY_CLIENT_ID"], env["EBAY_CLIENT_SECRET"])
    print(f"\nAggregating query={query!r} total={total}\n")

    agg = aggregate(token, query, total_items=total)
    report(agg)

    dump_path = Path(__file__).parent / "output" / "ebay_aggregate.json"
    dump_path.parent.mkdir(exist_ok=True)
    serializable = {
        "query": agg["query"],
        "api_calls": agg["api_calls"],
        "simple_listings": agg["simple_listings"],
        "groups": {gid: {"title": m["title"], "variations": m["variations"]} for gid, m in agg["groups"].items()},
    }
    dump_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False))
    print(f"\nFull aggregate saved to {dump_path}")


if __name__ == "__main__":
    main()
