"""Chunk 3e.1 — Flag les 7 IN_REF_UNCERTAIN non-absorbés en needs_review.

Refs:
  docs/research/referential-v2-progress.md §6.3 (3e review queue)
  docs/research/referential-v2.md §1.2 (audit IN_REF_UNCERTAIN)
  ml/datasets/audit_referential_v2.json
  ml/referential/audit_apply_common.py (cross_match_wrong_and_new_types)

Contexte
--------
L'audit V2 a classifié 9 nids Numista comme IN_REF_UNCERTAIN — leur theme
overlap (0.20 ≤ score < 0.40) avec un slot V1 existant est dans la zone
frontière : pas assez net pour un rematch automatique, trop pour ignorer.

Chunk 3c en a absorbé 2 (Bucket C : score post-margin ≥ 0.5 → rematch
appliqué). Les 7 restants n'ont pas été touchés — le slot V1 garde son
mapping d'origine, et le nid Numista UNCERTAIN reste candidat à un revue
humaine.

Ce script flagge les 7 V1 slots concernés avec needs_review=true et un
review_reason qui pointe explicitement le nid suspect. La résolution
manuelle se fera via l'UI admin (3e.4).

Ce que fait ce script
---------------------
1. Charge l'audit + cross-match (mêmes seuils que 3c)
2. Filtre les UNCERTAIN non-absorbés → 7 cas
3. Pour chaque : PATCH coins.needs_review=true + review_reason
4. Mode --dry-run obligatoire avant --apply
5. Snapshot JSON pour audit hors ligne

Idempotent : ré-run sans danger (PATCH idempotent, le review_reason
écrase mais reste cohérent).
"""

from __future__ import annotations

import argparse
import json
import sys
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


def filter_unresolved_uncertain(records: list[dict]) -> list[dict]:
    """Return audit records classified IN_REF_UNCERTAIN that 3c did NOT absorb.

    An UNCERTAIN is absorbed iff its `currently_matched_eurio_id` ended up in
    cross_match["rematches"] with by_source_class == "IN_REF_UNCERTAIN".
    """
    xm = cross_match_wrong_and_new_types(records)
    absorbed_eids = {
        eid for eid, cls in xm["by_source_class"].items()
        if cls == "IN_REF_UNCERTAIN"
    }
    return [
        r for r in records
        if r["classification"] == "IN_REF_UNCERTAIN"
        and r["currently_matched_eurio_id"] not in absorbed_eids
    ]


def build_review_reason(audit_record: dict) -> str:
    """Compose a structured review_reason that the UI can parse and display."""
    nid = audit_record["numista_id"]
    catalog = audit_record.get("catalog_name", "?")
    return (
        f"3e: UNCERTAIN — audit a flaggé un overlap de thème entre ce Type et "
        f"Numista nid={nid} ({catalog}). Vérifier le mapping (rebind, "
        f"merge, ou confirm as-is)."
    )


def fetch_live_state(sb: SupabaseClient, eids: list[str]) -> dict[str, dict]:
    """Return {eurio_id: row} for the V1 slots we're about to flag."""
    if not eids:
        return {}
    in_list = ",".join(eids)
    rows = sb.query(
        "coins",
        select="eurio_id,country,year,theme,cross_refs,needs_review,review_reason",
        params={"eurio_id": f"in.({in_list})"},
    )
    return {r["eurio_id"]: r for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records = load_audit()
    uncertain_unresolved = filter_unresolved_uncertain(records)

    print("=" * 66)
    print(f"  Chunk 3e.1 — FLAG UNCERTAIN  ({'DRY-RUN' if args.dry_run else 'APPLY'})")
    print("=" * 66)
    print(f"  Audit total IN_REF_UNCERTAIN         : "
          f"{sum(1 for r in records if r['classification'] == 'IN_REF_UNCERTAIN')}")
    print(f"  Absorbed by 3c (Bucket C rematch)    : "
          f"{sum(1 for r in records if r['classification'] == 'IN_REF_UNCERTAIN') - len(uncertain_unresolved)}")
    print(f"  Non-absorbed to flag in 3e.1         : {len(uncertain_unresolved)}")
    print()

    print("Cases to flag (V1 slot ← suspect Numista nid):")
    for r in uncertain_unresolved:
        eid = r["currently_matched_eurio_id"]
        nid = r["numista_id"]
        cat = (r.get("catalog_name") or "?")[:60]
        print(f"  {eid}")
        print(f"    ↑ suspect: nid={nid} ({cat})")
    print()

    today = date.today().isoformat()
    eids = [r["currently_matched_eurio_id"] for r in uncertain_unresolved]

    snapshot = {
        "applied_at": today,
        "items": [
            {
                "eurio_id": r["currently_matched_eurio_id"],
                "suspect_numista_id": r["numista_id"],
                "suspect_catalog_name": r.get("catalog_name"),
                "country": r.get("country"),
                "year": r.get("year"),
                "review_reason": build_review_reason(r),
            }
            for r in uncertain_unresolved
        ],
    }

    if args.dry_run:
        out = ML_DIR / "datasets" / "chunk_3e1_dryrun.json"
        out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
        print(f"Snapshot written: {out}")
        print("\n--dry-run: nothing written to Supabase. Re-run with --apply to commit.")
        return 0

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1

    sb = SupabaseClient(url, key)
    try:
        live = fetch_live_state(sb, eids)
        missing = [eid for eid in eids if eid not in live]
        if missing:
            print(f"⚠  {len(missing)} eurio_ids absent de coins (skipped):")
            for eid in missing:
                print(f"    {eid}")
            print()

        already_flagged_other_reason: list[tuple[str, str]] = []
        for eid in eids:
            row = live.get(eid)
            if row and row.get("needs_review") and row.get("review_reason"):
                rr = row["review_reason"]
                if not rr.startswith("3e:"):
                    already_flagged_other_reason.append((eid, rr[:80]))
        if already_flagged_other_reason:
            print(f"⚠  {len(already_flagged_other_reason)} déjà flaggés par un autre chunk "
                  f"(3e va écraser le reason — vérifier que c'est OK) :")
            for eid, rr in already_flagged_other_reason:
                print(f"    {eid}  «{rr}»")
            print()

        print(f"Applying needs_review=true to {len(uncertain_unresolved)} coins…")
        applied = 0
        for r in uncertain_unresolved:
            eid = r["currently_matched_eurio_id"]
            if eid not in live:
                continue
            sb.patch(
                "coins",
                filters={"eurio_id": f"eq.{eid}"},
                payload={
                    "needs_review": True,
                    "review_reason": build_review_reason(r),
                    "last_updated": today,
                },
            )
            applied += 1
        print(f"  ✓ {applied} coins patched")

        # Final count check
        total_flagged = sb.count(
            "coins", params={"needs_review": "eq.true"}
        )
        print(f"\nTotal coins.needs_review=true now : {total_flagged}")
        print("(attendu après 3e.1 : 32 = 21 [3b] + 4 [3d B2/B3] + 7 [3e.1])")
        print("\nDone.")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
