"""Verify the ambiguous Numista IDs by re-fetching from the Numista API.

For each item in numista_review_queue.json, fetches the type details and
compares (country, year) with what the catalog recorded.  Splits the queue into:
  - ✅ Confirmed  : API data matches catalog → genuine ambiguity, keep in review
  - ❌ Bad ID     : mismatch → catalog entry is wrong, pull it out

Dry-run by default — pass --write to actually update files.

Usage:
    cd ml && python -m referential.verify_review_queue
    cd ml && python -m referential.verify_review_queue --write
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from referential.numista_keys import KeyManager
from referential.import_numista import get_type_details
from referential.eurio_referential import COUNTRY_NAME_TO_ISO2

DATASETS_DIR   = Path(__file__).parent.parent / "datasets"
REVIEW_PATH    = DATASETS_DIR / "numista_review_queue.json"
CATALOG_PATH   = DATASETS_DIR / "coin_catalog.json"
BAD_IDS_PATH   = DATASETS_DIR / "numista_bad_ids.json"

DELAY = 0.5  # seconds between API calls

# A few Numista country names not in the shared map
_EXTRA_COUNTRY_MAP = {
    "Germany, Federal Republic of": "DE",
    "Germany": "DE",
}


def to_iso2(name: str) -> str | None:
    return COUNTRY_NAME_TO_ISO2.get(name) or _EXTRA_COUNTRY_MAP.get(name)


def fetch_and_verify(km: KeyManager, item: dict) -> dict:
    """Return a verdict dict for one review queue item."""
    numista_id   = item["numista_id"]
    catalog_country = item["country"]   # ISO2
    catalog_year    = item["year"]      # int

    try:
        data = km.call(get_type_details, numista_id)
    except Exception as exc:
        return {
            "numista_id": numista_id,
            "status": "error",
            "error": str(exc),
            "item": item,
            "api_data": None,
        }

    # Extract country from API response
    issuer = data.get("issuer") or {}
    if isinstance(issuer, list):
        issuer = issuer[0] if issuer else {}
    api_country_name = issuer.get("name", "")
    api_iso2 = to_iso2(api_country_name)

    # Extract year — Numista uses min_year / max_year, or plain year
    api_min_year = data.get("min_year") or data.get("year")
    api_max_year = data.get("max_year") or api_min_year
    api_title    = data.get("title") or data.get("name") or ""

    # Year match: catalog year must fall within [min_year, max_year]
    try:
        api_min = int(api_min_year) if api_min_year else None
        api_max = int(api_max_year) if api_max_year else None
    except (ValueError, TypeError):
        api_min = api_max = None

    country_ok = (api_iso2 == catalog_country) if api_iso2 else False
    year_ok = (
        api_min is not None
        and api_max is not None
        and api_min <= catalog_year <= api_max
    )

    status = "confirmed" if (country_ok and year_ok) else "bad_id"

    return {
        "numista_id": numista_id,
        "status": status,
        "item": item,
        "api_data": {
            "title": api_title,
            "country_name": api_country_name,
            "country_iso2": api_iso2,
            "min_year": api_min,
            "max_year": api_max,
        },
        "mismatch": {
            "expected_country": catalog_country,
            "got_country": api_iso2,
            "expected_year": catalog_year,
            "got_year_range": f"{api_min}–{api_max}",
        } if status == "bad_id" else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="Write updated queue + bad-IDs file + cleaned catalog")
    args = parser.parse_args()

    if not REVIEW_PATH.exists():
        print("No review queue found — nothing to do.")
        return 0

    queue: list[dict] = json.loads(REVIEW_PATH.read_text())
    print(f"Review queue: {len(queue)} items")

    catalog: dict = json.loads(CATALOG_PATH.read_text())
    catalog_coins: dict = catalog.get("coins", catalog)  # support both shapes

    km = KeyManager()
    quota = km.status()
    remaining = sum(s["remaining"] for s in quota)
    print(f"Numista quota remaining: {remaining} calls across {len(quota)} key(s)")
    if remaining < len(queue):
        print(f"WARNING: only {remaining} calls left, queue has {len(queue)} items — may not finish")

    print()

    verdicts: list[dict] = []
    confirmed: list[dict] = []
    bad: list[dict] = []
    errors: list[dict] = []

    for i, item in enumerate(queue, 1):
        nid = item["numista_id"]
        print(f"[{i:2d}/{len(queue)}] #{nid} {item['numista_name'][:50]}", end="  ")
        v = fetch_and_verify(km, item)
        verdicts.append(v)

        if v["status"] == "confirmed":
            print("✅ OK")
            confirmed.append(item)
        elif v["status"] == "bad_id":
            api = v["api_data"]
            m = v["mismatch"]
            print(f"❌ BAD — API says: {api['title']!r} | {api['country_iso2']} {api['min_year']}–{api['max_year']}  (expected {m['expected_country']} {m['expected_year']})")
            bad.append(v)
        else:
            print(f"⚠  ERROR: {v['error']}")
            errors.append(v)

        time.sleep(DELAY)

    print()
    print(f"Results: {len(confirmed)} confirmed / {len(bad)} bad IDs / {len(errors)} errors")
    print()

    if bad:
        print("─── Bad IDs detail ───────────────────────────────────────")
        for v in bad:
            api = v["api_data"]
            item = v["item"]
            print(f"  numista_id={v['numista_id']}")
            print(f"    Catalog said : {item['numista_name']!r}  {item['country']} {item['year']}")
            print(f"    Numista says : {api['title']!r}  {api['country_iso2']} {api['min_year']}–{api['max_year']}")
            print(f"    Candidates   : {', '.join(c['eurio_id'] for c in item['candidates'])}")
            print()

    if not args.write:
        print("─── Dry-run — pass --write to apply changes ──────────────")
        return 0

    # ── Write updated queue (confirmed only) ─────────────────────────────────
    REVIEW_PATH.write_text(json.dumps(confirmed, indent=2, ensure_ascii=False))
    print(f"✓ numista_review_queue.json updated: {len(confirmed)} items")

    # ── Write bad-IDs report ─────────────────────────────────────────────────
    bad_report = [
        {
            "numista_id": v["numista_id"],
            "catalog_name": v["item"]["numista_name"],
            "catalog_country": v["item"]["country"],
            "catalog_year": v["item"]["year"],
            "api_title": v["api_data"]["title"],
            "api_country": v["api_data"]["country_iso2"],
            "api_year_range": f"{v['api_data']['min_year']}–{v['api_data']['max_year']}",
            "candidates": [c["eurio_id"] for c in v["item"]["candidates"]],
        }
        for v in bad
    ]
    BAD_IDS_PATH.write_text(json.dumps(bad_report, indent=2, ensure_ascii=False))
    print(f"✓ numista_bad_ids.json written: {len(bad_report)} entries")

    # ── Remove bad IDs from coin_catalog.json ────────────────────────────────
    bad_nids = {str(v["numista_id"]) for v in bad}
    removed_from_catalog = 0
    for nid in bad_nids:
        if nid in catalog_coins:
            del catalog_coins[nid]
            removed_from_catalog += 1

    catalog_out = catalog if "coins" in catalog else {"coins": catalog_coins}
    CATALOG_PATH.write_text(json.dumps(catalog_out, indent=2, ensure_ascii=False))
    print(f"✓ coin_catalog.json cleaned: {removed_from_catalog} bad entries removed")

    print()
    print(f"Done. {len(confirmed)} items remain in the review queue for manual resolution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
