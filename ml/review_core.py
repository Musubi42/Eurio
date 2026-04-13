"""Pure review-queue helpers shared by all review tools (CLI or web server).

This module has no I/O side effects at import time and no interactive parts.
It owns :
- the `ReviewGroup` model that bundles all variants of a single human decision
- queue/resolutions/referential loaders and savers
- the per-source `enrich_*` dispatchers
- the state mutators (`mark_group_resolved`)

Spec : docs/research/data-referential-architecture.md §5.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from eurio_referential import load_referential, save_referential

DATASETS_DIR = Path(__file__).parent / "datasets"
REVIEW_QUEUE_PATH = DATASETS_DIR / "review_queue.json"
MANUAL_RESOLUTIONS_PATH = DATASETS_DIR / "manual_resolutions.json"
MATCHING_LOG_PATH = DATASETS_DIR / "matching_log.jsonl"
SOURCES_DIR = DATASETS_DIR / "sources"


# ---------- persistent state I/O ----------


def load_queue() -> list[dict]:
    if not REVIEW_QUEUE_PATH.exists():
        return []
    return json.loads(REVIEW_QUEUE_PATH.read_text())


def save_queue(queue: list[dict]) -> None:
    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_QUEUE_PATH.write_text(json.dumps(queue, indent=2, ensure_ascii=False))


def load_resolutions() -> dict[str, str]:
    if not MANUAL_RESOLUTIONS_PATH.exists():
        return {}
    return json.loads(MANUAL_RESOLUTIONS_PATH.read_text())


def save_resolutions(resolutions: dict[str, str]) -> None:
    MANUAL_RESOLUTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_RESOLUTIONS_PATH.write_text(
        json.dumps(resolutions, indent=2, ensure_ascii=False)
    )


def append_matching_log(records: list[dict]) -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    sampled_at = datetime.now(timezone.utc).isoformat()
    with MATCHING_LOG_PATH.open("a") as f:
        for r in records:
            f.write(json.dumps({"sampled_at": sampled_at, **r}, ensure_ascii=False) + "\n")


def load_source_snapshot(source: str) -> list[dict]:
    """Load the most recent `{source}_*.json` snapshot in sources/."""
    candidates = sorted(SOURCES_DIR.glob(f"{source}_*.json"), reverse=True)
    if not candidates:
        return []
    return json.loads(candidates[0].read_text())


# ---------- group model ----------


@dataclass
class ReviewGroup:
    source: str
    country: str
    year: int
    theme_slug: str
    items: list[dict]
    candidates: list[str]

    @property
    def key(self) -> str:
        return f"{self.source}:{self.country}:{self.year}:{self.theme_slug}"

    @property
    def sample_item(self) -> dict:
        return self.items[0]


def build_groups(
    queue: list[dict],
    *,
    source_filter: str | None = None,
    only_unresolved: bool = True,
) -> list[ReviewGroup]:
    """Bucket queue items by (source, country, year, theme_slug). Stable order."""
    buckets: dict[tuple[str, str, int, str], list[dict]] = defaultdict(list)
    for item in queue:
        if only_unresolved and item.get("resolved"):
            continue
        if source_filter and item.get("source") != source_filter:
            continue
        rp = item.get("raw_payload") or {}
        country = rp.get("country") or "?"
        year = rp.get("year") or 0
        theme = rp.get("theme_slug") or "?"
        key = (item.get("source") or "?", country, year, theme)
        buckets[key].append(item)

    groups: list[ReviewGroup] = []
    for (source, country, year, theme), items in buckets.items():
        cands = items[0].get("candidates") or []
        groups.append(
            ReviewGroup(
                source=source,
                country=country,
                year=year,
                theme_slug=theme,
                items=items,
                candidates=cands,
            )
        )
    groups.sort(key=lambda g: (g.source, g.country, g.year, g.theme_slug))
    return groups


def mark_group_resolved(group: ReviewGroup, action: str, value: str | None) -> None:
    """Stamp every queue item in this group as resolved."""
    now = datetime.now(timezone.utc).isoformat()
    for item in group.items:
        item["resolved"] = True
        item["resolution"] = {
            "action": action,
            "eurio_id": value if action == "pick" else None,
            "decided_at": now,
        }


# ---------- per-source enrichers ----------


def enrich_lmdlp(
    referential: dict[str, dict],
    eurio_id: str,
    items: list[dict],
    snapshot: list[dict],
) -> int:
    """Apply a manual lmdlp resolution : append the matching snapshot products
    to `observations.lmdlp_variants`, dedupe by SKU. Returns number added."""
    from scrape_lmdlp import build_variant_obs, extract_mintage

    target = referential.get(eurio_id)
    if target is None:
        return 0

    skus_in_group = {it.get("source_native_id") for it in items if it.get("source_native_id")}
    snapshot_by_sku = {p.get("sku"): p for p in snapshot if p.get("sku")}
    matching_products = [snapshot_by_sku[sku] for sku in skus_in_group if sku in snapshot_by_sku]
    if not matching_products:
        return 0

    obs = target.setdefault("observations", {})
    existing_variants = obs.get("lmdlp_variants") or []
    existing_skus = {v.get("sku") for v in existing_variants if v.get("sku")}

    added = 0
    for product in matching_products:
        if product.get("sku") in existing_skus:
            continue
        existing_variants.append(build_variant_obs(product))
        added += 1
    obs["lmdlp_variants"] = existing_variants

    if "lmdlp_mintage" not in obs:
        mintage = next((m for m in (extract_mintage(p) for p in matching_products) if m), None)
        if mintage:
            obs["lmdlp_mintage"] = {
                "value": mintage,
                "source": "lmdlp",
                "fetched_at": date.today().isoformat(),
            }

    cross_refs = target.setdefault("cross_refs", {})
    existing_sku_list = cross_refs.get("lmdlp_skus") or []
    for sku in skus_in_group:
        if sku and sku not in existing_sku_list:
            existing_sku_list.append(sku)
    cross_refs["lmdlp_skus"] = existing_sku_list
    if not cross_refs.get("lmdlp_url") and matching_products:
        cross_refs["lmdlp_url"] = matching_products[0].get("permalink")

    sources = target["provenance"].setdefault("sources_used", [])
    if "lmdlp" not in sources:
        sources.append("lmdlp")
    target["provenance"]["last_updated"] = date.today().isoformat()

    return added


SOURCE_ENRICHERS: dict[str, Callable[[dict, str, list[dict], list[dict]], int]] = {
    "lmdlp": enrich_lmdlp,
}


# ---------- live enrichment preview (for server UI) ----------


def candidate_preview(entry: dict | None) -> dict[str, Any]:
    """Compact summary of an existing canonical entry's enrichment state."""
    if entry is None:
        return {"missing": True}
    ident = entry.get("identity") or {}
    obs = entry.get("observations") or {}
    wiki = obs.get("wikipedia") or {}
    ebay = obs.get("ebay_market") or {}
    lmdlp_variants = obs.get("lmdlp_variants") or []
    mdp_issue = obs.get("mdp_issue") or []
    images = entry.get("images") or []
    return {
        "missing": False,
        "theme": ident.get("theme"),
        "design_description": ident.get("design_description"),
        "country": ident.get("country"),
        "year": ident.get("year"),
        "is_joint_issue": ident.get("country") == "eu",
        "national_variants": ident.get("national_variants"),
        "wikipedia_volume": wiki.get("volume") or wiki.get("total_volume"),
        "lmdlp_variants_count": len(lmdlp_variants),
        "mdp_issue_count": len(mdp_issue),
        "ebay_p50": ebay.get("p50"),
        "ebay_samples": ebay.get("samples_count"),
        "sources_used": (entry.get("provenance") or {}).get("sources_used") or [],
        "image_url": images[0]["url"] if images else None,
    }
