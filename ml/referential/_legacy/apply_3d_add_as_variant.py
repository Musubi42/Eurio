"""Chunk 3d — ADD_AS_VARIANT × 25.

Refs:
  docs/research/referential-v2.md (decisions D1–D8)
  docs/research/referential-v2-progress.md §6 (D-3d-1 → D-3d-4)
  ml/datasets/audit_referential_v2.json
  ml/referential/audit_apply_common.py (overlap_score, eurio_id_from_catalog)

Contexte
--------
L'audit a identifié 19 ORPHAN_VARIANT_OF_MATCHED + 6 ORPHAN_VARIANT_NO_PARENT_YET.
Périmètre 3d organisé en 3 buckets après vérification live DB :

  Bucket A (19) — ORPHAN_VARIANT_OF_MATCHED
    Le parent existe en DB. L'audit fournit un `likely_parent_eurio_id` mais
    plusieurs sont incorrects (matched-by-bucket sans vérif sémantique). On
    re-match via overlap_score contre tous les coins du même
    (country, year, is_commemorative) bucket. DRIFT cases surfaced for review.

  Bucket B1 (3) — NO_PARENT_YET re-classifiés
    Les 3 NL 2015 EU Flag variants. Parent `nl-2015-2eur-30-years-of-european-union-flag`
    a été créé en 3a comme joint-issue. Reclassifiables comme bucket A.

  Bucket B2 (3) — NO_PARENT_YET vrais (NL 2017/2018/2019 collector coloured-only)
    Aucun parent classic n'existe (Numista n'expose pas de classic counterpart).
    On crée le Type parent via eurio_id_from_catalog + on flag needs_review.

Décisions appliquées (D-3d-1 → D-3d-4) :
  - D-3d-1 : si finish='classic' et parent.cross_refs.numista_id != classic_nid,
             on bascule cross_refs vers le classic_nid (cohérence D-3c-1).
  - D-3d-2 : Bucket B2 → création de parent abstrait avec needs_review=true.
  - D-3d-3 : variant_label='color-variant' → finish='other' + notes explicites.
  - D-3d-4 : source_ref granularité = 1 row par (parent, source, native_id).

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

from serving.supabase_client import SupabaseClient, load_env  # noqa: E402
from referential.audit_apply_common import (  # noqa: E402
    eurio_id_from_catalog,
    load_audit,
    overlap_score,
)


# ─── Variant finish whitelist (mirror migration SQL CHECK) ───────────────────


FINISH_WHITELIST = {
    "classic", "coloured", "hologram", "gilded",
    "pattern", "mule", "misstrike", "other",
}


def normalize_finish(label: str) -> tuple[str, str | None]:
    """Map an audit variant_label to a CHECK-valid finish + optional reason note.

    Returns (finish, extra_note_or_None).
    """
    if label in FINISH_WHITELIST:
        return label, None
    # Known unmapped labels we collapse onto 'other'.
    return "other", f"variant_label={label}"


# ─── Bucket categorization ───────────────────────────────────────────────────


# B1 — the 3 NL 2015 EU Flag NO_PARENT_YET that DO have a parent post-3a.
# Parent slug created in 3a as part of the eu-flag-2015 joint-issue bootstrap.
B1_PARENT = "nl-2015-2eur-30-years-of-european-union-flag"
B1_NIDS = {"218048", "218049", "218051"}

# Manual overrides for ORPHAN_VARIANT_OF_MATCHED records the audit got wrong
# AND re-match cannot recover (no existing parent in DB matches the variant's
# theme). For each group, we synthesize a new parent Type and route all listed
# nids under it.
#
# LU 2024 Guillaume II : audit assigns both nids to the Feierstëppler parent,
# but they're a distinct commemo (William II, ruled 1840–1849). We create the
# canonical Type with cross_refs pointed at the classic nid, and flag the row
# needs_review for human verification of theme/description.
MANUAL_OVERRIDES_NEW_PARENTS: list[dict] = [
    {
        "parent_eurio_id": "lu-2024-2eur-guillaume-ii",
        "country": "LU",
        "year": 2024,
        "theme": "Guillaume II",
        "design_description": (
            "2 Euros — Guillaume II (Grand Duke of Luxembourg, 1840–1849). "
            "Bootstrapped via 3d (manual override). Numista exposes only "
            "variant entries (classic + hologram) for this commemo."
        ),
        "primary_nid": "398222",  # classic — used for cross_refs.numista_id
        "member_nids": {"398222", "427789"},
    },
]


def categorize(
    records: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Return (bucket_a, bucket_b1, bucket_b2, bucket_b3).

    Bucket B3 = ORPHAN_VARIANT_OF_MATCHED records covered by MANUAL_OVERRIDES_NEW_PARENTS.
    """
    overridden = {
        nid for ov in MANUAL_OVERRIDES_NEW_PARENTS for nid in ov["member_nids"]
    }
    bucket_a = [
        r for r in records
        if r["classification"] == "ORPHAN_VARIANT_OF_MATCHED"
        and r["numista_id"] not in overridden
    ]
    bucket_b3 = [
        r for r in records
        if r["classification"] == "ORPHAN_VARIANT_OF_MATCHED"
        and r["numista_id"] in overridden
    ]
    no_parent = [
        r for r in records
        if r["classification"] == "ORPHAN_VARIANT_NO_PARENT_YET"
    ]
    bucket_b1 = [r for r in no_parent if r["numista_id"] in B1_NIDS]
    bucket_b2 = [r for r in no_parent if r["numista_id"] not in B1_NIDS]
    return bucket_a, bucket_b1, bucket_b2, bucket_b3


# ─── Live DB queries ─────────────────────────────────────────────────────────


def fetch_bucket_coins(
    sb: SupabaseClient, country_year_pairs: set[tuple[str, int]]
) -> dict[tuple[str, int], list[dict]]:
    """Return {(country, year): [coins]} for all 2eur commemos in those buckets."""
    out: dict[tuple[str, int], list[dict]] = {}
    if not country_year_pairs:
        return out
    countries = sorted({c for c, _ in country_year_pairs})
    years = sorted({y for _, y in country_year_pairs})
    rows = sb.query(
        "coins",
        select="eurio_id,country,year,theme,cross_refs,is_commemorative,needs_review",
        params={
            "country": f"in.({','.join(countries)})",
            "year": f"in.({','.join(str(y) for y in years)})",
            "face_value": "eq.2.0",
        },
    )
    for r in rows:
        key = (r["country"], r["year"])
        out.setdefault(key, []).append(r)
    return out


def fetch_existing_variants(
    sb: SupabaseClient, parents: list[str]
) -> dict[str, set[str]]:
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


# ─── Parent re-matching (override audit's likely_parent_eurio_id) ────────────


def best_parent(
    variant_record: dict,
    coins_in_bucket: list[dict],
    min_overlap: float = 0.4,
) -> tuple[str | None, float, list[tuple[float, str]]]:
    """Find the best parent eurio_id for a variant in the given bucket.

    Returns (best_eid_or_None, best_score, scored_runners_up).
    """
    cat_name = variant_record["catalog_name"]
    scored: list[tuple[float, str]] = []
    for c in coins_in_bucket:
        if c.get("is_commemorative") != variant_record["is_commemorative"]:
            continue
        sc = overlap_score(cat_name, c.get("theme") or "", c["eurio_id"])
        if sc > 0:
            scored.append((sc, c["eurio_id"]))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < min_overlap:
        return None, scored[0][0] if scored else 0.0, scored[:3]
    return scored[0][1], scored[0][0], scored[:3]


# ─── Slug allocator ──────────────────────────────────────────────────────────


def allocate_variant_slug(parent_eid: str, finish: str, taken: set[str]) -> str:
    base = f"{parent_eid}/{finish}"
    if base not in taken:
        return base
    seq = 1
    while True:
        cand = f"{base}-{seq}"
        if cand not in taken:
            return cand
        seq += 1


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records = load_audit()
    bucket_a, bucket_b1, bucket_b2, bucket_b3 = categorize(records)

    print("=" * 66)
    print(f"  Chunk 3d — ADD_AS_VARIANT  ({'DRY-RUN' if args.dry_run else 'APPLY'})")
    print("=" * 66)
    print(f"  Bucket A  (ORPHAN_VARIANT_OF_MATCHED, re-matched)   : {len(bucket_a)}")
    print(f"  Bucket B1 (NO_PARENT_YET → parent created in 3a)    : {len(bucket_b1)}")
    print(f"  Bucket B2 (NO_PARENT_YET → create new parent now)   : {len(bucket_b2)}")
    print(f"  Bucket B3 (manual override → create new parent now) : {len(bucket_b3)}")
    print()

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing.")
        return 1

    sb = SupabaseClient(url, key)
    try:
        # ── 1. Re-match Bucket A parents (audit had errors) ──
        country_year_pairs = {
            (r["country"], int(r["year"])) for r in bucket_a
        }
        bucket_coins = fetch_bucket_coins(sb, country_year_pairs)

        rematches: list[dict] = []
        for r in bucket_a:
            key = (r["country"], int(r["year"]))
            coins = bucket_coins.get(key, [])
            audit_parent = r["likely_parent_eurio_id"]
            best_eid, best_sc, runners = best_parent(r, coins)
            drift = (best_eid is not None and best_eid != audit_parent)
            rematches.append({
                "audit": dict(r),
                "audit_parent": audit_parent,
                "recomputed_parent": best_eid,
                "best_score": best_sc,
                "runners_up": runners,
                "drift": drift,
            })

        # ── 2. Build payloads ──
        # B1 uses fixed parent.
        # B2 needs parent creation (eurio_id_from_catalog).
        # Bucket A uses recomputed_parent (or audit's if recompute failed — surfaced).

        all_parents = sorted({
            m["recomputed_parent"] or m["audit_parent"]
            for m in rematches
            if (m["recomputed_parent"] or m["audit_parent"])
        } | {B1_PARENT})
        existing_variants = fetch_existing_variants(sb, all_parents)
        allocated: dict[str, set[str]] = {p: set(s) for p, s in existing_variants.items()}

        variant_rows: list[dict] = []
        source_ref_rows: list[dict] = []
        cross_refs_baseline: dict[str, dict] = {}

        # Capture parent live cross_refs (for D-3d-1 bascule decisions)
        parent_live_state: dict[str, dict] = {}
        for coins in bucket_coins.values():
            for c in coins:
                parent_live_state[c["eurio_id"]] = c

        # NL 2015 parent for B1 — fetch separately if not in any bucket
        if B1_PARENT not in parent_live_state:
            extra = sb.query(
                "coins",
                select="eurio_id,country,year,theme,cross_refs,is_commemorative,needs_review",
                params={"eurio_id": f"eq.{B1_PARENT}"},
            )
            if extra:
                parent_live_state[B1_PARENT] = extra[0]

        bascule_actions: list[dict] = []  # D-3d-1
        skipped: list[dict] = []

        def make_variant(parent: str, label: str, nid: str, name: str) -> dict:
            finish, extra_note = normalize_finish(label)
            taken = allocated.setdefault(parent, set())
            slug = allocate_variant_slug(parent, finish, taken)
            taken.add(slug)
            note = f"Numista nid={nid} — {name}"
            if extra_note:
                note = f"[{extra_note}] {note}"
            return {
                "id": slug,
                "parent_type_id": parent,
                "finish": finish,
                "notes": note,
            }

        # Bucket A
        for m in rematches:
            r = m["audit"]
            parent = m["recomputed_parent"] or m["audit_parent"]
            if not parent or parent not in parent_live_state:
                skipped.append({
                    "nid": r["numista_id"],
                    "reason": f"no parent in DB (recomputed={m['recomputed_parent']}, audit={m['audit_parent']})",
                    "catalog_name": r["catalog_name"],
                })
                continue
            variant_rows.append(make_variant(
                parent, r["variant_label"], r["numista_id"], r["catalog_name"],
            ))
            source_ref_rows.append({
                "coin_type_id": parent,
                "source": "numista",
                "native_id": r["numista_id"],
                "native_url": None,
            })
            # D-3d-1: if finish='classic' and parent currently points at a non-classic nid,
            #         bascule cross_refs to this classic_nid.
            finish_norm, _ = normalize_finish(r["variant_label"])
            if finish_norm == "classic":
                pcoin = parent_live_state.get(parent) or {}
                cur = (pcoin.get("cross_refs") or {}).get("numista_id")
                if cur is not None and str(cur) != str(r["numista_id"]):
                    bascule_actions.append({
                        "eurio_id": parent,
                        "old_nid": str(cur),
                        "new_nid": str(r["numista_id"]),
                        "catalog_name": r["catalog_name"],
                    })

        # Bucket B1 — fixed parent, B1_PARENT
        for r in bucket_b1:
            variant_rows.append(make_variant(
                B1_PARENT, r["variant_label"], r["numista_id"], r["catalog_name"],
            ))
            source_ref_rows.append({
                "coin_type_id": B1_PARENT,
                "source": "numista",
                "native_id": r["numista_id"],
                "native_url": None,
            })

        # Bucket B3 — manual overrides : create new parent + N variants per group
        b3_new_parents: list[dict] = []
        b3_new_parent_srefs: list[dict] = []
        today = date.today().isoformat()
        for ov in MANUAL_OVERRIDES_NEW_PARENTS:
            members = [r for r in bucket_b3 if r["numista_id"] in ov["member_nids"]]
            if not members:
                continue
            new_eid = ov["parent_eurio_id"]
            primary_nid = ov["primary_nid"]
            b3_new_parents.append({
                "eurio_id": new_eid,
                "country": ov["country"],
                "year": int(ov["year"]),
                "face_value": 2.0,
                "currency": "EUR",
                "is_commemorative": True,
                "is_withdrawn": False,
                "collector_only": False,
                "needs_review": True,
                "review_reason": (
                    "3d manual override: audit mis-routed variants under wrong parent; "
                    "Type bootstrapped — verify theme/description"
                ),
                "personal_owned": False,
                "theme": ov["theme"],
                "design_description": ov["design_description"],
                "cross_refs": {"numista_id": int(primary_nid)},
                "sources_used": ["numista"],
                "first_seen": today,
                "last_updated": today,
            })
            # Source ref for the primary nid (also the variant nid below)
            b3_new_parent_srefs.append({
                "coin_type_id": new_eid,
                "source": "numista",
                "native_id": primary_nid,
                "native_url": None,
            })
            # Add a variant row per member nid + source_ref for the non-primary
            for r in members:
                variant_rows.append(make_variant(
                    new_eid, r["variant_label"], r["numista_id"], r["catalog_name"],
                ))
                if r["numista_id"] != primary_nid:
                    b3_new_parent_srefs.append({
                        "coin_type_id": new_eid,
                        "source": "numista",
                        "native_id": r["numista_id"],
                        "native_url": None,
                    })

        # Bucket B2 — create parent + variant
        b2_new_parents: list[dict] = []
        b2_new_parent_srefs: list[dict] = []
        for r in bucket_b2:
            country = r["country"]
            year = int(r["year"])
            nid = r["numista_id"]
            cat_name = r["catalog_name"]
            new_eid = eurio_id_from_catalog(country, year, 2.0, cat_name)
            theme_match = re.search(r"\(([^)]+)\)", cat_name or "")
            theme = theme_match.group(1).strip() if theme_match else None
            # Strip the variant suffix from the theme for cleaner display
            if theme:
                theme = re.sub(r"\s*[;,-]\s*(?:coloured?|hologram|gilded).*$",
                               "", theme, flags=re.IGNORECASE).strip()
            b2_new_parents.append({
                "eurio_id": new_eid,
                "country": country,
                "year": year,
                "face_value": 2.0,
                "currency": "EUR",
                "is_commemorative": True,
                "is_withdrawn": False,
                "collector_only": True,
                "needs_review": True,
                "review_reason": (
                    "3d: created as parent for coloured-only variant; "
                    "no Numista classic counterpart found"
                ),
                "personal_owned": False,
                "theme": theme,
                "design_description": cat_name,
                "cross_refs": {"numista_id": int(nid)},
                "sources_used": ["numista"],
                "first_seen": today,
                "last_updated": today,
            })
            b2_new_parent_srefs.append({
                "coin_type_id": new_eid,
                "source": "numista",
                "native_id": nid,
                "native_url": None,
            })
            # And the variant row under the new parent
            variant_rows.append(make_variant(
                new_eid, r["variant_label"], nid, cat_name,
            ))
            # The source_ref for the variant nid is the same as the parent's
            # primary nid here — single nid covers the only variant. The
            # b2_new_parent_srefs entry above already covers it.

        # ── 3. Print previews ──
        print("Bucket A — re-matched parents (DRIFT cases highlighted) :")
        for m in rematches:
            tag = "DRIFT" if m["drift"] else "OK"
            r = m["audit"]
            print(f"  [{tag}] nid={r['numista_id']:>6} {r['variant_label']:<10}"
                  f" {r['country']} {r['year']} | {r['catalog_name'][:55]}")
            if m["drift"]:
                print(f"     audit parent      : {m['audit_parent']}")
                print(f"     recomputed parent : {m['recomputed_parent']}  (score={m['best_score']:.2f})")
                if len(m["runners_up"]) > 1:
                    runner = m["runners_up"][1]
                    print(f"     runner-up         : {runner[1]}  (score={runner[0]:.2f})")
            elif m["recomputed_parent"]:
                print(f"     parent : {m['recomputed_parent']}  (score={m['best_score']:.2f})")
            else:
                print(f"     ⚠ no parent matched (audit={m['audit_parent']})")
        print()

        print("Bucket B1 — NL 2015 EU Flag variants under created joint-issue parent :")
        print(f"  parent: {B1_PARENT}")
        for r in bucket_b1:
            print(f"  → nid={r['numista_id']} variant_label={r['variant_label']:<14} "
                  f"| {r['catalog_name'][:55]}")
        print()

        print("Bucket B2 — new parent Type creation (collector NL coloured-only) :")
        for p, sref, r in zip(b2_new_parents, b2_new_parent_srefs, bucket_b2):
            print(f"  CREATE Type: {p['eurio_id']}")
            print(f"      country={p['country']} year={p['year']} cross_refs.numista_id={r['numista_id']}")
            print(f"      theme: {p['theme']}  needs_review=true")
            print(f"      → variant /{normalize_finish(r['variant_label'])[0]} for nid={r['numista_id']}")
        print()

        if b3_new_parents:
            print("Bucket B3 — manual override new parents :")
            for p in b3_new_parents:
                members = [r for r in bucket_b3 if r["country"] == p["country"]
                           and int(r["year"]) == p["year"]]
                print(f"  CREATE Type: {p['eurio_id']}  (cross_refs.numista_id={p['cross_refs']['numista_id']})")
                print(f"      theme: {p['theme']}  needs_review=true")
                for r in members:
                    print(f"      → variant /{normalize_finish(r['variant_label'])[0]}"
                          f" for nid={r['numista_id']}  ({r['catalog_name'][:50]})")
            print()

        if bascule_actions:
            print("D-3d-1 bascules (cross_refs → classic_nid) :")
            for ba in bascule_actions:
                print(f"  {ba['eurio_id']}: numista_id {ba['old_nid']} → {ba['new_nid']}  "
                      f"({ba['catalog_name'][:50]})")
            print()
        else:
            print("D-3d-1 : no bascule cases (no finish='classic' on a parent pointing elsewhere).")
            print()

        if skipped:
            print("⚠  Skipped cases (no parent in DB) :")
            for s in skipped:
                print(f"  nid={s['nid']}: {s['reason']}")
                print(f"     {s['catalog_name']}")
            print()

        if any(existing_variants.values()):
            print("Existing coin_variants on impacted parents (collision check) :")
            for p, ids in sorted(existing_variants.items()):
                if ids:
                    print(f"  {p}:")
                    for vid in sorted(ids):
                        print(f"      {vid}")
            print()

        print("Variant slugs to insert :")
        for v in variant_rows:
            print(f"  {v['id']:<78s}  finish={v['finish']}")
        print()

        finish_counts = Counter(v["finish"] for v in variant_rows)
        print("Variant finish distribution :")
        for f, n in sorted(finish_counts.items(), key=lambda x: -x[1]):
            print(f"  {f:<10} {n}")
        print()

        # ── 4. Dry-run snapshot or apply ──
        if args.dry_run:
            out_path = ML_DIR / "datasets" / "chunk_3d_dryrun.json"
            out_path.write_text(json.dumps({
                "rematches": [
                    {
                        "nid": m["audit"]["numista_id"],
                        "variant_label": m["audit"]["variant_label"],
                        "catalog_name": m["audit"]["catalog_name"],
                        "audit_parent": m["audit_parent"],
                        "recomputed_parent": m["recomputed_parent"],
                        "best_score": m["best_score"],
                        "runners_up": m["runners_up"],
                        "drift": m["drift"],
                    }
                    for m in rematches
                ],
                "bucket_b1": bucket_b1,
                "bucket_b2": bucket_b2,
                "bucket_b3": bucket_b3,
                "b2_new_parents": b2_new_parents,
                "b2_new_parent_srefs": b2_new_parent_srefs,
                "b3_new_parents": b3_new_parents,
                "b3_new_parent_srefs": b3_new_parent_srefs,
                "variant_rows": variant_rows,
                "source_ref_rows": source_ref_rows,
                "bascule_actions": bascule_actions,
                "skipped": skipped,
                "existing_variants": {p: sorted(s) for p, s in existing_variants.items()},
            }, indent=2, ensure_ascii=False))
            print(f"Dry-run snapshot: {out_path}")
            print("\n--dry-run: nothing written. Re-run with --apply to commit.")
            return 0

        # ── APPLY ───
        # 1. Create B2 + B3 parents first (foreign key for variants)
        new_parents = b2_new_parents + b3_new_parents
        if new_parents:
            print(f"Upserting {len(new_parents)} new parent Types (B2={len(b2_new_parents)}, B3={len(b3_new_parents)})…")
            sb.upsert("coins", new_parents, on_conflict="eurio_id")
            print(f"  ✓ {len(new_parents)} parent Types")

        # 2. coin_source_refs for B2 + B3 parents
        new_parent_srefs = b2_new_parent_srefs + b3_new_parent_srefs
        if new_parent_srefs:
            print(f"Upserting {len(new_parent_srefs)} new parent source_refs…")
            sb.upsert(
                "coin_source_refs",
                new_parent_srefs,
                on_conflict="coin_type_id,source,native_id",
            )
            print(f"  ✓ {len(new_parent_srefs)} source_refs")

        # 3. coin_variants (Bucket A + B1 + B2 + B3)
        if variant_rows:
            print(f"Upserting {len(variant_rows)} coin_variants…")
            sb.upsert("coin_variants", variant_rows, on_conflict="id")
            print(f"  ✓ {len(variant_rows)} coin_variants")

        # 4. coin_source_refs for Bucket A + B1 variant nids
        #    (B2/B3 source_refs already done above)
        new_parent_ids = {p["eurio_id"] for p in new_parents}
        ab1_source_refs = [s for s in source_ref_rows if s["coin_type_id"] not in new_parent_ids]
        if ab1_source_refs:
            print(f"Upserting {len(ab1_source_refs)} variant source_refs (Bucket A + B1)…")
            sb.upsert(
                "coin_source_refs",
                ab1_source_refs,
                on_conflict="coin_type_id,source,native_id",
            )
            print(f"  ✓ {len(ab1_source_refs)} source_refs")

        # 5. D-3d-1 bascules : PATCH parent.cross_refs.numista_id → classic_nid
        #    + add classic source_ref (already in source_ref_rows above for these parents,
        #    so already upserted — only the PATCH remains)
        if bascule_actions:
            print(f"Applying {len(bascule_actions)} D-3d-1 bascules…")
            for ba in bascule_actions:
                pcoin = parent_live_state.get(ba["eurio_id"])
                if not pcoin:
                    print(f"  ⚠ {ba['eurio_id']} not loaded, skipping")
                    continue
                cross_refs = dict(pcoin.get("cross_refs") or {})
                cross_refs["numista_id"] = int(ba["new_nid"])
                sb.patch(
                    "coins",
                    filters={"eurio_id": f"eq.{ba['eurio_id']}"},
                    payload={
                        "cross_refs": cross_refs,
                        "last_updated": today,
                    },
                )
            print(f"  ✓ {len(bascule_actions)} bascules patched")

        print("\nDone.")
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
