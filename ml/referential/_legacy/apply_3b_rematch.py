"""Chunk 3b — Démêler les matchings sémantiquement faux.

Refs:
  docs/research/referential-v2.md §8
  ml/datasets/audit_referential_v2.json
  ml/referential/audit_apply_common.py (cross_match_wrong_and_new_types)

Contexte
--------
L'audit a identifié 58 IN_REF_WRONG (theme overlap < 0.20 entre l'eurio_id V1
et le numista_id auquel il est actuellement matché). Exemples : DE 2018
Helmut Schmidt matché à "Bundesländer Berlin", BE 2014 Croix-Rouge matché à
"WW I Anniversary".

Le cross-matching de 3a/common a réparti en :
  - 47 rematches  (eurio_id ↔ nouveau nid trouvé dans le bucket country/year)
  - 21 unresolved (pas de nid candidat valide → null + needs_review=true)

Ce script applique uniquement la branche WRONG (rematches qui viennent d'une
classification IN_REF_WRONG). Les cas IN_REF_BUT_VARIANT / IN_REF_UNCERTAIN
absorbés par le cross-matching seront traités en 3c — la rematch pour eux
n'est qu'une moitié du fix, l'autre étant de pousser le nid variant dans
coin_variants.

Ce que fait ce script
---------------------
Pour chaque rematch WRONG :
  1. PATCH coins.cross_refs.numista_id = new_nid + last_updated = today
  2. Optionnel : si theme V1 ne correspond plus, peut écraser theme (off par défaut)
  3. INSERT coin_source_refs (eurio_id, 'numista', new_nid)
  4. DELETE coin_source_refs (eurio_id, 'numista', old_nid)  ← cleanup OLD

Pour chaque unresolved WRONG :
  1. PATCH coins.cross_refs (numista_id removed) + needs_review=true +
     review_reason="3b: no rematch candidate found in country/year bucket"
  2. DELETE coin_source_refs (eurio_id, 'numista', old_nid)

Mode `--dry-run` obligatoire.
Idempotent : re-run sans danger (PATCH/upsert/delete sont idempotents).
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

from serving.supabase_client import SupabaseClient, load_env  # noqa: E402
from referential.audit_apply_common import (  # noqa: E402
    cross_match_wrong_and_new_types,
    load_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records = load_audit()
    xm = cross_match_wrong_and_new_types(records)

    # Filter to only WRONG-class rematches and unresolved (this script's scope)
    wrong_rematches = {
        eid: nid for eid, nid in xm["rematches"].items()
        if xm["by_source_class"].get(eid) == "IN_REF_WRONG"
    }
    unresolved = xm["unresolved_wrong"]

    print("=" * 66)
    print(f"  Chunk 3b — REMATCH  ({'DRY-RUN' if args.dry_run else 'APPLY'})")
    print("=" * 66)
    print(f"  IN_REF_WRONG rematches to apply       : {len(wrong_rematches)}")
    print(f"  IN_REF_WRONG unresolved (null + flag) : {len(unresolved)}")
    print(f"  (BUT_VARIANT / UNCERTAIN rematches deferred to chunk 3c: "
          f"{len(xm['rematches']) - len(wrong_rematches)})")
    print()

    # Print preview
    print("Sample rematches (first 10):")
    for eid in list(wrong_rematches.keys())[:10]:
        new_nid = wrong_rematches[eid]
        old_nid = xm["old_nids"][eid]
        det = xm["rematch_details"][eid]
        print(f"  {eid}")
        print(f"    OLD nid={old_nid} ({det['old'][:55]})")
        print(f"    NEW nid={new_nid} ({det['new'][:55]})")
    print()
    print("Sample unresolved (first 8):")
    for eid in unresolved[:8]:
        old_nid = xm["old_nids"].get(eid, "?")
        det = xm["rematch_details"].get(eid, {})
        print(f"  {eid}")
        print(f"    OLD nid={old_nid} ({(det.get('old') or '?')[:55]})")
    print()

    today = date.today().isoformat()

    # Persist a snapshot for offline review
    snapshot = {
        "rematches": [
            {
                "eurio_id": eid,
                "old_nid": xm["old_nids"][eid],
                "new_nid": nid,
                "old_catalog_name": xm["rematch_details"][eid]["old"],
                "new_catalog_name": xm["rematch_details"][eid]["new"],
            }
            for eid, nid in wrong_rematches.items()
        ],
        "unresolved": [
            {
                "eurio_id": eid,
                "old_nid": xm["old_nids"].get(eid),
                "old_catalog_name": (xm["rematch_details"].get(eid) or {}).get("old"),
            }
            for eid in unresolved
        ],
    }

    if args.dry_run:
        out = ML_DIR / "datasets" / "chunk_3b_dryrun.json"
        out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
        print(f"Snapshot written: {out}")
        print("\n--dry-run: nothing written. Re-run with --apply to commit.")
        return 0

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1
    sb = SupabaseClient(url, key)

    try:
        # ── Apply rematches ──
        print(f"Applying {len(wrong_rematches)} rematches...")
        all_eids = list(wrong_rematches.keys()) + unresolved
        # Fetch current cross_refs for all impacted coins
        in_list = ",".join(all_eids)
        current = {
            r["eurio_id"]: r
            for r in sb.query(
                "coins",
                select="eurio_id,cross_refs",
                params={"eurio_id": f"in.({in_list})"},
            )
        }

        new_refs: list[dict] = []

        for eid, new_nid in wrong_rematches.items():
            old_nid = xm["old_nids"][eid]
            cur = current.get(eid)
            if not cur:
                print(f"  ⚠ {eid} not found in coins, skipping")
                continue
            cross_refs = dict(cur.get("cross_refs") or {})
            cross_refs["numista_id"] = int(new_nid)
            sb.patch(
                "coins",
                filters={"eurio_id": f"eq.{eid}"},
                payload={
                    "cross_refs": cross_refs,
                    "last_updated": today,
                    "needs_review": False,
                    "review_reason": None,
                },
            )
            new_refs.append({
                "coin_type_id": eid,
                "source": "numista",
                "native_id": str(new_nid),
                "native_url": None,
            })
            # DELETE the OLD coin_source_refs entry (it pointed to wrong nid)
            sb.delete(
                "coin_source_refs",
                filters={
                    "coin_type_id": f"eq.{eid}",
                    "source": "eq.numista",
                    "native_id": f"eq.{old_nid}",
                },
            )
        print(f"  ✓ {len(wrong_rematches)} rematches patched")

        if new_refs:
            sb.upsert(
                "coin_source_refs",
                new_refs,
                on_conflict="coin_type_id,source,native_id",
            )
            print(f"  ✓ {len(new_refs)} new coin_source_refs upserted")

        # ── Apply unresolved (null + needs_review) ──
        print(f"\nApplying {len(unresolved)} unresolved (null + needs_review)...")
        for eid in unresolved:
            old_nid = xm["old_nids"].get(eid)
            cur = current.get(eid)
            if not cur:
                print(f"  ⚠ {eid} not found in coins, skipping")
                continue
            cross_refs = dict(cur.get("cross_refs") or {})
            cross_refs.pop("numista_id", None)
            sb.patch(
                "coins",
                filters={"eurio_id": f"eq.{eid}"},
                payload={
                    "cross_refs": cross_refs,
                    "last_updated": today,
                    "needs_review": True,
                    "review_reason": (
                        "3b: rematch failed — no Numista candidate matched the "
                        "expected design in this country/year bucket"
                    ),
                },
            )
            if old_nid:
                sb.delete(
                    "coin_source_refs",
                    filters={
                        "coin_type_id": f"eq.{eid}",
                        "source": "eq.numista",
                        "native_id": f"eq.{old_nid}",
                    },
                )
        print(f"  ✓ {len(unresolved)} unresolved patched")

        print("\nDone.")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
