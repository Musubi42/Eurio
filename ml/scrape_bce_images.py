"""Enrich the referential with official BCE coin images — Phase 2C.5b.1.

Wikipedia's commemorative page only carries country flags, not coin images.
The BCE per-year pages `comm_{year}.en.html` are the canonical official
source: each coin has a high-quality JPG with a descriptive filename,
plus an authoritative English Feature / Description / Issuing volume block.

This script walks every published year (2004 → current_year - 1, since the
BCE lags Wikipedia by a few months on new years), parses each page, and
matches the BCE entries against the canonical referential via the shared
multi-stage matcher. Images are appended to `entry["identity"]["images"]`
in the additive 4-layer schema, deduped by absolute URL.

This is the *primary* coin image source. There is no Wikipedia fallback
because Wikipedia genuinely has no coin images on the commemorative page.

Outputs:
- `ml/datasets/sources/bce_comm_{year}_{date}.html` — immutable snapshots
- `ml/datasets/eurio_referential.json` — enriched with images
- `ml/datasets/matching_log.jsonl` — append-only decisions
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from eurio_referential import (
    SOURCES_DIR,
    country_to_iso2,
    load_referential,
    save_referential,
    slugify,
)
from matching import index_referential, match as match_identity

BCE_BASE = "https://www.ecb.europa.eu/euro/coins/comm/html/"
BCE_YEAR_URL = BCE_BASE + "comm_{year}.en.html"
USER_AGENT = "Eurio/0.1 bce-images-scraper (https://github.com/Musubi42/Eurio)"
SOURCE_TAG = "bce_comm"

DATASETS_DIR = Path(__file__).parent / "datasets"
MATCHING_LOG_PATH = DATASETS_DIR / "matching_log.jsonl"

# Country names used by the BCE pages — mostly English, with a couple of
# variants we need to map to ISO2.
BCE_COUNTRY_OVERRIDES: dict[str, str] = {
    "Vatican City State": "VA",
    "Vatican": "VA",
    "Slovak Republic": "SK",
    "Cyprus": "CY",
}


# ---------- BCE fetch ----------


def fetch_year(year: int, sleep: float = 0.4) -> str | None:
    """Fetch a BCE comm_{year}.en.html. Returns None on 404 (year not yet published)."""
    url = BCE_YEAR_URL.format(year=year)
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=30,
        )
    except httpx.HTTPError as exc:
        print(f"  [{year}] FAIL: {exc}")
        return None
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    time.sleep(sleep)
    return resp.text


def write_snapshot(year: int, html: str) -> Path:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"bce_comm_{year}_{date.today().isoformat()}.html"
    path.write_text(html)
    return path


# ---------- BCE parser ----------


PARAGRAPH_KEYS = {
    "feature": re.compile(r"^Feature\s*:\s*(.*)$", re.IGNORECASE | re.S),
    "description": re.compile(r"^Description\s*:\s*(.*)$", re.IGNORECASE | re.S),
    "issuing_volume": re.compile(r"^Issuing\s+volume\s*:\s*(.*)$", re.IGNORECASE | re.S),
    "issuing_date": re.compile(r"^Issuing\s+date\s*:\s*(.*)$", re.IGNORECASE | re.S),
}


def _extract_text_block(h3: Any) -> dict[str, str]:
    """Walk the <p> tags following an <h3> until the next <h3>, extract metadata."""
    out: dict[str, str] = {}
    for sib in h3.find_all_next():
        if sib.name == "h3":
            break
        if sib.name != "p":
            continue
        txt = sib.get_text(" ", strip=True)
        for key, rx in PARAGRAPH_KEYS.items():
            if key in out:
                continue
            m = rx.match(txt)
            if m:
                out[key] = m.group(1).strip()
                break
        if all(k in out for k in ("feature", "issuing_volume")):
            # Got the essentials; the description is optional
            break
    return out


def parse_bce_page(html: str, year: int) -> list[dict]:
    """Return a list of {country_iso2, year, image_url, feature, description, ...} per coin."""
    soup = BeautifulSoup(html, "lxml")
    coins: list[dict] = []
    for h3 in soup.find_all("h3"):
        country_raw = h3.get_text(" ", strip=True)
        if not country_raw:
            continue
        iso2 = BCE_COUNTRY_OVERRIDES.get(country_raw) or country_to_iso2(country_raw)
        if not iso2:
            continue
        prev_img = h3.find_previous("img")
        if not prev_img:
            continue
        src = prev_img.get("src") or ""
        if not src or not src.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        if src.startswith("/"):
            image_url = "https://www.ecb.europa.eu" + src
        elif src.startswith("http"):
            image_url = src
        else:
            image_url = BCE_BASE + src
        block = _extract_text_block(h3)
        feature = block.get("feature") or ""
        if not feature:
            continue
        coins.append(
            {
                "country": iso2,
                "country_raw": country_raw,
                "year": year,
                "feature": feature,
                "description": block.get("description"),
                "issuing_volume": block.get("issuing_volume"),
                "issuing_date": block.get("issuing_date"),
                "image_url": image_url,
                "theme_slug": slugify(feature),
            }
        )
    return coins


# ---------- enrichment ----------


def enrich_entry_with_image(
    entry: dict,
    coin: dict,
) -> bool:
    """Append the BCE image + description to an existing canonical entry.

    Returns True if a new image was added (False if it was already present).
    """
    images = entry.setdefault("images", [])
    existing_urls = {i.get("url") for i in images}
    if coin["image_url"] in existing_urls:
        return False
    images.append(
        {
            "url": coin["image_url"],
            "source": SOURCE_TAG,
            "role": "obverse",
            "feature": coin.get("feature"),
            "description": coin.get("description"),
            "fetched_at": date.today().isoformat(),
        }
    )
    # Identity description is null on most entries — fill it with the BCE
    # authoritative description if we have it.
    if coin.get("description") and not entry["identity"].get("design_description"):
        entry["identity"]["design_description"] = coin["description"]
    sources = entry["provenance"].setdefault("sources_used", [])
    if SOURCE_TAG not in sources:
        sources.append(SOURCE_TAG)
    entry["provenance"]["last_updated"] = date.today().isoformat()
    return True


def append_matching_log(records: list[dict]) -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    sampled_at = datetime.now(timezone.utc).isoformat()
    with MATCHING_LOG_PATH.open("a") as f:
        for r in records:
            f.write(
                json.dumps(
                    {"source": SOURCE_TAG, "sampled_at": sampled_at, **r},
                    ensure_ascii=False,
                )
                + "\n"
            )


# ---------- main ----------


def main() -> None:
    referential = load_referential()
    print(f"Loaded referential: {len(referential)} entries")
    idx = index_referential(referential)

    current_year = date.today().year
    years = list(range(2004, current_year + 1))
    print(f"Fetching BCE comm pages for {years[0]}-{years[-1]}\n")

    log_records: list[dict] = []
    stage_counts: dict[str, int] = defaultdict(int)
    total_added = 0
    coins_by_year: dict[int, int] = {}

    for year in years:
        html = fetch_year(year)
        if html is None:
            print(f"[{year}] not published yet (404)")
            continue
        write_snapshot(year, html)
        coins = parse_bce_page(html, year)
        coins_by_year[year] = len(coins)
        print(f"[{year}] {len(coins)} BCE coins parsed")

        for coin in coins:
            decision = match_identity(idx, coin["country"], coin["year"], coin["theme_slug"])
            stage_counts[decision["stage"]] += 1
            log_records.append(
                {
                    "country": coin["country"],
                    "year": coin["year"],
                    "theme_slug": coin["theme_slug"],
                    "stage": decision["stage"],
                    "eurio_id": decision.get("eurio_id"),
                    "image_url": coin["image_url"],
                }
            )
            eurio_id = decision.get("eurio_id")
            if not eurio_id:
                continue
            entry = referential.get(eurio_id)
            if entry is None:
                continue
            if enrich_entry_with_image(entry, coin):
                total_added += 1

    save_referential(referential)
    append_matching_log(log_records)

    print("\n" + "=" * 60)
    print(f"BCE coins parsed total: {sum(coins_by_year.values())}")
    print(f"Match stages: {dict(stage_counts)}")
    print(f"Images added to referential: {total_added}")
    print(f"Years covered: {sorted(coins_by_year)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
