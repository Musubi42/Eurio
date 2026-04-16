"""Batch-match coin_catalog.json Numista types to eurio_referential entries.

Reads the existing coin_catalog.json (441 2EUR types with Numista IDs) and
matches them to eurio_referential.json entries using:
  1. Exact key match: (country, face_value, year, is_commemorative) with 1 candidate
  2. Theme matching: fuzzy word overlap between Numista name and referential theme

Updates cross_refs.numista_id in the referential and patches Supabase.
Zero API calls — purely local data matching.

Usage:
    python ml/batch_match_numista.py              # Match + update referential + Supabase
    python ml/batch_match_numista.py --dry-run    # Preview matches without writing
    python ml/batch_match_numista.py --no-supabase # Referential only
    python ml/batch_match_numista.py --review     # Export ambiguous cases for manual review
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from eurio_referential import COUNTRY_NAME_TO_ISO2, load_referential, save_referential
from sync_to_supabase import load_env

CATALOG_PATH = Path(__file__).parent / "datasets" / "coin_catalog.json"
REVIEW_PATH = Path(__file__).parent / "datasets" / "numista_review_queue.json"

# Numista uses some country names that differ from COUNTRY_NAME_TO_ISO2
EXTRA_COUNTRY_MAP = {
    "Germany, Federal Republic of": "DE",
}


def load_catalog() -> dict[str, dict[str, Any]]:
    with open(CATALOG_PATH) as f:
        return json.load(f)["coins"]


def country_to_iso(name: str) -> str | None:
    return COUNTRY_NAME_TO_ISO2.get(name) or EXTRA_COUNTRY_MAP.get(name)


def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def extract_numista_theme(name: str) -> str:
    """Extract theme from Numista name like '2 Euros (Council of Europe)'."""
    m = re.search(r"\((.+)\)", name or "")
    return normalize(m.group(1)) if m else normalize(name or "")


def theme_score(numista_theme: str, ref_theme: str, ref_eurio_id: str) -> float:
    """Score how well a Numista theme matches a referential entry."""
    words = [w for w in numista_theme.split() if len(w) > 2]
    if not words:
        return 0.0
    ref_text = ref_theme + " " + ref_eurio_id
    return sum(1 for w in words if w in ref_text) / len(words)


def match_catalog_to_referential(
    catalog: dict[str, dict[str, Any]],
    referential: dict[str, dict[str, Any]],
) -> tuple[list[tuple[str, int, str]], list[dict[str, Any]]]:
    """Match catalog entries to referential.

    Returns:
        matched: list of (eurio_id, numista_id, match_method) tuples
        ambiguous: list of dicts for manual review
    """
    # Build referential lookup
    ref_by_key: dict[tuple, list[dict[str, Any]]] = {}
    for eurio_id, entry in referential.items():
        ident = entry.get("identity", {})
        key = (ident["country"], ident["face_value"], ident["year"], ident.get("is_commemorative", False))
        ref_by_key.setdefault(key, []).append({"eurio_id": eurio_id, **entry})

    matched: list[tuple[str, int, str]] = []
    ambiguous: list[dict[str, Any]] = []
    no_ref = 0
    already_has = 0

    for nid_str, coin in catalog.items():
        if coin.get("face_value") != 2.0:
            continue

        numista_id = int(nid_str)
        iso = country_to_iso(coin.get("country", ""))
        if not iso:
            continue

        year = coin.get("year")
        is_commemo = coin.get("type") == "commemorative"
        key = (iso, 2.0, year, is_commemo)
        candidates = ref_by_key.get(key, [])

        if not candidates:
            no_ref += 1
            continue

        # Check if already enriched
        if len(candidates) == 1:
            eid = candidates[0]["eurio_id"]
            existing = referential[eid].get("cross_refs", {}).get("numista_id")
            if existing == numista_id:
                already_has += 1
                continue
            matched.append((eid, numista_id, "exact_key"))
            continue

        # Multiple candidates — try theme matching
        numista_theme = extract_numista_theme(coin.get("name", ""))
        scored = []
        for cand in candidates:
            ref_theme = normalize(cand.get("identity", {}).get("theme", "") or "")
            ref_eid = normalize(cand["eurio_id"])
            score = theme_score(numista_theme, ref_theme, ref_eid)
            scored.append((score, cand["eurio_id"]))

        scored.sort(reverse=True)
        best_score, best_eid = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0

        # Accept if best score is good AND clearly better than second
        if best_score >= 0.4 and best_score - second_score >= 0.15:
            existing = referential[best_eid].get("cross_refs", {}).get("numista_id")
            if existing == numista_id:
                already_has += 1
                continue
            matched.append((best_eid, numista_id, "theme"))
        else:
            ambiguous.append({
                "numista_id": numista_id,
                "numista_name": coin.get("name"),
                "country": iso,
                "year": year,
                "numista_theme": numista_theme,
                "candidates": [
                    {"eurio_id": eid, "score": round(sc, 2)}
                    for sc, eid in scored[:4]
                ],
            })

    print(f"  Exact key matches:  {sum(1 for _, _, m in matched if m == 'exact_key')}")
    print(f"  Theme matches:      {sum(1 for _, _, m in matched if m == 'theme')}")
    print(f"  Already enriched:   {already_has}")
    print(f"  Ambiguous (review): {len(ambiguous)}")
    print(f"  No referential:     {no_ref}")

    return matched, ambiguous


def update_referential(
    referential: dict[str, dict[str, Any]],
    matched: list[tuple[str, int, str]],
) -> None:
    today = date.today().isoformat()
    for eurio_id, numista_id, _ in matched:
        entry = referential[eurio_id]
        if "cross_refs" not in entry:
            entry["cross_refs"] = {}
        entry["cross_refs"]["numista_id"] = numista_id
        entry["provenance"]["last_updated"] = today


def patch_supabase(
    matched: list[tuple[str, int, str]],
    referential: dict[str, dict[str, Any]],
) -> None:
    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("  SKIP: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found")
        return

    base = url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    patched = 0
    errors = 0
    with httpx.Client(headers=headers, timeout=60) as client:
        for eurio_id, _, _ in matched:
            cross_refs = referential[eurio_id].get("cross_refs", {})
            resp = client.patch(
                f"{base}/coins",
                params={"eurio_id": f"eq.{eurio_id}"},
                json={"cross_refs": cross_refs},
            )
            if resp.status_code >= 400:
                print(f"    FAIL {eurio_id}: HTTP {resp.status_code}")
                errors += 1
            else:
                patched += 1

    print(f"  Supabase: patched {patched}" + (f", {errors} errors" if errors else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-supabase", action="store_true")
    parser.add_argument("--review", action="store_true", help="Export ambiguous cases to review file")
    args = parser.parse_args()

    print("Loading data...")
    catalog = load_catalog()
    referential = load_referential()
    two_eur = sum(1 for c in catalog.values() if c.get("face_value") == 2.0)
    print(f"  coin_catalog.json: {two_eur} 2EUR types")
    print(f"  eurio_referential: {len(referential)} entries")

    print("\nMatching...")
    matched, ambiguous = match_catalog_to_referential(catalog, referential)
    print(f"\n  Total new matches: {len(matched)}")

    if args.review and ambiguous:
        REVIEW_PATH.write_text(json.dumps(ambiguous, indent=2, ensure_ascii=False))
        print(f"\n  Review queue written: {REVIEW_PATH} ({len(ambiguous)} items)")

    if not matched:
        print("Nothing new to enrich.")
        return 0

    if args.dry_run:
        print("\n--dry-run: not writing.")
        return 0

    print("\nUpdating referential...")
    update_referential(referential, matched)
    save_referential(referential)
    print("  Done.")

    if not args.no_supabase:
        print("\nPatching Supabase...")
        patch_supabase(matched, referential)

    print("\nDone! Run 'go-task android:snapshot' to regenerate the snapshot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
