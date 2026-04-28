"""Scrape lamonnaiedelapiece.com and enrich the canonical referential — Phase 2C.2.

Pulls all products with attribute "Nominale waarde = 2 euro" via the WooCommerce
Store API (server-side filter), keeps only single 2€ commemorative coins (no
sets, rolls, coffrets, gold/silver investment), and runs the multi-stage matcher
against the canonical referential.

A single physical coin typically appears as multiple SKUs on the shop — UNC,
BU FDC, BE Polissage inversé, Coincard, etc. We group all variants of the same
coin under the same `eurio_id` and store them in `observations.lmdlp_variants`
as a list. Mintage from the `Tirage` attribute lands in
`observations.lmdlp_mintage` (additive, doesn't overwrite Wikipedia).

Outputs:
- `ml/datasets/sources/lmdlp_YYYY-MM-DD.json` — raw immutable snapshot
- `ml/datasets/eurio_referential.json` — enriched in place
- `ml/datasets/matching_log.jsonl` — append-only, one line per matched product
- `ml/datasets/review_queue.json` — escalations
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
    COUNTRY_NAME_FR_TO_ISO2,
    SOURCES_DIR,
    load_referential,
    save_referential,
    slugify,
)
from eval.matching import (
    best_slug_match,
    candidates_for,
    index_referential,
    match as match_identity,
    slug_score,
)
from state.sources_runs import record_run

API_BASE = "https://lamonnaiedelapiece.com/wp-json/wc/store/v1/products"
USER_AGENT = "Eurio/0.1 lmdlp-scraper (https://github.com/Musubi42/Eurio)"
ATTR_DENOM_2EUR = ("pa_nominale-waarde", "2-euro-fr")
SOURCE_TAG = "lmdlp"

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
MATCHING_LOG_PATH = DATASETS_DIR / "matching_log.jsonl"
REVIEW_QUEUE_PATH = DATASETS_DIR / "review_queue.json"

YEAR_RX = re.compile(r"^(19|20)\d{2}$")
NAME_PREFIX_RX = re.compile(
    r"^2\s*euros?\s+[A-ZÀ-ÿa-zà-ÿ\-\s]+?\s+\d{4}\s*[\u2013\u2014\-:]\s*",
    re.IGNORECASE,
)
QUALITY_SUFFIX_RX = re.compile(
    r"\s+(UNC|BU(?:\s+FDC)?(?:\s+\w+)?|BE(?:\s+\w+)?|"
    r"FDC|Coincard|Blister|Rouleau)\b.*$",
    re.IGNORECASE,
)
TIRAGE_RX = re.compile(r"([\d][\d\s.,\u00a0\u202f]*)")


# ---------- API fetch ----------


def fetch_all_2eur_products() -> list[dict]:
    """Page through the API, return all products tagged 2 euro denomination."""
    products: list[dict] = []
    page = 1
    per_page = 100
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        while True:
            resp = client.get(
                API_BASE,
                params={
                    "per_page": per_page,
                    "page": page,
                    "attributes[0][attribute]": ATTR_DENOM_2EUR[0],
                    "attributes[0][slug]": ATTR_DENOM_2EUR[1],
                },
            )
            resp.raise_for_status()
            chunk = resp.json()
            if not chunk:
                break
            products.extend(chunk)
            total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
            print(f"  page {page}/{total_pages}: +{len(chunk)} products (total {len(products)})")
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.3)
    return products


def write_snapshot(products: list[dict]) -> Path:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"lmdlp_{date.today().isoformat()}.json"
    path.write_text(json.dumps(products, indent=2, ensure_ascii=False))
    return path


# ---------- product extraction helpers ----------


def get_attr_terms(product: dict, attr_name: str) -> list[str]:
    """Return the list of term names for a given attribute name (case-insensitive)."""
    target = attr_name.casefold()
    for a in product.get("attributes", []):
        if (a.get("name") or "").casefold() == target:
            return [t.get("name", "") for t in a.get("terms", [])]
    return []


def extract_country_iso2(product: dict) -> str | None:
    for cat in product.get("categories", []):
        name = cat.get("name", "").strip()
        iso = COUNTRY_NAME_FR_TO_ISO2.get(name)
        if iso:
            return iso
    return None


def extract_year(product: dict) -> int | None:
    for cat in product.get("categories", []):
        name = (cat.get("name") or "").strip()
        if YEAR_RX.match(name):
            return int(name)
    # Fallback: a 4-digit year embedded in the SKU (`it2026piunc`)
    sku = product.get("sku") or ""
    m = re.search(r"(20\d{2})", sku)
    if m:
        return int(m.group(1))
    return None


MULTIPACK_PREFIX_RX = re.compile(r"^\s*\d+\s*x\s+2\s*euros?", re.IGNORECASE)
PLUS_SEPARATOR_RX = re.compile(r"\s\+\s")


def is_single_commemo(product: dict) -> tuple[bool, str]:
    """Return (keep, reason). Filters out sets, rolls, coffrets, bundles.

    Bundles and multi-packs are rejected because Eurio's referential targets
    *individual* canonical coins. A "2 x 2 euros" coincard containing two
    different commemoratives of the same year, or a "5 x 2 euros roll of the
    same coin, cannot be attached to a single eurio_id without losing or
    duplicating information. We drop them at scrape time rather than piling
    them in the review queue. See docs/research/phase-2c5-review-tool-run.md.
    """
    if not product.get("is_purchasable"):
        return False, "not_purchasable"
    types = [t.casefold() for t in get_attr_terms(product, "Type")]
    name = (product.get("name") or "").casefold()
    raw_name = product.get("name") or ""
    cat_names = [(c.get("name") or "").casefold() for c in product.get("categories", [])]

    # N x 2 euros ... => multi-pack (roll or dual bundle). Reject all N > 1.
    if MULTIPACK_PREFIX_RX.match(raw_name):
        return False, "multipack_prefix"
    # Two distinct themes separated by " + " in the raw name => dual bundle
    if PLUS_SEPARATOR_RX.search(raw_name):
        return False, "plus_separator_bundle"

    blacklist_terms = ("coffret", "rouleau", "série", "serie", "set ", " set", "blister")
    if any(b in name for b in blacklist_terms):
        return False, "name_blacklist"
    if any(b in c for c in cat_names for b in ("coffret", "rouleau", "liste")):
        return False, "category_blacklist"

    # Type attribute check — must include "2 euros commémorative" or similar
    if types:
        if not any("commémorative" in t or "commemorative" in t for t in types):
            return False, f"type_not_commemo: {types}"
    return True, "ok"


def extract_theme_slug(product: dict) -> str:
    """Best-effort theme slug from product name (after stripping prefix and quality suffix)."""
    raw = html.unescape(product.get("name") or "")
    # Drop the leading "2 euros {Country} {Year} – " prefix
    cleaned = NAME_PREFIX_RX.sub("", raw)
    # Drop trailing quality marker
    cleaned = QUALITY_SUFFIX_RX.sub("", cleaned)
    return slugify(cleaned)


def extract_price_eur(product: dict) -> float | None:
    p = product.get("prices") or {}
    raw = p.get("price")
    minor = p.get("currency_minor_unit")
    if raw is None or minor is None:
        return None
    try:
        return int(raw) / (10 ** int(minor))
    except (TypeError, ValueError):
        return None


def extract_quality(product: dict) -> str | None:
    qs = get_attr_terms(product, "Qualité")
    return qs[0] if qs else None


def extract_mintage(product: dict) -> int | None:
    """Parse the Tirage attribute. Format is '250.000', '4.000', '1.500.000'."""
    terms = get_attr_terms(product, "Tirage")
    if not terms:
        return None
    raw = terms[0]
    m = TIRAGE_RX.search(raw)
    if not m:
        return None
    cleaned = re.sub(r"[\s.,\u00a0\u202f]", "", m.group(1))
    if not cleaned.isdigit():
        return None
    return int(cleaned)


def extract_image_url(product: dict) -> str | None:
    imgs = product.get("images") or []
    if imgs and isinstance(imgs[0], dict):
        return imgs[0].get("src")
    return None


# ---------- matching pipeline ----------


def match_product(
    product: dict,
    idx: dict[tuple[str, int, float], list[dict]],
) -> dict:
    """Run the shared multi-stage matcher on an lmdlp product."""
    sku = product.get("sku")
    country = extract_country_iso2(product)
    year = extract_year(product)
    theme_slug = extract_theme_slug(product)
    decision = match_identity(idx, country, year, theme_slug)
    return {
        "sku": sku,
        "name": html.unescape(product.get("name") or ""),
        **decision,
    }


# ---------- enrichment writer ----------


def build_variant_obs(product: dict) -> dict:
    return {
        "sku": product.get("sku"),
        "name": html.unescape(product.get("name") or ""),
        "url": product.get("permalink"),
        "price_eur": extract_price_eur(product),
        "quality": extract_quality(product),
        "in_stock": product.get("is_in_stock", False),
        "image_url": extract_image_url(product),
        "sampled_at": datetime.now(timezone.utc).isoformat(),
    }


def enrich_referential(
    referential: dict[str, dict],
    matched: dict[str, list[dict]],
) -> int:
    """Apply enrichment to the referential in place. Returns number of entries touched."""
    touched = 0
    for eurio_id, products in matched.items():
        entry = referential.get(eurio_id)
        if entry is None:
            continue

        variants = [build_variant_obs(p) for p in products]
        entry.setdefault("observations", {})["lmdlp_variants"] = variants

        # Mintage : take the first non-null Tirage we find. Don't overwrite existing.
        mintage = next((m for m in (extract_mintage(p) for p in products) if m), None)
        if mintage:
            existing_obs = entry["observations"]
            if "lmdlp_mintage" not in existing_obs:
                existing_obs["lmdlp_mintage"] = {
                    "value": mintage,
                    "source": SOURCE_TAG,
                    "fetched_at": date.today().isoformat(),
                }

        cross_refs = entry.setdefault("cross_refs", {})
        cross_refs["lmdlp_skus"] = [p.get("sku") for p in products]
        cross_refs["lmdlp_url"] = products[0].get("permalink")

        sources = entry["provenance"].setdefault("sources_used", [])
        if SOURCE_TAG not in sources:
            sources.append(SOURCE_TAG)
        entry["provenance"]["last_updated"] = date.today().isoformat()

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
    """Replace the source's slot in the review queue (idempotent across runs)."""
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


def list_missing_eurio_ids() -> None:
    """Print eurio_ids of 2€ commemos not enriched by lmdlp. Read-only."""
    referential = load_referential()
    for eid, entry in referential.items():
        ident = entry.get("identity", {})
        if not ident.get("is_commemorative"):
            continue
        if ident.get("face_value") != 2.0:
            continue
        if ident.get("country") == "eu":
            continue
        sources = set(entry.get("provenance", {}).get("sources_used", []))
        if SOURCE_TAG not in sources:
            print(eid)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list-missing",
        action="store_true",
        help="Read-only: list eurio_ids absent from the latest lmdlp enrichment, then exit",
    )
    args = parser.parse_args()

    if args.list_missing:
        list_missing_eurio_ids()
        return

    print("Fetching lmdlp 2€ products...")
    raw_products = fetch_all_2eur_products()
    print(f"Fetched {len(raw_products)} raw products")
    snapshot = write_snapshot(raw_products)
    print(f"Snapshot: {snapshot}")

    referential = load_referential()
    print(f"Loaded referential: {len(referential)} entries")
    idx = index_referential(referential)
    print(f"Indexed {sum(len(v) for v in idx.values())} commemo entries by (country, year)")

    filtered: list[dict] = []
    skipped_reasons: dict[str, int] = defaultdict(int)
    for p in raw_products:
        keep, reason = is_single_commemo(p)
        if keep:
            filtered.append(p)
        else:
            skipped_reasons[reason] += 1
    print(f"\nFiltered to {len(filtered)} single commemorative products")
    for r, n in sorted(skipped_reasons.items(), key=lambda x: -x[1]):
        print(f"  skipped {n}: {r}")

    decisions: list[dict] = []
    matched_by_eurio: dict[str, list[dict]] = defaultdict(list)
    queue: list[dict] = []
    stage_counts: dict[str, int] = defaultdict(int)

    for p in filtered:
        decision = match_product(p, idx)
        decisions.append(decision)
        stage_counts[decision["stage"]] += 1
        if decision.get("eurio_id"):
            matched_by_eurio[decision["eurio_id"]].append(p)
        elif decision["stage"] == "5":
            queue.append(
                {
                    "source": SOURCE_TAG,
                    "source_native_id": decision.get("sku"),
                    "reason": decision.get("reason"),
                    "candidates": decision.get("candidates", []),
                    "raw_payload": {
                        "sku": p.get("sku"),
                        "name": html.unescape(p.get("name") or ""),
                        "permalink": p.get("permalink"),
                        "categories": [c.get("name") for c in p.get("categories", [])],
                        "country": decision.get("country"),
                        "year": decision.get("year"),
                        "theme_slug": decision.get("theme_slug"),
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

    record_run("lmdlp", "scrape", calls=0, added_coins=touched)


if __name__ == "__main__":
    main()
