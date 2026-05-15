"""Chunk 3e.2 — Enrichit les 32 coins.needs_review avec review_action_hint + review_payload.

Refs:
  docs/research/referential-v2-progress.md §3e
  supabase/migrations/20260516_coins_review_context.sql (schema)
  ml/datasets/audit_referential_v2.json

Contexte
--------
Les 32 coins avec `needs_review = true` viennent de 3 sources :
  - 21 du chunk 3b (IN_REF_WRONG sans rematch candidat)        → action 'rebind'
  -  4 du chunk 3d B2/B3 (nouveaux parents abstraits)           → action 'verify_parent'
  -  7 du chunk 3e.1 (IN_REF_UNCERTAIN non-absorbés par 3c)    → action 'confirm_or_rematch_uncertain'

L'UI admin a besoin d'un hint d'action + d'un payload structuré pour
chaque cas. Ce script backfille les colonnes `review_action_hint` et
`review_payload` ajoutées par la migration 20260516.

Identification de la source
---------------------------
Le `review_reason` texte (déjà écrit par 3b/3d/3e.1) est notre clé :
  - "3b:" prefix       → action 'rebind'
  - "3d:" prefix       → action 'verify_parent' (bucket B2)
  - "3d manual…"       → action 'verify_parent' (bucket B3)
  - "3e: UNCERTAIN"    → action 'confirm_or_rematch_uncertain'

Contrat du payload
------------------
{
  "kind": "rebind" | "verify_parent" | "confirm_or_rematch_uncertain",
  ...fields spécifiques au kind (voir docstrings ci-dessous)
}

Idempotent : ré-run écrase review_payload avec une version fraîche
dérivée de l'état DB actuel + audit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.supabase_client import SupabaseClient, load_env  # noqa: E402
from referential.audit_apply_common import (  # noqa: E402
    cross_match_wrong_and_new_types,
    load_audit,
)
from referential.apply_3e_flag_uncertain import filter_unresolved_uncertain  # noqa: E402


_VARIANT_NOTE_RE = re.compile(r"^Numista nid=(\d+)\s*[—-]\s*(.+)$")


# ─── Payload builders ─────────────────────────────────────────────────────────


def build_rebind_payload(eid: str, xm: dict, coin: dict) -> dict[str, Any]:
    """Payload schema (kind=rebind):

    {
      "kind": "rebind",
      "lost_at": "3b",                       — qui a vidé le nid
      "audit_old_nid": "12345" | null,       — nid Numista jadis bound, perdu en 3b
      "audit_old_catalog_name": str | null,  — son label Numista d'origine
      "current_numista_id": null,            — coins.cross_refs.numista_id (= null après 3b)
    }
    """
    old_nid = xm["old_nids"].get(eid)
    rematch_det = xm["rematch_details"].get(eid) or {}
    return {
        "kind": "rebind",
        "lost_at": "3b",
        "audit_old_nid": str(old_nid) if old_nid is not None else None,
        "audit_old_catalog_name": rematch_det.get("old"),
        "current_numista_id": (coin.get("cross_refs") or {}).get("numista_id"),
    }


def build_verify_parent_payload(
    eid: str,
    coin: dict,
    review_reason: str,
    variants_rows: list[dict],
) -> dict[str, Any]:
    """Payload schema (kind=verify_parent):

    {
      "kind": "verify_parent",
      "bucket": "B2" | "B3",
      "primary_numista_id": "12345",         — coins.cross_refs.numista_id
      "member_variants": [
        {"variant_id": "...", "finish": "...", "numista_id": "...", "catalog_name": "..."}
      ],
      "review_reason_seed": str,             — original reason from 3d
    }
    """
    bucket = "B3" if "manual override" in review_reason else "B2"
    members: list[dict[str, Any]] = []
    for v in variants_rows:
        notes = v.get("notes") or ""
        m = _VARIANT_NOTE_RE.match(notes)
        if not m:
            continue
        members.append({
            "variant_id": v["id"],
            "finish": v["finish"],
            "numista_id": m.group(1),
            "catalog_name": m.group(2).strip(),
        })
    primary_nid = (coin.get("cross_refs") or {}).get("numista_id")
    return {
        "kind": "verify_parent",
        "bucket": bucket,
        "primary_numista_id": str(primary_nid) if primary_nid is not None else None,
        "member_variants": members,
        "review_reason_seed": review_reason,
    }


def build_uncertain_payload(
    eid: str,
    coin: dict,
    audit_record: dict,
) -> dict[str, Any]:
    """Payload schema (kind=confirm_or_rematch_uncertain):

    {
      "kind": "confirm_or_rematch_uncertain",
      "suspect_numista_id": "11526",         — nid flagué par l'audit
      "suspect_catalog_name": "...",         — son label Numista
      "current_numista_id": "67890",         — ce que V1 a actuellement
      "country": "fr",
      "year": 2010,
    }
    """
    nid = audit_record["numista_id"]
    return {
        "kind": "confirm_or_rematch_uncertain",
        "suspect_numista_id": str(nid),
        "suspect_catalog_name": audit_record.get("catalog_name"),
        "current_numista_id": (coin.get("cross_refs") or {}).get("numista_id"),
        "country": audit_record.get("country"),
        "year": audit_record.get("year"),
    }


# ─── Live state fetch ─────────────────────────────────────────────────────────


def fetch_needs_review_coins(sb: SupabaseClient) -> list[dict]:
    return sb.query(
        "coins",
        select="eurio_id,country,year,theme,cross_refs,review_reason,review_action_hint,review_payload",
        params={"needs_review": "eq.true"},
    )


def fetch_variants_for(
    sb: SupabaseClient, parent_eids: list[str]
) -> dict[str, list[dict]]:
    if not parent_eids:
        return {}
    in_list = ",".join(parent_eids)
    rows = sb.query(
        "coin_variants",
        select="id,parent_type_id,finish,notes",
        params={"parent_type_id": f"in.({in_list})"},
    )
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["parent_type_id"], []).append(r)
    return out


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    audit_records = load_audit()
    xm = cross_match_wrong_and_new_types(audit_records)
    uncertain_unresolved = filter_unresolved_uncertain(audit_records)
    uncertain_by_eid = {
        r["currently_matched_eurio_id"]: r for r in uncertain_unresolved
    }

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1
    sb = SupabaseClient(url, key)

    try:
        coins = fetch_needs_review_coins(sb)
        print("=" * 66)
        print(f"  Chunk 3e.2 — ENRICH CONTEXT  ({'DRY-RUN' if args.dry_run else 'APPLY'})")
        print("=" * 66)
        print(f"  coins.needs_review = true                : {len(coins)}")
        print()

        # Pre-fetch all variants for B2/B3 parents in one round-trip
        parent_eids = [
            c["eurio_id"] for c in coins
            if (c.get("review_reason") or "").startswith("3d")
        ]
        variants_by_parent = fetch_variants_for(sb, parent_eids)

        patches: list[tuple[str, str, dict]] = []  # (eid, hint, payload)
        unknown: list[tuple[str, str]] = []

        for c in coins:
            eid = c["eurio_id"]
            rr = (c.get("review_reason") or "").strip()
            if rr.startswith("3b:"):
                payload = build_rebind_payload(eid, xm, c)
                hint = "rebind"
            elif rr.startswith("3d"):
                payload = build_verify_parent_payload(
                    eid, c, rr, variants_by_parent.get(eid, [])
                )
                hint = "verify_parent"
            elif rr.startswith("3e:"):
                a = uncertain_by_eid.get(eid)
                if not a:
                    unknown.append((eid, "3e flagged but not in audit UNCERTAIN"))
                    continue
                payload = build_uncertain_payload(eid, c, a)
                hint = "confirm_or_rematch_uncertain"
            else:
                unknown.append((eid, rr[:80] or "(empty review_reason)"))
                continue
            patches.append((eid, hint, payload))

        # Histogram
        by_hint: dict[str, int] = {}
        for _, h, _ in patches:
            by_hint[h] = by_hint.get(h, 0) + 1

        print("Patches by action hint :")
        for h in ("rebind", "verify_parent", "confirm_or_rematch_uncertain"):
            print(f"  {h:35s}  {by_hint.get(h, 0)}")
        print()

        if unknown:
            print(f"⚠  {len(unknown)} coins with unrecognized review_reason :")
            for eid, rr in unknown:
                print(f"    {eid}  «{rr}»")
            print()

        # Sample preview
        print("Sample patches (first 6) :")
        for eid, hint, payload in patches[:6]:
            print(f"  {eid}")
            print(f"    hint    : {hint}")
            print(f"    payload : {json.dumps(payload, ensure_ascii=False)[:140]}")
        print()

        snapshot = {
            "applied_at": date.today().isoformat(),
            "summary": {
                "total": len(patches),
                "by_hint": by_hint,
                "unknown": len(unknown),
            },
            "patches": [
                {"eurio_id": eid, "review_action_hint": h, "review_payload": p}
                for eid, h, p in patches
            ],
        }

        if args.dry_run:
            out = ML_DIR / "datasets" / "chunk_3e2_dryrun.json"
            out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
            print(f"Snapshot written: {out}")
            print("\n--dry-run: nothing written to Supabase. Re-run with --apply to commit.")
            return 0

        print(f"PATCHing {len(patches)} coins…")
        for eid, hint, payload in patches:
            sb.patch(
                "coins",
                filters={"eurio_id": f"eq.{eid}"},
                payload={
                    "review_action_hint": hint,
                    "review_payload": payload,
                },
            )
        print(f"  ✓ {len(patches)} coins patched\n")

        # Verify counts
        rebind_count = sb.count(
            "coins", params={"review_action_hint": "eq.rebind"}
        )
        verify_count = sb.count(
            "coins", params={"review_action_hint": "eq.verify_parent"}
        )
        uncertain_count = sb.count(
            "coins",
            params={"review_action_hint": "eq.confirm_or_rematch_uncertain"},
        )
        print("Final DB state :")
        print(f"  review_action_hint=rebind                       : {rebind_count}")
        print(f"  review_action_hint=verify_parent                : {verify_count}")
        print(f"  review_action_hint=confirm_or_rematch_uncertain : {uncertain_count}")
        print(f"  total enriched                                  : "
              f"{rebind_count + verify_count + uncertain_count}")
        print("\nDone.")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
