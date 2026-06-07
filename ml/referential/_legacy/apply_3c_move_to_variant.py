"""Chunk 3c — MOVE_TO_VARIANT × 15 + UNCERTAIN absorbed × 2.

Refs:
  docs/research/referential-v2.md (decisions D1–D8)
  docs/research/referential-v2-progress.md §6.1 (cross_refs policy)
  ml/datasets/audit_referential_v2.json
  ml/referential/audit_apply_common.py (cross_match_wrong_and_new_types)

Contexte
--------
L'audit a identifié 15 IN_REF_BUT_VARIANT (V1 entry pointing at a Numista
variant nid instead of the classic) et 9 IN_REF_UNCERTAIN (theme overlap
between 0.20 and 0.40). Cross-matching produit 3 buckets pour 3c :

  Bucket A — BUT_VARIANT absorbés (8) : V1 → rematch vers classic NEW_TYPE
    qui était dans le pool 3a. On switch cross_refs.numista_id (variant → classic),
    on ajoute un row coin_variants pour le variant_nid (finish=variant_label),
    on ajoute le classic_nid comme 2e source_ref. Le variant_nid source_ref
    existant (de 2c) est conservé.

  Bucket B — BUT_VARIANT non absorbés (7) : pas de classic candidat trouvé
    par cross-match. V1 garde son cross_refs intact (default reco §6.1).
    On ajoute juste le row coin_variants. Le source_ref du variant_nid existe
    déjà depuis 2c, donc rien à upsert là.

  Bucket C — UNCERTAIN absorbés (2) : pas de variant. Comportement strict 3b
    pour WRONG (PATCH cross_refs vers le rematch_nid, swap source_refs).

Ce que fait ce script
---------------------
1. Charge l'audit + cross_match → catégorise en 3 buckets.
2. Live read coins / coin_variants pour préview + idempotency :
   - cross_refs actuel pour chaque eid impacté
   - coin_variants existants par parent (slug collision)
3. Construit payloads : variant rows, source_ref rows, rematch actions.
4. Persist `chunk_3c_dryrun.json` en --dry-run.
5. En --apply : upsert variants, upsert source_refs, PATCH coins (Bucket A puis C),
   DELETE old source_refs (Bucket C only — Bucket A garde le variant_nid ref).

Mode `--dry-run` obligatoire avant `--apply`.
Idempotent : tous les writes utilisent upsert / PATCH par eid.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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


# ─── Bucket categorization ───────────────────────────────────────────────────


def categorize(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (bucket_a, bucket_b, bucket_c) — see module docstring for semantics."""
    xm = cross_match_wrong_and_new_types(records)
    bucket_a: list[dict] = []
    bucket_b: list[dict] = []
    bucket_c: list[dict] = []
    for r in records:
        cl = r["classification"]
        eid = r.get("currently_matched_eurio_id")
        if cl == "IN_REF_BUT_VARIANT":
            absorbed = (
                eid in xm["rematches"]
                and xm["by_source_class"].get(eid) == "IN_REF_BUT_VARIANT"
            )
            if absorbed:
                bucket_a.append({**r, "classic_nid": str(xm["rematches"][eid])})
            else:
                bucket_b.append({**r})
        elif cl == "IN_REF_UNCERTAIN":
            absorbed = (
                eid in xm["rematches"]
                and xm["by_source_class"].get(eid) == "IN_REF_UNCERTAIN"
            )
            if absorbed:
                bucket_c.append({**r, "rematch_nid": str(xm["rematches"][eid])})
    return bucket_a, bucket_b, bucket_c


# ─── Slug allocator ──────────────────────────────────────────────────────────


def allocate_variant_slug(parent_eid: str, finish: str, taken: set[str]) -> str:
    """Return a free slug `{parent}/{finish}` or `{parent}/{finish}-{seq}`."""
    base = f"{parent_eid}/{finish}"
    if base not in taken:
        return base
    seq = 1
    while True:
        cand = f"{base}-{seq}"
        if cand not in taken:
            return cand
        seq += 1


# ─── Live DB queries ─────────────────────────────────────────────────────────


def fetch_existing_variants(
    sb: SupabaseClient, parents: list[str]
) -> dict[str, set[str]]:
    """Return {parent_eid: set(variant_id)} for existing rows on these parents."""
    if not parents:
        return {}
    out: dict[str, set[str]] = {}
    in_list = ",".join(parents)
    rows = sb.query(
        "coin_variants",
        select="id,parent_type_id",
        params={"parent_type_id": f"in.({in_list})"},
    )
    for row in rows:
        out.setdefault(row["parent_type_id"], set()).add(row["id"])
    return out


def fetch_live_cross_refs(
    sb: SupabaseClient, eids: list[str]
) -> dict[str, dict]:
    """Return {eid: row} with cross_refs / needs_review for the given eurio_ids."""
    if not eids:
        return {}
    in_list = ",".join(eids)
    rows = sb.query(
        "coins",
        select="eurio_id,cross_refs,needs_review",
        params={"eurio_id": f"in.({in_list})"},
    )
    return {r["eurio_id"]: r for r in rows}


# ─── Payload builder ─────────────────────────────────────────────────────────


def build_payloads(
    bucket_a: list[dict],
    bucket_b: list[dict],
    bucket_c: list[dict],
    existing_variants: dict[str, set[str]],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Build variant_rows, classic_source_ref_rows, rematch_actions_a, rematch_actions_c."""
    variant_rows: list[dict] = []
    classic_source_ref_rows: list[dict] = []
    rematch_actions_a: list[dict] = []
    rematch_actions_c: list[dict] = []

    # Slug allocator state — seed with already-existing variants per parent.
    allocated: dict[str, set[str]] = {p: set(s) for p, s in existing_variants.items()}

    def make_variant_row(parent: str, finish: str, nid: str, name: str) -> dict:
        taken = allocated.setdefault(parent, set())
        slug = allocate_variant_slug(parent, finish, taken)
        taken.add(slug)
        return {
            "id": slug,
            "parent_type_id": parent,
            "finish": finish,
            "notes": f"Numista nid={nid} — {name}",
        }

    # Bucket A — variant + rematch (variant_nid → classic_nid)
    for r in bucket_a:
        parent = r["currently_matched_eurio_id"]
        variant_rows.append(make_variant_row(
            parent, r["variant_label"], r["numista_id"], r["catalog_name"],
        ))
        classic_source_ref_rows.append({
            "coin_type_id": parent,
            "source": "numista",
            "native_id": r["classic_nid"],
            "native_url": None,
        })
        rematch_actions_a.append({
            "eurio_id": parent,
            "old_nid": str(r["numista_id"]),
            "new_nid": r["classic_nid"],
            "catalog_name": r["catalog_name"],
        })

    # Bucket B — variant only (V1 cross_refs untouched)
    for r in bucket_b:
        parent = r["currently_matched_eurio_id"]
        variant_rows.append(make_variant_row(
            parent, r["variant_label"], r["numista_id"], r["catalog_name"],
        ))

    # Bucket C — UNCERTAIN rematch only (no variant row, swap source_refs)
    for r in bucket_c:
        rematch_actions_c.append({
            "eurio_id": r["currently_matched_eurio_id"],
            "old_nid": str(r["numista_id"]),
            "new_nid": r["rematch_nid"],
            "catalog_name": r["catalog_name"],
        })

    return variant_rows, classic_source_ref_rows, rematch_actions_a, rematch_actions_c


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records = load_audit()
    bucket_a, bucket_b, bucket_c = categorize(records)

    print("=" * 66)
    print(f"  Chunk 3c — MOVE_TO_VARIANT  ({'DRY-RUN' if args.dry_run else 'APPLY'})")
    print("=" * 66)
    print(f"  Bucket A (BUT_VARIANT absorbed → rematch + variant) : {len(bucket_a)}")
    print(f"  Bucket B (BUT_VARIANT not absorbed → variant only)  : {len(bucket_b)}")
    print(f"  Bucket C (UNCERTAIN absorbed → rematch only)        : {len(bucket_c)}")
    print(f"  Total coin_variants rows                            : "
          f"{len(bucket_a) + len(bucket_b)}")
    print()

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1

    sb = SupabaseClient(url, key)
    try:
        all_parents = sorted({
            r["currently_matched_eurio_id"] for r in bucket_a + bucket_b
        })
        existing_variants = fetch_existing_variants(sb, all_parents)

        all_impacted_eids = sorted({
            r["currently_matched_eurio_id"]
            for r in bucket_a + bucket_b + bucket_c
        })
        live = fetch_live_cross_refs(sb, all_impacted_eids)

        variant_rows, classic_sref_rows, rematch_a, rematch_c = build_payloads(
            bucket_a, bucket_b, bucket_c, existing_variants,
        )

        # ── Live DB previews ──
        print("Bucket A — rematch (variant_nid → classic_nid) + variant insert :")
        for ra in rematch_a:
            cur = (live.get(ra["eurio_id"]) or {}).get("cross_refs") or {}
            cur_nid = cur.get("numista_id")
            tag = "OK" if str(cur_nid) == ra["old_nid"] else "DRIFT"
            print(f"  [{tag}] {ra['eurio_id']}")
            print(f"     live cross_refs.numista_id : {cur_nid}")
            print(f"     audit variant nid           : {ra['old_nid']}")
            print(f"     classic nid (3a candidate)  : {ra['new_nid']}")
            print(f"     name : {ra['catalog_name'][:60]}")
        print()

        print("Bucket B — variant only (V1 cross_refs left untouched) :")
        for r in bucket_b:
            eid = r["currently_matched_eurio_id"]
            cur = (live.get(eid) or {}).get("cross_refs") or {}
            cur_nid = cur.get("numista_id")
            audit_nid = int(r["numista_id"])
            tag = "EQ" if cur_nid == audit_nid else "DIFF"
            print(f"  [{tag}] {eid}")
            print(f"     live cross_refs.numista_id : {cur_nid}")
            print(f"     audit variant nid           : {audit_nid}")
            print(f"     finish={r['variant_label']:<8}  ({r['catalog_name'][:55]})")
        print()

        print("Bucket C — UNCERTAIN rematch (idem 3b WRONG) :")
        for rc in rematch_c:
            cur = (live.get(rc["eurio_id"]) or {}).get("cross_refs") or {}
            cur_nid = cur.get("numista_id")
            tag = "OK" if str(cur_nid) == rc["old_nid"] else "DRIFT"
            print(f"  [{tag}] {rc['eurio_id']}")
            print(f"     live cross_refs.numista_id : {cur_nid}")
            print(f"     audit nid (old)             : {rc['old_nid']}")
            print(f"     rematch nid (new)           : {rc['new_nid']}")
            print(f"     name : {rc['catalog_name'][:60]}")
        print()

        # ── Variant slug summary ──
        print("Variant slugs to insert :")
        for v in variant_rows:
            print(f"  {v['id']:<70s}  finish={v['finish']}")
        print()

        if any(existing_variants.values()):
            print("⚠  Existing coin_variants on impacted parents :")
            for p, ids in sorted(existing_variants.items()):
                if ids:
                    print(f"  {p}: {sorted(ids)}")
            print()
        else:
            print("✓ No existing coin_variants on impacted parents (no slug collisions).")
            print()

        finish_counts = Counter(v["finish"] for v in variant_rows)
        print("Variant finish distribution :")
        for f, n in sorted(finish_counts.items(), key=lambda x: -x[1]):
            print(f"  {f:<10} {n}")
        print()

        if args.dry_run:
            out_path = ML_DIR / "datasets" / "chunk_3c_dryrun.json"
            out_path.write_text(json.dumps({
                "bucket_a": bucket_a,
                "bucket_b": bucket_b,
                "bucket_c": bucket_c,
                "variant_rows": variant_rows,
                "classic_source_ref_rows": classic_sref_rows,
                "rematch_actions_a": rematch_a,
                "rematch_actions_c": rematch_c,
                "live_cross_refs": {
                    eid: {
                        "cross_refs": (live.get(eid) or {}).get("cross_refs"),
                        "needs_review": (live.get(eid) or {}).get("needs_review"),
                    }
                    for eid in all_impacted_eids
                },
                "existing_variants": {p: sorted(s) for p, s in existing_variants.items()},
            }, indent=2, ensure_ascii=False))
            print(f"Dry-run snapshot: {out_path}")
            print("\n--dry-run: nothing written to Supabase. Re-run with --apply to commit.")
            return 0

        # ─── APPLY ───
        today = date.today().isoformat()

        # 1. Insert all coin_variants (Bucket A + B)
        if variant_rows:
            print(f"Upserting {len(variant_rows)} coin_variants…")
            sb.upsert("coin_variants", variant_rows, on_conflict="id")
            print(f"  ✓ {len(variant_rows)} coin_variants")

        # 2. Bucket A: insert classic_nid as 2nd source_ref under V1's parent.
        #    The variant_nid source_ref already exists (from 2c) and is kept.
        if classic_sref_rows:
            print(f"Upserting {len(classic_sref_rows)} new classic source_refs (Bucket A)…")
            sb.upsert(
                "coin_source_refs",
                classic_sref_rows,
                on_conflict="coin_type_id,source,native_id",
            )
            print(f"  ✓ {len(classic_sref_rows)} source_refs")

        # 3. Bucket A rematches: PATCH coins.cross_refs.numista_id → classic_nid
        print(f"Patching {len(rematch_a)} bucket-A coins (cross_refs swap)…")
        for ra in rematch_a:
            cur = live.get(ra["eurio_id"])
            if not cur:
                print(f"  ⚠ {ra['eurio_id']} not found, skipping")
                continue
            cross_refs = dict(cur.get("cross_refs") or {})
            cross_refs["numista_id"] = int(ra["new_nid"])
            sb.patch(
                "coins",
                filters={"eurio_id": f"eq.{ra['eurio_id']}"},
                payload={
                    "cross_refs": cross_refs,
                    "last_updated": today,
                    "needs_review": False,
                    "review_reason": None,
                },
            )
        print(f"  ✓ {len(rematch_a)} bucket-A rematches patched")

        # 4. Bucket C UNCERTAIN rematches: PATCH coins + swap source_refs
        print(f"Patching {len(rematch_c)} bucket-C UNCERTAIN coins…")
        new_c_refs: list[dict] = []
        for rc in rematch_c:
            cur = live.get(rc["eurio_id"])
            if not cur:
                print(f"  ⚠ {rc['eurio_id']} not found, skipping")
                continue
            cross_refs = dict(cur.get("cross_refs") or {})
            cross_refs["numista_id"] = int(rc["new_nid"])
            sb.patch(
                "coins",
                filters={"eurio_id": f"eq.{rc['eurio_id']}"},
                payload={
                    "cross_refs": cross_refs,
                    "last_updated": today,
                    "needs_review": False,
                    "review_reason": None,
                },
            )
            new_c_refs.append({
                "coin_type_id": rc["eurio_id"],
                "source": "numista",
                "native_id": rc["new_nid"],
                "native_url": None,
            })
            sb.delete(
                "coin_source_refs",
                filters={
                    "coin_type_id": f"eq.{rc['eurio_id']}",
                    "source": "eq.numista",
                    "native_id": f"eq.{rc['old_nid']}",
                },
            )
        if new_c_refs:
            sb.upsert(
                "coin_source_refs",
                new_c_refs,
                on_conflict="coin_type_id,source,native_id",
            )
        print(f"  ✓ {len(rematch_c)} bucket-C rematches patched")

        print("\nDone.")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
