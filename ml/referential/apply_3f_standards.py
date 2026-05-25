"""Chunk 3f — Standards orphans × 15.

⚠️ DEPRECATED — voir docs/coin-richness/ROADMAP-DB.md P.9.
Le `standard_slug` ci-dessous duplique `numista_eurio_id.standard_slug` (la
version canonique). Ce fichier sera archivé sous `ml/referential/_legacy/`
en P.9 ; aucun nouveau code ne doit l'importer.

Refs:
  docs/research/referential-v2.md (decisions D1–D8)
  docs/research/referential-v2-progress.md §6 (D-3f-1 → D-3f-5)
  ml/datasets/audit_referential_v2.json
  ml/referential/audit_apply_common.py (cross_match_wrong_and_new_types)

Contexte
--------
L'audit a identifié 151 ORPHAN_NEW_TYPE — 89 commémos créées en 3a, 47
absorbés en 3a/3b/3c via cross_matching, restent **15 standards** (entrées
non-commemoratives qui correspondent à des redesigns de portrait/carte côté
Numista non capturés par V1).

Pattern V1 actuel : une entry par "ère de design" (ex be-2007-2eur-standard
= 2nd map era, be-2008 = sub-update). Les 15 standards Numista non couverts
sont des redesigns intermédiaires ou anciens (BE 1999 1st map, MC 2006
Albert II 1st map, VA 2014 Francis, BG 2026 nouvelle eurozone, etc.).

Décisions appliquées (D-3f-1 → D-3f-5)
--------------------------------------
- D-3f-1 : nouveaux TYPE entries (Option A, comme 3a mais non-commémo).
- D-3f-2 : eurio_id format `{country}-{year}-2eur-standard-{slug}` avec slug
           toujours descriptif (rule système : slug long et précis pour tous
           les cas, fallback `1st-type` si Numista ne donne rien).
- D-3f-3 : theme + design_description depuis catalog_name.
- D-3f-4 : `is_commemorative=false`, `needs_review=false` (Numista fait
           autorité sur les standards, pas d'ambiguïté à reviewer).
- D-3f-5 : `coin_variants` / `coin_mint_releases` non touchés. `series_id`
           et `design_group_id` reportés à une session future.

Mode `--dry-run` obligatoire avant `--apply`. Idempotent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.supabase_client import SupabaseClient, load_env  # noqa: E402
from referential.audit_apply_common import (  # noqa: E402
    cross_match_wrong_and_new_types,
    load_audit,
)
from referential.eurio_referential import slugify  # noqa: E402


# ─── Custom slug extractor for standards ─────────────────────────────────────
#
# RE-FETCH CONTRACT (read this before adding heuristics)
# ------------------------------------------------------
# This module participates in the two-tier matching contract documented in
# `docs/research/referential-v2-progress.md` §6 ("Re-fetch contract").
#
#   Tier 1 — BINDING (authoritative, immutable)
#     For every Numista nid we re-fetch from the API, the binding lives in
#     `coin_source_refs (source='numista', native_id=nid) → coin_type_id`.
#     If that row exists we update the existing coin's metadata and NEVER
#     touch its eurio_id (slug freezes at creation).
#
#   Tier 2 — SLUG GENERATION (purely deterministic from API payload)
#     If a nid has no source_refs binding yet, we synthesize a new
#     coin_type_id. The slug must be derivable from the Numista API payload
#     ALONE (no domain knowledge, no external research, no human gut feel).
#     `standard_slug(catalog_name)` below is that pure function.
#
# Why this matters: any heuristic that uses information NOT in the Numista
# payload (e.g. "I happen to know VA 2017 is the 2nd map era") creates a
# binding we can't reproduce on a future re-fetch. The next person running
# the import will get a different slug → orphaned eurio_id, broken history.
#
# When you genuinely have domain knowledge that should override the
# algorithm (e.g. an external authoritative source confirms map version),
# add an entry to MANUAL_NID_SLUG_OVERRIDES below. Keying on numista_id
# (stable across re-fetches) preserves determinism.


_VALUE_PREFIX_RX = re.compile(
    r"^\s*\d+\s*(?:euros?|cent[s]?)\s*-?\s*", re.IGNORECASE
)


# Manual slug overrides keyed on numista_id. Each entry MUST cite an
# authoritative external source in the comment above it. Empty for 3f
# (the algorithm is sufficient for the 15 cases — VA 2014/2017 Francis
# share slug `francis` and are disambiguated by year, which is honest about
# the absence of map info in the Numista catalog name).
MANUAL_NID_SLUG_OVERRIDES: dict[str, str] = {
    # Example template — leave commented unless adding a real override:
    # "105616": "francis-2nd-map",  # VA 2017 — source: <citation>
}


def standard_slug(catalog_name: str) -> str:
    """Extract a descriptive slug for a Numista standard 2€ entry.

    PURE FUNCTION of the Numista catalog_name. No external knowledge.
    See module-level "RE-FETCH CONTRACT" docstring before changing.

    Algorithm:
      1. Strip leading "2 Euros [- ]" prefix.
      2. Combine the leading text (ruler name) with parenthesized qualifier
         (since both are valid distinguishers for standards — unlike
         commemos, where ruler is treated as noise).
      3. Slugify the combination.
      4. Fallback to "1st-type" if nothing extractable.

    Examples (only real Numista catalog_names — verifiable):
      "2 Euros - Albert II (1st map, 1st type, 1st portrait)"
        → "albert-ii-1st-map-1st-type-1st-portrait"
      "2 Euros (2nd map)"            → "2nd-map"
      "2 Euros - Philippe"           → "philippe"
      "2 Euros - Sede Vacante"       → "sede-vacante"
      "2 Euros (Albert II - 2nd portrait)" → "albert-ii-2nd-portrait"
      "2 Euros"                      → "1st-type" (fallback)
      "2 Euros (Il-Kelb Tal-Fenek)"  → "il-kelb-tal-fenek"

    Disambiguation when two nids in the same (country, year) bucket
    produce the same slug:
      - The eurio_id is `{country}-{year}-2eur-standard-{slug}` so year
        already discriminates across years.
      - For an in-bucket collision (same country+year+slug), the caller
        must apply a tiebreaker (suffix `-{numista_id}`) and flag
        needs_review=true. NOT this function's job — it stays pure.
    """
    if not catalog_name:
        return "1st-type"
    text = _VALUE_PREFIX_RX.sub("", catalog_name, count=1).strip()
    # Extract paren content; keep what's outside parens too
    paren_match = re.search(r"\(([^)]+)\)", text)
    paren_content = paren_match.group(1).strip() if paren_match else ""
    leading = re.sub(r"\([^)]*\)", "", text).strip(" -;,")
    combined = " ".join(filter(None, [leading, paren_content]))
    if not combined:
        return "1st-type"
    slug = slugify(combined)
    return slug or "1st-type"


def resolve_slug(numista_id: str, catalog_name: str) -> str:
    """Tier-2 entry point. Honor manual overrides before computing the slug.

    Re-fetch determinism: `numista_id` is stable Numista-side, so the same
    override keeps applying across re-runs.
    """
    if numista_id in MANUAL_NID_SLUG_OVERRIDES:
        return MANUAL_NID_SLUG_OVERRIDES[numista_id]
    return standard_slug(catalog_name)


def standard_eurio_id(country: str, year: int, slug: str) -> str:
    return f"{country.lower()}-{year}-2eur-standard-{slug}"


# ─── Build payloads ──────────────────────────────────────────────────────────


def _extract_theme(catalog_name: str) -> str | None:
    """Theme = ruler + parens content, human-readable. Eg :
       "2 Euros - Albert II (1st map, 1st type, 1st portrait)"
         → "Albert II — 1st map, 1st type, 1st portrait"
    """
    if not catalog_name:
        return None
    text = _VALUE_PREFIX_RX.sub("", catalog_name, count=1).strip()
    paren = re.search(r"\(([^)]+)\)", text)
    paren_content = paren.group(1).strip() if paren else ""
    leading = re.sub(r"\([^)]*\)", "", text).strip(" -;,")
    if leading and paren_content:
        return f"{leading} — {paren_content}"
    return leading or paren_content or None


def build_payloads(records: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Build coin_rows, source_ref_rows, stats."""
    xm = cross_match_wrong_and_new_types(records)
    standards = [r for r in xm["create_as_new_types"] if not r["is_commemorative"]]
    today = date.today().isoformat()

    coin_rows: list[dict] = []
    source_ref_rows: list[dict] = []
    seen: dict[str, str] = {}  # eurio_id → nid (collision tracking inside batch)
    in_batch_collisions: list[tuple[str, str]] = []

    for r in standards:
        country = r["country"]
        year = int(r["year"])
        nid = str(r["numista_id"])
        cat_name = r["catalog_name"]
        slug = resolve_slug(nid, cat_name)
        eid = standard_eurio_id(country, year, slug)
        if eid in seen:
            in_batch_collisions.append((eid, nid))
            continue
        seen[eid] = nid
        theme = _extract_theme(cat_name)
        coin_rows.append({
            "eurio_id": eid,
            "country": country,
            "year": year,
            "face_value": 2.0,
            "currency": "EUR",
            "is_commemorative": False,
            "is_withdrawn": False,
            "collector_only": False,
            "needs_review": False,
            "personal_owned": False,
            "theme": theme,
            "design_description": cat_name,
            "cross_refs": {"numista_id": int(nid)},
            "sources_used": ["numista"],
            "first_seen": today,
            "last_updated": today,
        })
        source_ref_rows.append({
            "coin_type_id": eid,
            "source": "numista",
            "native_id": nid,
            "native_url": None,
        })

    stats = {
        "audit_total_new_type": sum(
            1 for r in records if r["classification"] == "ORPHAN_NEW_TYPE"
        ),
        "absorbed_by_rematch": len(xm["absorbed_nids"]),
        "commemo_created_in_3a": sum(
            1 for r in xm["create_as_new_types"] if r["is_commemorative"]
        ),
        "standards_to_create": len(standards),
        "in_batch_collisions": in_batch_collisions,
        "coin_rows": len(coin_rows),
        "source_ref_rows": len(source_ref_rows),
    }
    return coin_rows, source_ref_rows, stats


# ─── Live DB collision check ─────────────────────────────────────────────────


def fetch_existing_eurio_ids(sb: SupabaseClient, eurio_ids: list[str]) -> set[str]:
    if not eurio_ids:
        return set()
    out: set[str] = set()
    in_list = ",".join(eurio_ids)
    rows = sb.query(
        "coins",
        select="eurio_id",
        params={"eurio_id": f"in.({in_list})"},
    )
    for r in rows:
        out.add(r["eurio_id"])
    return out


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records = load_audit()
    coin_rows, source_ref_rows, stats = build_payloads(records)

    print("=" * 66)
    print(f"  Chunk 3f — STANDARDS orphans  ({'DRY-RUN' if args.dry_run else 'APPLY'})")
    print("=" * 66)
    print(f"  Audit total ORPHAN_NEW_TYPE         : {stats['audit_total_new_type']}")
    print(f"  Absorbed by 3a/3b/3c rematch        : {stats['absorbed_by_rematch']}")
    print(f"  Commémos créées en 3a               : {stats['commemo_created_in_3a']}")
    print(f"  Standards à créer en 3f             : {stats['standards_to_create']}")
    print(f"  In-batch collisions                 : {len(stats['in_batch_collisions'])}")
    print(f"  coins rows ready                    : {stats['coin_rows']}")
    print(f"  coin_source_refs rows ready         : {stats['source_ref_rows']}")
    print()

    if stats["in_batch_collisions"]:
        print("⚠ In-batch eurio_id collisions :")
        for eid, nid in stats["in_batch_collisions"]:
            print(f"  {eid}  (catalog nid={nid})")
        print()

    print("Sample of new standards being created :")
    for r in coin_rows:
        print(f"  {r['eurio_id']:<78s}  nid={r['cross_refs']['numista_id']}")
    print()

    by_country = Counter(r["country"] for r in coin_rows)
    print("New standards per country :")
    for c, n in sorted(by_country.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")
    print()

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1

    sb = SupabaseClient(url, key)
    try:
        existing = fetch_existing_eurio_ids(sb, [r["eurio_id"] for r in coin_rows])
        if existing:
            print(f"⚠ {len(existing)} eurio_ids already exist in coins (will be UPSERTED) :")
            for e in sorted(existing):
                print(f"    {e}")
            print()
        else:
            print("✓ No collisions with existing coins (all 15 are net-new).")
            print()

        if args.dry_run:
            out_path = ML_DIR / "datasets" / "chunk_3f_dryrun.json"
            out_path.write_text(json.dumps({
                "stats": {**stats, "in_batch_collisions": [list(t) for t in stats["in_batch_collisions"]]},
                "coin_rows": coin_rows,
                "source_ref_rows": source_ref_rows,
                "existing_eurio_ids": sorted(existing),
            }, indent=2, ensure_ascii=False))
            print(f"Dry-run snapshot: {out_path}")
            print("\n--dry-run: nothing written. Re-run with --apply to commit.")
            return 0

        # APPLY
        print(f"Upserting {len(coin_rows)} coins…")
        sb.upsert("coins", coin_rows, on_conflict="eurio_id")
        print(f"  ✓ {len(coin_rows)} coins")
        print(f"Upserting {len(source_ref_rows)} coin_source_refs…")
        sb.upsert(
            "coin_source_refs",
            source_ref_rows,
            on_conflict="coin_type_id,source,native_id",
        )
        print(f"  ✓ {len(source_ref_rows)} coin_source_refs")

        print("\nDone.")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
