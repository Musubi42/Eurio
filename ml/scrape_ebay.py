"""Enrich the canonical referential with eBay market prices — Phase 2C.4.

For each target commemorative entry (`eurio_id`), runs a tightly scoped
Browse API search, filters out lot/proof/collector noise, applies a
velocity-weighted percentile calculation, and writes a point-in-time
`observations.ebay_market = {p25, p50, p75, samples, ...}` observation.

The script uses the *existing* canonical referential as the source of target
coins — we never create new entries. Matching of listings to a target
eurio_id is trivial here because every query is bound to a single
(country, year, theme_slug) triple; we reject listings whose extracted
attributes don't line up with the target.

Budget model: ~1 search + up to ~2 getItem calls per target coin. Default
target count = 30 (first run), override with `--limit`. Full enrichment of
517 commemoratives would consume ~1500 calls — well within the 5000/day
default quota.

Spec: docs/research/ebay-api-strategy.md, docs/phases/phase-2c-referential.md §2C.4.
"""

import argparse
import json
import math
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import httpx

from ebay_client import EbayClient, get_app_token, load_env
from eurio_referential import (
    ISO2_TO_NAME_FR,
    SOURCES_DIR,
    load_referential,
    save_referential,
    slugify,
)

SOURCE_TAG = "ebay"
CATEGORY_EURO_COINS = "32650"

DATASETS_DIR = Path(__file__).parent / "datasets"
MATCHING_LOG_PATH = DATASETS_DIR / "matching_log.jsonl"

# Filters (see ebay-api-strategy.md §6.3)
NOISE_PATTERNS = re.compile(
    r"\b("
    r"lot|coffret|set\b|s[eé]rie\s|collection\s*compl[eè]te|"
    r"bu\b|proof|[eé]preuve|belle\s*[eé]preuve|be\b|"
    r"argent|or\b|silver|gold|plaqu[eé]|"
    r"coloris[eé]e?|color|"
    r"erreur\s*de\s*frappe|faut[eé]e?|"
    r"rouleau|roll\b"
    r")\b",
    re.IGNORECASE,
)
FACE_VALUE_FACTOR_LOW = 0.8
FACE_VALUE_FACTOR_HIGH = 500


# ---------- listing extraction ----------


def _listing_aspects(item: dict) -> dict[str, str]:
    aspects = item.get("localizedAspects") or []
    return {a.get("name", ""): a.get("value", "") for a in aspects if a.get("name")}


def listing_row(item: dict) -> dict:
    """Normalise an item summary or a group variation into a common shape."""
    price = item.get("price") or {}
    avail = (item.get("estimatedAvailabilities") or [{}])[0]
    seller = item.get("seller") or {}
    return {
        "item_id": item.get("itemId"),
        "title": item.get("title") or "",
        "price": float(price["value"]) if price.get("value") else None,
        "currency": price.get("currency"),
        "sold": int(avail.get("estimatedSoldQuantity") or 0),
        "origin_date": item.get("itemOriginDate"),
        "seller": seller.get("username"),
        "seller_fb_pct": _parse_percent(seller.get("feedbackPercentage")),
        "seller_fb_score": seller.get("feedbackScore"),
        "item_web_url": item.get("itemWebUrl"),
        "aspects": _listing_aspects(item),
    }


def _parse_percent(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).rstrip("%"))
    except ValueError:
        return None


# ---------- filtering ----------


def accept_listing(row: dict, face_value: float) -> tuple[bool, str]:
    """Filter a listing against the anti-noise rules."""
    title = row.get("title") or ""
    if NOISE_PATTERNS.search(title):
        return False, "noise_title"
    price = row.get("price")
    if price is None:
        return False, "no_price"
    if row.get("currency") and row["currency"] != "EUR":
        return False, "non_eur"
    if price < face_value * FACE_VALUE_FACTOR_LOW:
        return False, "below_face"
    if price > face_value * FACE_VALUE_FACTOR_HIGH:
        return False, "above_extreme"
    return True, "ok"


def filter_listings(rows: list[dict], face_value: float) -> tuple[list[dict], dict[str, int]]:
    kept: list[dict] = []
    reasons: dict[str, int] = defaultdict(int)
    for r in rows:
        ok, reason = accept_listing(r, face_value)
        if ok:
            kept.append(r)
        reasons[reason] += 1
    return kept, dict(reasons)


# ---------- velocity weighting ----------


def _years_since(origin: str | None) -> float:
    if not origin:
        return 0.5
    try:
        dt = datetime.fromisoformat(origin.replace("Z", "+00:00"))
    except ValueError:
        return 0.5
    delta = datetime.now(timezone.utc) - dt
    return max(delta.days / 365.25, 0.5)


def listing_weight(row: dict) -> float:
    """Velocity weight: log(1 + sales_per_year) × seller_trust."""
    sold = row.get("sold") or 0
    years = _years_since(row.get("origin_date"))
    sales_per_year = sold / years if years > 0 else 0.0
    velocity = math.log1p(sales_per_year)
    trust = (row.get("seller_fb_pct") or 0.0) / 100.0
    # Floor on trust so listings without a feedback score aren't zeroed out;
    # otherwise a new seller with no history would contribute 0 weight
    # regardless of sold count.
    return max(velocity * max(trust, 0.1), 0.05)


def weighted_quantile(values: list[float], weights: list[float], q: float) -> float | None:
    if not values:
        return None
    paired = sorted(zip(values, weights))
    total = sum(w for _, w in paired)
    if total <= 0:
        # Fall back to unweighted.
        vals_sorted = [v for v, _ in paired]
        k = int(q * (len(vals_sorted) - 1))
        return vals_sorted[k]
    target = q * total
    cum = 0.0
    for v, w in paired:
        cum += w
        if cum >= target:
            return v
    return paired[-1][0]


def compute_market_stats(rows: list[dict]) -> dict[str, Any]:
    prices = [r["price"] for r in rows if r.get("price") is not None]
    weights = [listing_weight(r) for r in rows if r.get("price") is not None]
    if not prices:
        return {
            "p25": None,
            "p50": None,
            "p75": None,
            "samples_count": 0,
            "with_sales_count": 0,
        }
    with_sales = sum(1 for r in rows if (r.get("sold") or 0) > 0)
    return {
        "p25": weighted_quantile(prices, weights, 0.25),
        "p50": weighted_quantile(prices, weights, 0.50),
        "p75": weighted_quantile(prices, weights, 0.75),
        "mean": sum(prices) / len(prices),
        "median_raw": median(prices),
        "samples_count": len(prices),
        "with_sales_count": with_sales,
    }


# ---------- query construction ----------


def target_commemoratives(
    referential: dict[str, dict],
    *,
    countries: set[str] | None = None,
    limit: int | None = None,
    only_enriched: bool = False,
) -> list[dict]:
    """Select commemorative entries to target in this run.

    Priority: coins already enriched by another source (lmdlp/mdp) — that gives
    us cross-validation. Then recent years first. Filters: only 2€ commemos,
    skip eu-* joint issues on the first pass (they'd need cross-country
    queries), optional country filter.
    """
    targets: list[dict] = []
    for entry in referential.values():
        ident = entry["identity"]
        if not ident.get("is_commemorative"):
            continue
        if ident.get("face_value") != 2.0:
            continue
        if ident.get("country") == "eu":
            continue
        if countries and ident.get("country") not in countries:
            continue
        sources = set(entry["provenance"].get("sources_used", []))
        already_enriched = bool(sources & {"lmdlp", "mdp"})
        if only_enriched and not already_enriched:
            continue
        targets.append(entry)

    # Priority: enriched first, then older years first (more listings, established
    # market) and country for stability.
    targets.sort(
        key=lambda e: (
            not bool(set(e["provenance"].get("sources_used", [])) & {"lmdlp", "mdp"}),
            e["identity"]["year"],
            e["identity"]["country"],
        )
    )
    if limit is not None:
        targets = targets[:limit]
    return targets


STOP_WORDS = {
    "of", "the", "in", "and", "a", "an", "to", "for", "with", "on",
    "de", "la", "le", "les", "du", "des", "et", "au", "aux",
    "anniversary", "years", "since", "birth", "death", "founding",
    "th", "st", "nd", "rd",
}


def _theme_keywords(eurio_id: str, max_words: int = 5) -> str:
    """Extract a short keyword string from the design slug, dropping stop words and ordinals."""
    slug_tokens = eurio_id.split("-")[3:]
    kept: list[str] = []
    for tok in slug_tokens:
        if not tok:
            continue
        if tok in STOP_WORDS:
            continue
        if re.match(r"^\d+th$", tok) or re.match(r"^\d{3,4}$", tok):
            # drop anniversaries like "100th" and stray years
            continue
        kept.append(tok)
        if len(kept) >= max_words:
            break
    return " ".join(kept)


def build_search_query(entry: dict) -> tuple[str, str, list[str]]:
    """Build (q, aspect_filter, theme_keyword_tokens) for an eBay search on EBAY_FR.

    We cast a wide net with country + year only — adding full theme keywords
    crushes recall because eBay titles are short and use different phrasings.
    The theme tokens are returned separately so the caller can apply a title
    keyword filter on the response.
    """
    ident = entry["identity"]
    iso2 = ident["country"]
    country_name_fr = ISO2_TO_NAME_FR.get(iso2, ident.get("country_name") or iso2)
    year = ident["year"]
    theme_kw = _theme_keywords(entry["eurio_id"], max_words=4)
    theme_tokens = [t for t in theme_kw.split() if len(t) >= 4]
    q = f"2 euro {country_name_fr} {year}".strip()
    aspect_filter = f"categoryId:{CATEGORY_EURO_COINS},Année:{{{year}}}"
    return q, aspect_filter, theme_tokens


def title_matches_theme(title: str, theme_tokens: list[str]) -> bool:
    """Return True if any theme token appears in the title (case-insensitive).

    When the referential has only one commemo for a given (country, year) we
    don't need any theme match — the aspect filter already uniquely identifies
    the coin. Callers should only invoke this for ambiguous cases.
    """
    if not theme_tokens:
        return True
    low = title.lower()
    return any(tok in low for tok in theme_tokens)


# ---------- single-target pipeline ----------


def collect_listings_for_target(
    client: EbayClient,
    entry: dict,
    theme_tokens: list[str],
    ambiguous: bool,
    max_search_items: int = 50,
    expand_groups_top_k: int = 2,
) -> list[dict]:
    """Run one search + conditional group expansion for a single target entry.

    When `ambiguous` is True (multiple commemos for this country/year), we
    filter out listings whose title doesn't contain any theme keyword.
    """
    q, aspect_filter, _ = build_search_query(entry)
    search = client.search(
        q,
        category_ids=CATEGORY_EURO_COINS,
        aspect_filter=aspect_filter,
        filter_expr="price:[1..500],priceCurrency:EUR",
        limit=max_search_items,
    )
    summaries = search.get("itemSummaries") or []
    rows: list[dict] = []
    group_ids: list[str] = []
    for it in summaries:
        pig = it.get("primaryItemGroup") or {}
        group_id = pig.get("itemGroupId")
        if group_id:
            if group_id not in group_ids:
                group_ids.append(group_id)
        else:
            rows.append(listing_row(it))

    for gid in group_ids[:expand_groups_top_k]:
        try:
            data = client.get_items_by_group(gid)
            for it in data.get("items") or []:
                rows.append(listing_row(it))
        except httpx.HTTPError as exc:
            print(f"    group {gid} failed: {exc}")

    if ambiguous:
        rows = [r for r in rows if title_matches_theme(r.get("title") or "", theme_tokens)]
    return rows


# ---------- enrichment writer ----------


def write_observation(entry: dict, stats: dict, query_used: str, kept_rows: list[dict]) -> None:
    obs = entry.setdefault("observations", {})
    obs["ebay_market"] = {
        "p25": _round(stats.get("p25")),
        "p50": _round(stats.get("p50")),
        "p75": _round(stats.get("p75")),
        "mean": _round(stats.get("mean")),
        "samples_count": stats.get("samples_count"),
        "with_sales_count": stats.get("with_sales_count"),
        "query": query_used,
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "listings": [
            {
                "item_id": r.get("item_id"),
                "price": r.get("price"),
                "sold": r.get("sold"),
                "origin_date": r.get("origin_date"),
                "seller": r.get("seller"),
                "url": r.get("item_web_url"),
            }
            for r in kept_rows[:10]  # keep a small provenance trail
        ],
    }
    sources = entry["provenance"].setdefault("sources_used", [])
    if SOURCE_TAG not in sources:
        sources.append(SOURCE_TAG)
    entry["provenance"]["last_updated"] = date.today().isoformat()


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


# ---------- logging ----------


def append_matching_log(entries: list[dict]) -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    sampled_at = datetime.now(timezone.utc).isoformat()
    with MATCHING_LOG_PATH.open("a") as f:
        for rec in entries:
            f.write(
                json.dumps(
                    {"source": SOURCE_TAG, "sampled_at": sampled_at, **rec},
                    ensure_ascii=False,
                )
                + "\n"
            )


def write_snapshot(records: list[dict]) -> Path:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"ebay_{date.today().isoformat()}.json"
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    return path


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Enrich referential with eBay market prices")
    ap.add_argument("--limit", type=int, default=30, help="Max target coins to enrich (default 30)")
    ap.add_argument(
        "--countries",
        default="FR,DE,IT,ES,GR",
        help="Comma-separated ISO2 country filter (default FR,DE,IT,ES,GR)",
    )
    ap.add_argument(
        "--all-commemos",
        action="store_true",
        help="Target all commemos instead of only those already enriched by lmdlp/mdp",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Sleep seconds between API calls (politeness)",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    countries = {c.strip().upper() for c in args.countries.split(",")} if args.countries else None

    env = load_env()
    client_id = env.get("EBAY_CLIENT_ID")
    client_secret = env.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: EBAY_CLIENT_ID / EBAY_CLIENT_SECRET missing from .env")
        raise SystemExit(1)

    referential = load_referential()
    targets = target_commemoratives(
        referential,
        countries=countries,
        limit=args.limit,
        only_enriched=not args.all_commemos,
    )
    print(f"Loaded referential: {len(referential)} entries")
    print(f"Targeting {len(targets)} commemoratives ({'any' if args.all_commemos else 'lmdlp/mdp-enriched'}, countries={sorted(countries or [])})")

    # Count commemos per (country, year) to decide when theme filtering matters
    commemo_count: dict[tuple[str, int], int] = defaultdict(int)
    for entry in referential.values():
        ident = entry["identity"]
        if ident.get("is_commemorative") and ident.get("face_value") == 2.0 and ident.get("country") != "eu":
            commemo_count[(ident["country"], ident["year"])] += 1

    token = get_app_token(client_id, client_secret)
    snapshot_records: list[dict] = []
    log_entries: list[dict] = []
    touched = 0

    with EbayClient(token) as client:
        for idx, entry in enumerate(targets, 1):
            q, _, theme_tokens = build_search_query(entry)
            key = (entry["identity"]["country"], entry["identity"]["year"])
            ambiguous = commemo_count[key] > 1
            print(f"\n[{idx}/{len(targets)}] {entry['eurio_id']}")
            print(f"  q: {q}  ambiguous={ambiguous}  theme_tokens={theme_tokens}")
            try:
                rows = collect_listings_for_target(
                    client, entry, theme_tokens, ambiguous=ambiguous
                )
            except httpx.HTTPError as exc:
                print(f"  FAIL: {exc}")
                log_entries.append(
                    {"eurio_id": entry["eurio_id"], "status": "http_error", "error": str(exc)}
                )
                continue
            kept, reasons = filter_listings(rows, face_value=2.0)
            stats = compute_market_stats(kept)
            print(f"  raw={len(rows)} kept={len(kept)} reasons={reasons}")
            print(
                f"  p25={stats.get('p25')} p50={stats.get('p50')} p75={stats.get('p75')} "
                f"samples={stats['samples_count']} with_sales={stats['with_sales_count']}"
            )

            snapshot_records.append(
                {
                    "eurio_id": entry["eurio_id"],
                    "query": q,
                    "raw_count": len(rows),
                    "kept_count": len(kept),
                    "stats": stats,
                    "kept": kept,
                }
            )
            log_entries.append(
                {
                    "eurio_id": entry["eurio_id"],
                    "query": q,
                    "raw_count": len(rows),
                    "kept_count": len(kept),
                    "with_sales": stats["with_sales_count"],
                    "p50": _round(stats.get("p50")),
                }
            )

            if stats["samples_count"] >= 3:
                write_observation(entry, stats, q, kept)
                touched += 1
            time.sleep(args.sleep)

    snapshot_path = write_snapshot(snapshot_records)
    save_referential(referential)
    append_matching_log(log_entries)

    print("\n" + "=" * 60)
    print(f"Snapshot: {snapshot_path}")
    print(f"eBay API calls consumed: {client.call_count}")
    print(f"Enriched entries: {touched}/{len(targets)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
