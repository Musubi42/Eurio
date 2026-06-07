"""Chunk 3a — Crée les Types absents du référentiel V1 pour des nids Numista
déjà présents dans coin_catalog.json mais non promus en eurio_id.

Refs:
  docs/research/referential-v2.md §8 (plan migration)
  ml/datasets/audit_referential_v2.json (audit V2)

Contexte
--------
L'audit V2 a classifié 151 nids Numista comme ORPHAN_NEW_TYPE (pas de slot ref).
Cross-matching avec les IN_REF_WRONG en absorbe ~37 (rematch en 3b). Restent
~114 nids dont 99 commémoratives à créer en Type, 15 standards reportés
(chunk 3f).

Sur les 99 commémos à créer, ~64 sont des joint-issues (Treaty of Rome 2007,
EMU 2009, Euro Cash 2012, EU Flag 2015, Erasmus 2022). Chacune crée un Type
national distinct lié à un même design_group « eu-{theme}-{year} » (D5 du doc).

Ce que fait ce script
---------------------
1. Charge l'audit + applique le cross-matching (NEW_TYPE absorbés par WRONG → 3b)
2. Filtre les NEW_TYPE commémoratives à créer (99)
3. Pour chaque coin :
   a) Détecte si joint-issue → assigne design_group_id
   b) Génère eurio_id canonique
   c) Vérifie absence de collision avec coins existants
4. Bootstrap les 5 design_groups joint-issues s'ils n'existent pas
5. Upsert :
   - design_groups (joint-issues)
   - coins (nouveaux Types, on_conflict=eurio_id)
   - coin_source_refs (numista native_ids correspondants)

Mode `--dry-run` obligatoire avant `--apply`.

Idempotent : tous les writes utilisent upsert. Re-run sans danger.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from serving.supabase_client import SupabaseClient, load_env  # noqa: E402
from referential.audit_apply_common import (  # noqa: E402
    JOINT_ISSUES,
    cross_match_wrong_and_new_types,
    detect_joint_issue,
    eurio_id_from_catalog,
    joint_design_group_id,
    load_audit,
)


# ─── Build payloads ──────────────────────────────────────────────────────────


def _extract_theme(catalog_name: str) -> str | None:
    """Return the parenthesized theme from a Numista name, or None."""
    import re
    m = re.search(r"\(([^)]+)\)", catalog_name or "")
    if m:
        return m.group(1).strip()
    return None


def build_payloads(
    audit_records: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict], dict[str, Any]]:
    """Build the design_groups, coins, coin_source_refs payloads.

    Returns (design_groups_rows, coin_rows, source_ref_rows, skipped, stats).
    """
    xm = cross_match_wrong_and_new_types(audit_records)
    # Only commemo NEW_TYPEs not absorbed into rematches.
    candidates = [
        r for r in xm["create_as_new_types"] if r["is_commemorative"]
    ]

    # Track joint-issue design_groups to insert (once each).
    dg_seen: dict[str, dict] = {}
    coin_rows: list[dict] = []
    source_ref_rows: list[dict] = []
    skipped: list[dict] = []
    collisions: list[tuple[str, str]] = []  # (eurio_id, numista_id_conflict)
    seen_eurio_ids: set[str] = set()

    today = date.today().isoformat()

    for r in candidates:
        country_iso = r["country"]
        year = int(r["year"])
        nid = str(r["numista_id"])
        cat_name = r["catalog_name"]

        eurio_id = eurio_id_from_catalog(country_iso, year, 2.0, cat_name)
        if eurio_id in seen_eurio_ids:
            # Same eurio_id generated twice in this batch (e.g. 2 catalog entries
            # with identical theme in same country/year). Defer to review.
            collisions.append((eurio_id, nid))
            skipped.append({**r, "skip_reason": "duplicate eurio_id in batch"})
            continue
        seen_eurio_ids.add(eurio_id)

        ji = detect_joint_issue(cat_name, year)
        dg_id = None
        if ji:
            theme_slug, designation = ji
            dg_id = joint_design_group_id(theme_slug, year)
            if dg_id not in dg_seen:
                dg_seen[dg_id] = {
                    "id": dg_id,
                    "designation": designation,
                    "description": (
                        "Bootstrap from referential V2 migration 2026-05-15. "
                        "Joint commemorative issue across eurozone members."
                    ),
                    # shared_obverse_url left null — populated later from one
                    # of the members' images.
                }

        theme = _extract_theme(cat_name)

        coin_rows.append({
            "eurio_id": eurio_id,
            "country": country_iso,
            "year": year,
            "face_value": 2.0,
            "currency": "EUR",
            "is_commemorative": True,
            "is_withdrawn": False,
            "collector_only": False,
            "needs_review": False,
            "personal_owned": False,
            "theme": theme,
            "design_description": cat_name,
            "cross_refs": {"numista_id": int(nid)},
            "sources_used": ["numista"],
            "design_group_id": dg_id,
            "first_seen": today,
            "last_updated": today,
        })

        source_ref_rows.append({
            "coin_type_id": eurio_id,
            "source": "numista",
            "native_id": nid,
            "native_url": None,
        })

    stats = {
        "audit_total_new_type": sum(
            1 for r in audit_records if r["classification"] == "ORPHAN_NEW_TYPE"
        ),
        "absorbed_by_rematch": len(xm["absorbed_nids"]),
        "deferred_standards": sum(
            1 for r in xm["create_as_new_types"] if not r["is_commemorative"]
        ),
        "commemo_to_create": len(candidates),
        "coin_rows": len(coin_rows),
        "source_ref_rows": len(source_ref_rows),
        "design_groups_to_upsert": len(dg_seen),
        "collisions": collisions,
    }

    return list(dg_seen.values()), coin_rows, source_ref_rows, skipped, stats


# ─── Collision check (against live DB) ───────────────────────────────────────


def fetch_existing_eurio_ids(sb: SupabaseClient, eurio_ids: list[str]) -> set[str]:
    """Return the subset of eurio_ids that already exist in coins."""
    existing: set[str] = set()
    # Chunk to avoid URL length issues
    for i in range(0, len(eurio_ids), 200):
        chunk = eurio_ids[i:i + 200]
        in_list = ",".join(chunk)
        rows = sb.query(
            "coins",
            select="eurio_id",
            params={"eurio_id": f"in.({in_list})"},
        )
        existing.update(r["eurio_id"] for r in rows)
    return existing


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records = load_audit()
    dg_rows, coin_rows, sref_rows, skipped, stats = build_payloads(records)

    print("=" * 66)
    print(f"  Chunk 3a — CREATE_NEW_TYPE  ({'DRY-RUN' if args.dry_run else 'APPLY'})")
    print("=" * 66)
    print(f"  Audit total ORPHAN_NEW_TYPE       : {stats['audit_total_new_type']}")
    print(f"  Absorbed by 3b rematch            : {stats['absorbed_by_rematch']}")
    print(f"  Standards deferred to chunk 3f    : {stats['deferred_standards']}")
    print(f"  Commemo NEW_TYPEs to create       : {stats['commemo_to_create']}")
    print(f"  In-batch duplicates skipped       : {len(stats['collisions'])}")
    print(f"  coins rows ready                  : {stats['coin_rows']}")
    print(f"  coin_source_refs rows ready       : {stats['source_ref_rows']}")
    print(f"  design_groups to upsert           : {stats['design_groups_to_upsert']}")
    print()

    if stats["collisions"]:
        print("In-batch duplicate eurio_ids (will need review):")
        for eid, nid in stats["collisions"][:10]:
            print(f"  {eid}  (catalog nid={nid})")
        print()

    # Joint-issue summary
    ji_counts = Counter()
    for r in coin_rows:
        if r["design_group_id"]:
            ji_counts[r["design_group_id"]] += 1
    print("Joint-issue distribution :")
    for dg, n in sorted(ji_counts.items(), key=lambda x: -x[1]):
        print(f"  {dg:25s}  {n} coins")
    print()

    # Per country
    by_country = Counter(r["country"] for r in coin_rows)
    print("New Types per country (top 12) :")
    for c, n in sorted(by_country.items(), key=lambda x: -x[1])[:12]:
        print(f"  {c}: {n}")
    print()

    # Sample
    print("Sample of new Types being created (first 12) :")
    for r in coin_rows[:12]:
        dg = r.get("design_group_id") or "-"
        print(
            f"  {r['eurio_id']:60s} | nid={r['cross_refs']['numista_id']:>6} "
            f"| dg={dg}"
        )
    print()

    # Connect to Supabase and check for collisions with already-existing eurio_ids
    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1

    sb = SupabaseClient(url, key)
    try:
        ids_to_check = [r["eurio_id"] for r in coin_rows]
        existing = fetch_existing_eurio_ids(sb, ids_to_check)
        if existing:
            print(f"⚠  {len(existing)} eurio_ids already exist in coins :")
            for e in sorted(existing)[:10]:
                print(f"    {e}")
            print("These will be UPSERTED (overwriting V1 row).")
            print()

        if args.dry_run:
            # Persist a JSON snapshot for offline review
            out = ML_DIR / "datasets" / "chunk_3a_dryrun.json"
            out.write_text(json.dumps({
                "stats": {**stats, "collisions": [list(t) for t in stats["collisions"]]},
                "design_groups": dg_rows,
                "coin_rows": coin_rows,
                "source_ref_rows": sref_rows,
                "existing_eurio_ids": sorted(existing),
            }, indent=2, ensure_ascii=False))
            print(f"Dry-run snapshot written: {out}")
            print("\n--dry-run: nothing written to Supabase. Re-run with --apply to commit.")
            return 0

        # APPLY
        print("Upserting design_groups...")
        if dg_rows:
            sb.upsert("design_groups", dg_rows, on_conflict="id")
            print(f"  ✓ {len(dg_rows)} design_groups")
        print("Upserting coins...")
        sb.upsert("coins", coin_rows, on_conflict="eurio_id")
        print(f"  ✓ {len(coin_rows)} coins")
        print("Upserting coin_source_refs...")
        sb.upsert("coin_source_refs", sref_rows, on_conflict="coin_type_id,source,native_id")
        print(f"  ✓ {len(sref_rows)} coin_source_refs")
        print("\nDone.")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
