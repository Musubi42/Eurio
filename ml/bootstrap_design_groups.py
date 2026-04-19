"""Bootstrap the `design_groups` pivot table and populate `coins.design_group_id`.

Two stages, idempotent:

1. **Axis A — intra-country annual re-issues** (automatic, from Numista).
   Group coins by `cross_refs->>numista_id` when count >= 2. Numista assigns
   one id per design and changes id on effigy/map/type changes, so this is a
   reliable source of truth. A design_group is created per group, members get
   their `design_group_id` set.

2. **Axis B — joint commemoratives cross-country** (manual, from seed JSON).
   Load `ml/data/design_groups_seed.json`. The seed is wrapped in an
   `axis_b` object with a `status` field. When `status == "deferred"`
   (current state — joint issues are stored as single eu-country rows in
   `coins`, per-country expansion not yet done), entries are listed in the
   output for visibility but no design_group is created. When status flips
   to `"active"`, the bootstrap resolves members via the declared
   `members.criteria`, upserts the design_group, patches the matched
   coins' `design_group_id`, and asserts member count equals
   `expected_count` (aborts on mismatch).

Rule: a coin receives a `design_group_id` iff its design is shared by >=2
coins. Singletons and true one-offs stay NULL.

Post-conditions (assertions):
- Every design_group has >=2 members.
- Axis B: actual member count == expected_count.
- Members of a design_group share either `country` or `year`.

Design notes:
- Uses the shared `PostgrestClient` pattern from `sync_to_supabase.py`.
- Dry-run by default: prints the plan, touches nothing. Pass `--apply` to write.
- Re-running the script is safe (upserts on `id`, only patches coins whose
  `design_group_id` differs from the target).

Usage:
    python ml/bootstrap_design_groups.py                 # dry-run
    python ml/bootstrap_design_groups.py --apply         # write to Supabase
    python ml/bootstrap_design_groups.py --skip-axis-a   # seed only axis B
    python ml/bootstrap_design_groups.py --skip-axis-b   # only intra-country re-issues
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sync_to_supabase import PostgrestClient, load_env

SEED_PATH = Path(__file__).parent / "data" / "design_groups_seed.json"


# ---------- helpers ----------


FACE_VALUE_SLUG = {
    0.01: "1cent",
    0.02: "2cent",
    0.05: "5cent",
    0.10: "10cent",
    0.20: "20cent",
    0.50: "50cent",
    1.00: "1euro",
    2.00: "2euro",
}


def face_value_slug(face_value: float) -> str:
    """Slugify a face value for use in design_group ids."""
    key = round(float(face_value), 2)
    return FACE_VALUE_SLUG.get(key, f"fv{int(round(key * 100))}c")


def face_value_display(face_value: float) -> str:
    """Human-readable face value for admin labels."""
    key = round(float(face_value), 2)
    if key >= 1.0:
        return f"{int(key) if key == int(key) else key:g}€"
    return f"{int(round(key * 100))}c"


# ---------- Supabase I/O ----------


def fetch_coins_with_numista(client: PostgrestClient) -> list[dict[str, Any]]:
    """Fetch all coins that have a `cross_refs->numista_id` populated.

    Paginated to handle >1000 rows safely. We pull only what axis A needs
    to reason (including year/country for the slug + assertion).
    """
    select = "eurio_id,country,year,face_value,series_id,design_group_id,cross_refs"
    rows: list[dict[str, Any]] = []
    batch = 1000
    offset = 0
    while True:
        resp = client._client.get(
            f"{client.base}/coins",
            params={
                "select": select,
                "cross_refs->numista_id": "not.is.null",
                "limit": batch,
                "offset": offset,
            },
        )
        resp.raise_for_status()
        chunk = resp.json()
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < batch:
            break
        offset += batch
    return rows


def fetch_coins_by_criteria(
    client: PostgrestClient, criteria: dict[str, Any]
) -> list[dict[str, Any]]:
    """Resolve an axis B `members.criteria` block to concrete coin rows.

    Only the DSL-style simple `eq` filters are supported in v1 (year,
    issue_type, country, face_value). Enough for the 5 seed entries.
    """
    params: dict[str, str] = {
        "select": "eurio_id,country,year,face_value,issue_type,design_group_id",
    }
    for key, value in criteria.items():
        if isinstance(value, (list, tuple)):
            vals = ",".join(str(v) for v in value)
            params[key] = f"in.({vals})"
        else:
            params[key] = f"eq.{value}"
    resp = client._client.get(f"{client.base}/coins", params=params)
    resp.raise_for_status()
    return resp.json()


def upsert_design_groups(client: PostgrestClient, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    client.upsert("design_groups", rows, on_conflict="id")


def patch_coin_design_group(
    client: PostgrestClient, eurio_id: str, design_group_id: str | None
) -> None:
    """Patch a single coin's design_group_id (idempotent)."""
    resp = client._client.patch(
        f"{client.base}/coins",
        params={"eurio_id": f"eq.{eurio_id}"},
        json={"design_group_id": design_group_id},
    )
    if resp.status_code >= 400:
        print(f"  FAIL {eurio_id}: HTTP {resp.status_code} {resp.text[:200]}")
        resp.raise_for_status()


# ---------- axis A: intra-country annual re-issues ----------


def plan_axis_a(
    coins: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[tuple[str, str]], list[str]]:
    """Build the axis-A plan from the coin list.

    Returns:
        group_rows: rows to upsert into design_groups.
        coin_patches: list of (eurio_id, design_group_id) to patch.
        singletons: list of eurio_ids that stay NULL because their numista_id
                    only has one member.
    """
    by_numista: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for coin in coins:
        nid = coin.get("cross_refs", {}).get("numista_id")
        if nid is None:
            continue
        by_numista[str(nid)].append(coin)

    group_rows: list[dict[str, Any]] = []
    coin_patches: list[tuple[str, str]] = []
    singletons: list[str] = []

    for nid, members in sorted(by_numista.items()):
        if len(members) < 2:
            singletons.extend(m["eurio_id"] for m in members)
            continue

        # All members share country + face_value for a well-formed Numista group.
        countries = {m["country"].lower() for m in members}
        face_values = {round(float(m["face_value"]), 2) for m in members}
        years = sorted(m["year"] for m in members)

        # Axis A groups are intra-country by definition. If we find a Numista
        # group that somehow spans multiple countries, fall through — it's
        # either a data issue or an axis-B case handled by seed JSON.
        if len(countries) != 1 or len(face_values) != 1:
            # Skip — will be handled by axis B seed or flagged later.
            continue

        country = next(iter(countries))
        fv = next(iter(face_values))
        group_id = f"{country}-{face_value_slug(fv)}-n{nid}"
        year_range = (
            f"{years[0]}-{years[-1]}" if years[0] != years[-1] else str(years[0])
        )
        designation = (
            f"{country.upper()} {face_value_display(fv)} "
            f"(Numista #{nid}, {year_range})"
        )

        group_rows.append(
            {
                "id": group_id,
                "designation": designation,
                "description": (
                    f"Annual re-issue group grouped by Numista #{nid}. "
                    f"{len(members)} members spanning {year_range}."
                ),
            }
        )
        for m in members:
            coin_patches.append((m["eurio_id"], group_id))

    return group_rows, coin_patches, singletons


# ---------- axis B: joint commemoratives ----------


def plan_axis_b(
    client: PostgrestClient, seed: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[tuple[str, str]], list[str]]:
    """Build the axis-B plan from the seed JSON.

    Returns:
        group_rows, coin_patches, errors: errors non-empty means assertion
        mismatch (expected_count).
    """
    group_rows: list[dict[str, Any]] = []
    coin_patches: list[tuple[str, str]] = []
    errors: list[str] = []

    for entry in seed:
        criteria = entry.get("members", {}).get("criteria", {})
        matched = fetch_coins_by_criteria(client, criteria)
        actual = len(matched)
        expected = entry.get("expected_count")

        if expected is not None and actual != expected:
            errors.append(
                f"{entry['id']}: expected {expected} members, got {actual} "
                f"(criteria={criteria})"
            )

        group_rows.append(
            {
                "id": entry["id"],
                "designation": entry["designation"],
                "designation_i18n": entry.get("designation_i18n"),
                "description": entry.get("description"),
            }
        )
        for m in matched:
            coin_patches.append((m["eurio_id"], entry["id"]))

    return group_rows, coin_patches, errors


# ---------- assertions ----------


def check_coherence(
    coins: list[dict[str, Any]], patches: list[tuple[str, str]]
) -> list[str]:
    """Verify each design_group's members share either country or year.

    `coins` must include all coins that will end up in any group (patches'
    eurio_ids must be a subset of coins' eurio_ids).
    """
    by_eid = {c["eurio_id"]: c for c in coins}
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for eid, gid in patches:
        coin = by_eid.get(eid)
        if coin is None:
            continue
        by_group[gid].append(coin)

    warnings: list[str] = []
    for gid, members in by_group.items():
        if len(members) < 2:
            warnings.append(f"{gid}: only {len(members)} member(s), should be >=2")
            continue
        countries = {m["country"].lower() for m in members}
        years = {m["year"] for m in members}
        if len(countries) > 1 and len(years) > 1:
            warnings.append(
                f"{gid}: members span {len(countries)} countries and "
                f"{len(years)} years (hybrid axis — no example expected in v1)"
            )
    return warnings


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Bootstrap design_groups and populate coins.design_group_id"
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to Supabase (default is dry-run)",
    )
    ap.add_argument(
        "--skip-axis-a",
        action="store_true",
        help="Skip axis A (intra-country annual re-issues from Numista)",
    )
    ap.add_argument(
        "--skip-axis-b",
        action="store_true",
        help="Skip axis B (joint commemoratives from seed JSON)",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== bootstrap_design_groups.py [{mode}] ===\n")

    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from .env")
        sys.exit(1)

    all_group_rows: list[dict[str, Any]] = []
    all_patches: list[tuple[str, str]] = []

    with PostgrestClient(url, key) as client:
        # ---------- Axis A ----------
        axis_a_coins: list[dict[str, Any]] = []
        if not args.skip_axis_a:
            print("[1/3] Axis A — intra-country annual re-issues (from Numista)")
            axis_a_coins = fetch_coins_with_numista(client)
            print(f"  fetched {len(axis_a_coins)} coins with a numista_id")

            a_groups, a_patches, a_singletons = plan_axis_a(axis_a_coins)
            print(f"  groups to upsert: {len(a_groups)}")
            print(f"  coin patches: {len(a_patches)}")
            print(f"  singletons (stay NULL): {len(a_singletons)}")

            # Top sample for readability
            if a_groups:
                print("  sample groups:")
                for g in a_groups[:5]:
                    print(f"    {g['id']:50} — {g['designation']}")
                if len(a_groups) > 5:
                    print(f"    ... and {len(a_groups) - 5} more")

            all_group_rows.extend(a_groups)
            all_patches.extend(a_patches)
        else:
            print("[1/3] Axis A skipped (--skip-axis-a)")

        # ---------- Axis B ----------
        axis_b_coins: list[dict[str, Any]] = []
        if not args.skip_axis_b:
            print("\n[2/3] Axis B — joint commemoratives (from seed JSON)")
            seed_doc = json.loads(SEED_PATH.read_text())
            axis_b_block = seed_doc.get("axis_b", {})
            entries = axis_b_block.get("entries", [])
            status = axis_b_block.get("status", "active")

            if status == "deferred":
                reason = axis_b_block.get("deferred_reason", "(no reason given)")
                print(f"  status: DEFERRED — {len(entries)} entries documented, none applied")
                print(f"  reason: {reason}")
                if entries:
                    print("  deferred entries:")
                    for e in entries:
                        exp = e.get("expected_count", "?")
                        print(f"    {e['id']:30} (expected {exp} members)")
            else:
                b_groups, b_patches, b_errors = plan_axis_b(client, entries)
                print(f"  groups to upsert: {len(b_groups)}")
                print(f"  coin patches: {len(b_patches)}")

                if b_errors:
                    print("\nERROR: axis B expected_count mismatches:")
                    for line in b_errors:
                        print(f"    {line}")
                    print(
                        "\n  Fix the seed JSON or the coins' issue_type before re-running."
                    )
                    sys.exit(2)

                # Report per-theme counts
                counter: Counter[str] = Counter()
                for _, gid in b_patches:
                    counter[gid] += 1
                for gid, n in counter.most_common():
                    print(f"    {gid:30} {n:3} members")

                # We still need the full coin rows for the coherence check
                for entry in entries:
                    matched = fetch_coins_by_criteria(
                        client, entry["members"]["criteria"]
                    )
                    axis_b_coins.extend(matched)

                all_group_rows.extend(b_groups)
                all_patches.extend(b_patches)
        else:
            print("\n[2/3] Axis B skipped (--skip-axis-b)")

        # ---------- Coherence ----------
        print("\n[3/3] Coherence check")
        all_coins = axis_a_coins + axis_b_coins
        warnings = check_coherence(all_coins, all_patches)
        if warnings:
            print("  WARNINGS:")
            for w in warnings:
                print(f"    {w}")
        else:
            print("  ✓ All groups well-formed")

        # ---------- Write ----------
        print("\n=== write phase ===")
        if args.apply:
            if all_group_rows:
                print(f"Upserting {len(all_group_rows)} design_groups...")
                # Dedupe by id in case axis A and B collided (shouldn't)
                by_id = {r["id"]: r for r in all_group_rows}
                upsert_design_groups(client, list(by_id.values()))
                count = client.count("design_groups")
                print(f"  design_groups count after upsert: {count}")

            if all_patches:
                print(f"Patching {len(all_patches)} coins...")
                # Idempotent: skip patches where the coin already has the right gid.
                existing = {c["eurio_id"]: c.get("design_group_id") for c in all_coins}
                patched = 0
                skipped = 0
                for eid, gid in all_patches:
                    if existing.get(eid) == gid:
                        skipped += 1
                        continue
                    patch_coin_design_group(client, eid, gid)
                    patched += 1
                    if patched % 500 == 0:
                        print(f"    patched {patched}/{len(all_patches)}")
                print(f"  ✓ patched {patched} coins, skipped {skipped} already correct")
        else:
            print(f"[dry-run] would upsert {len(all_group_rows)} design_groups")
            print(f"[dry-run] would patch {len(all_patches)} coins")

    print("\n=== done ===")


if __name__ == "__main__":
    main()
