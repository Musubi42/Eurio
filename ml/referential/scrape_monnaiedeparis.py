"""Scrape monnaiedeparis.fr for official issue prices — Phase 2C.3.

Walks the public sitemap, keeps product pages for 2€ commemorative coins
(excludes rolls/keyring accessories), fetches each page and extracts the
JSON-LD Product schema (name, image, price, availability). Matches against
the canonical referential via the shared multi-stage matcher and writes
`observations.mdp_issue` (the *official* issue price — never overwritten
once set, this is a historical price point).

MDP only mints French coins (plus the French variant of joint issues) so the
issuer is always FR. Year and quality are extracted from the URL slug.

Outputs:
- `ml/datasets/sources/mdp_YYYY-MM-DD.json` — raw product payloads
- `ml/datasets/eurio_referential.json` — enriched in place
- `ml/datasets/matching_log.jsonl` — append-only
- `ml/datasets/review_queue.json` — escalations (replaces source=mdp slot)
"""

import argparse
import html
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from referential.eurio_referential import (
    SOURCES_DIR,
    load_referential,
    save_referential,
    slugify,
)
from eval.matching import index_referential, match as match_identity
from state.sources_runs import record_run

SITEMAP_URL = "https://www.monnaiedeparis.fr/media/sitemap/sitemap_mdp_fr.xml"
USER_AGENT = "Eurio/0.1 mdp-scraper (https://github.com/Musubi42/Eurio)"
SOURCE_TAG = "mdp"

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
MATCHING_LOG_PATH = DATASETS_DIR / "matching_log.jsonl"
REVIEW_QUEUE_PATH = DATASETS_DIR / "review_queue.json"

# URL pattern for a 2€ commemo single coin page.
COIN_URL_RX = re.compile(
    r"/fr/(?P<slug>[\w\-]+?)-monnaie-de-2eur-commemorative(?:-belle-epreuve)?"
    r"-qualite-(?P<quality>[a-z\-]+?)-millesime-(?P<year>\d{4})",
    re.IGNORECASE,
)
# Blacklist patterns anywhere in the URL.
URL_BLACKLIST = ("rouleau-de-", "porte-cles", "accessoire")


# ---------- sitemap + fetch ----------


def fetch_sitemap() -> list[str]:
    resp = httpx.get(
        SITEMAP_URL,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    urls = re.findall(r"<loc>([^<]+)</loc>", resp.text)
    return urls


def filter_coin_urls(urls: list[str]) -> list[dict]:
    """Return one dict per 2€ commemo product URL with the parsed metadata."""
    out: list[dict] = []
    seen: set[str] = set()
    for url in urls:
        low = url.lower()
        if any(b in low for b in URL_BLACKLIST):
            continue
        m = COIN_URL_RX.search(url)
        if not m:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "url": url,
                "theme_url_slug": m.group("slug"),
                "quality_raw": m.group("quality"),
                "year": int(m.group("year")),
            }
        )
    return out


def fetch_product_page(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  FAIL {url}: {exc}")
        return None
    return resp.text


# ---------- JSON-LD extraction ----------


def extract_product_jsonld(html_text: str) -> dict | None:
    """Return the first JSON-LD block with @type == 'Product', or None."""
    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html_text,
        flags=re.S,
    )
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return None


def extract_price_eur(ld: dict) -> float | None:
    offers = ld.get("offers") or {}
    if isinstance(offers, list) and offers:
        offers = offers[0]
    raw = offers.get("price")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def extract_availability(ld: dict) -> str | None:
    offers = ld.get("offers") or {}
    if isinstance(offers, list) and offers:
        offers = offers[0]
    raw = offers.get("availability") or ""
    # Values look like 'https://schema.org/OutOfStock'
    return raw.rsplit("/", 1)[-1] if raw else None


def extract_sku_from_image(ld: dict) -> str | None:
    """Return the image filename (without extension) as the MDP product sku.

    MDP stores product images under /catalog/product/X/Y/{name}.png. There is
    no true SKU exposed publicly, so the image filename is the most stable
    cross-reference we can compute — it stays constant across re-scrapes.
    """
    img = ld.get("image") or ""
    if not img:
        return None
    m = re.search(r"/catalog/product/[^/]+/[^/]+/([^/?]+)", img)
    if not m:
        return None
    return m.group(1).rsplit(".", 1)[0]


# ---------- identity extraction ----------


# Themes where MDP coincards actually carry the same canonical coin but
# appear under distinct sub-product slugs (one per artwork on the coincard
# cover). They all match to the same eurio_id.
SUBTHEME_COLLAPSE = {
    "musee-du-louvre-la-joconde": "musee-du-louvre",
    "musee-du-louvre-la-venus-de-milo": "musee-du-louvre",
    "musee-du-louvre-la-victoire-de-samothrace": "musee-du-louvre",
    "musee-du-louvre-l-amour-et-psyche-a-demi-couchee": "musee-du-louvre",
    "musee-du-louvre-polissage-inverse": "musee-du-louvre",
}


def extract_theme_slug(product_meta: dict, ld: dict | None) -> str:
    """Best-effort canonical theme slug.

    Combines:
    - the URL slug (reliable, kebab-case already)
    - the JSON-LD product name (more human, can disambiguate)
    Collapses known sub-theme packaging variants onto the canonical theme.
    """
    url_slug = product_meta["theme_url_slug"]
    url_slug = SUBTHEME_COLLAPSE.get(url_slug, url_slug)

    # If the JSON-LD name is a proper noun (e.g. 'Erasmus') that doesn't appear
    # in the url slug, prefer the name slug for matching — it's usually cleaner.
    ld_name = html.unescape((ld or {}).get("name") or "").strip()
    if ld_name:
        name_slug = slugify(ld_name)
        # When the LD name is short (single proper noun) and isn't contained in
        # the url slug, use it directly — matching against Wikipedia themes is
        # cleaner with proper nouns than with the full marketing slug.
        if name_slug and len(name_slug.split("-")) <= 3 and name_slug not in url_slug:
            return name_slug
    return url_slug


# MDP only mints French coins (and the French variant of joint issues).
MDP_COUNTRY = "FR"


# ---------- enrichment writer ----------


def build_variant_obs(product_meta: dict, ld: dict, mdp_sku: str | None) -> dict:
    return {
        "sku": mdp_sku,
        "name": html.unescape(ld.get("name") or ""),
        "url": product_meta["url"],
        "price_eur": extract_price_eur(ld),
        "quality": product_meta["quality_raw"],
        "availability": extract_availability(ld),
        "image_url": ld.get("image"),
        "sampled_at": datetime.now(timezone.utc).isoformat(),
    }


def enrich_referential(
    referential: dict[str, dict],
    matched: dict[str, list[dict]],
) -> int:
    """Apply enrichment to the referential in place. Returns number of entries touched.

    `matched` is {eurio_id: [variant_obs_dict, ...]}.
    """
    touched = 0
    today = date.today().isoformat()
    for eurio_id, variants in matched.items():
        entry = referential.get(eurio_id)
        if entry is None:
            continue

        entry.setdefault("observations", {})["mdp_issue"] = variants

        cross_refs = entry.setdefault("cross_refs", {})
        cross_refs["mdp_skus"] = [v["sku"] for v in variants if v.get("sku")]
        cross_refs["mdp_urls"] = [v["url"] for v in variants]

        sources = entry["provenance"].setdefault("sources_used", [])
        if SOURCE_TAG not in sources:
            sources.append(SOURCE_TAG)
        entry["provenance"]["last_updated"] = today

        touched += 1
    return touched


# ---------- logging ----------


def append_matching_log(decisions: list[dict]) -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    sampled_at = datetime.now(timezone.utc).isoformat()
    with MATCHING_LOG_PATH.open("a") as f:
        for d in decisions:
            f.write(
                json.dumps(
                    {"source": SOURCE_TAG, "sampled_at": sampled_at, **d},
                    ensure_ascii=False,
                )
                + "\n"
            )


def replace_review_queue_for_source(items: list[dict]) -> None:
    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if REVIEW_QUEUE_PATH.exists():
        try:
            existing = json.loads(REVIEW_QUEUE_PATH.read_text())
        except json.JSONDecodeError:
            existing = []
    other = [x for x in existing if x.get("source") != SOURCE_TAG]
    REVIEW_QUEUE_PATH.write_text(json.dumps(other + items, indent=2, ensure_ascii=False))


# ---------- main ----------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Scrape only the first N product pages")
    args = parser.parse_args()

    print(f"Fetching sitemap: {SITEMAP_URL}")
    urls = fetch_sitemap()
    print(f"  {len(urls)} URLs in sitemap")
    coin_urls = filter_coin_urls(urls)
    print(f"  {len(coin_urls)} single 2€ commemo product pages")
    if args.limit is not None:
        coin_urls = coin_urls[: args.limit]
        print(f"  --limit {args.limit}: keeping {len(coin_urls)} pages")

    raw_snapshot: list[dict] = []
    products: list[dict] = []
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        for meta in coin_urls:
            html_text = fetch_product_page(client, meta["url"])
            if html_text is None:
                continue
            ld = extract_product_jsonld(html_text)
            if ld is None:
                print(f"  SKIP no JSON-LD: {meta['url']}")
                continue
            products.append({**meta, "ld": ld})
            raw_snapshot.append({**meta, "jsonld": ld})
            time.sleep(0.5)  # politeness
            print(f"  OK  {meta['year']} {meta['quality_raw']} {ld.get('name', '')[:40]}")

    # Immutable snapshot
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = SOURCES_DIR / f"mdp_{date.today().isoformat()}.json"
    snapshot_path.write_text(json.dumps(raw_snapshot, indent=2, ensure_ascii=False))
    print(f"\nSnapshot: {snapshot_path}")

    referential = load_referential()
    print(f"Loaded referential: {len(referential)} entries")
    idx = index_referential(referential)

    decisions: list[dict] = []
    matched_by_eurio: dict[str, list[dict]] = defaultdict(list)
    queue: list[dict] = []
    stage_counts: dict[str, int] = defaultdict(int)

    for p in products:
        ld = p["ld"]
        mdp_sku = extract_sku_from_image(ld)
        theme_slug = extract_theme_slug(p, ld)
        decision = match_identity(idx, MDP_COUNTRY, p["year"], theme_slug)
        decision = {
            "sku": mdp_sku,
            "url": p["url"],
            "name": html.unescape(ld.get("name") or ""),
            **decision,
        }
        decisions.append(decision)
        stage_counts[decision["stage"]] += 1

        if decision.get("eurio_id"):
            matched_by_eurio[decision["eurio_id"]].append(build_variant_obs(p, ld, mdp_sku))
        elif decision["stage"] == "5":
            queue.append(
                {
                    "source": SOURCE_TAG,
                    "source_native_id": mdp_sku or p["url"],
                    "reason": decision.get("reason"),
                    "candidates": decision.get("candidates", []),
                    "raw_payload": {
                        "url": p["url"],
                        "name": html.unescape(ld.get("name") or ""),
                        "year": p["year"],
                        "quality": p["quality_raw"],
                        "theme_slug": theme_slug,
                    },
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    print("\nMatching results:")
    for stage in sorted(stage_counts):
        print(f"  stage {stage}: {stage_counts[stage]}")
    print(f"  unique coins matched: {len(matched_by_eurio)}")

    touched = enrich_referential(referential, matched_by_eurio)
    save_referential(referential)
    print(f"\nEnriched {touched} referential entries")

    append_matching_log(decisions)
    replace_review_queue_for_source(queue)
    if queue:
        print(f"Queued {len(queue)} products for human review")

    record_run("mdp", "scrape", calls=0, added_coins=touched)


if __name__ == "__main__":
    main()
