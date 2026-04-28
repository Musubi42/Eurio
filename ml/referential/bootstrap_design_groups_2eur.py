"""Bootstrap design_group_id on 2€ standards (axis A — re-issued standards).

Why this script exists
----------------------
Sub-agent investigation 2026-04-28 found that ``coins.design_group_id`` is
NULL for all 508 active 2€ coins. The original axis-A bootstrap (2026-04)
only ran on 1€ (4 groups, 49 coins). Without grouping, ``confusion_map.py``
falls back to ``numista_id`` for the "same design" exclusion, but each
yearly re-issue carries its own Numista ref → re-issues appear as each
other's nearest neighbours (e.g. ``ie-2002`` ↔ ``ie-2007`` sim=0.978).
This pollutes the red-zone signal and wastes ArcFace class slots on
visually identical coins.

What it does
------------
1. Fetches all 2€ standards (``is_commemorative=false``) with NULL
   ``design_group_id`` from Supabase.
2. Pulls their ``coin_confusion_map.top_k_neighbors`` and builds an
   undirected graph of "candidate same-design" edges:
   - both nodes 2€ standards
   - same ISO country
   - similarity ≥ ``--threshold`` (default 0.95)
3. Connected components ≥ 2 → proposed design group.
4. Dry-run prints the proposed groups + members. Apply mode INSERTs into
   ``design_groups`` and UPDATEs ``coins.design_group_id``.

Group naming
------------
Existing 1€ groups use ``{country}-{denom}-n{numista_id}`` because Numista
keeps one ref across all years for those. On 2€ each year has a distinct
Numista ref, so we name groups ``{country}-2eur-{theme}-{oldest_year}``
and use the oldest member as the canonical (its obverse URL fills
``shared_obverse_url``).

Usage
-----
    go-task ml -- python -m referential.bootstrap_design_groups_2eur --dry-run
    go-task ml -- python -m referential.bootstrap_design_groups_2eur --apply
    go-task ml -- python -m referential.bootstrap_design_groups_2eur --apply --threshold 0.94

Safety
------
- Never overwrites a non-NULL ``design_group_id`` (skips the coin).
- Cross-denomination edges are filtered out (only 2€ ↔ 2€).
- Cross-country edges are filtered out (only same ISO country).
- Apply mode is idempotent: re-running upserts the same rows by id.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Allow running as a script from `ml/` cwd
ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.supabase_client import SupabaseClient, load_env  # noqa: E402

logger = logging.getLogger("bootstrap_design_groups_2eur")

DEFAULT_THRESHOLD = 0.95
ENCODER_VERSION = "dinov2-vits14"


# --------------------------------------------------------------------------
# Data fetching
# --------------------------------------------------------------------------


def fetch_candidates(sb: SupabaseClient) -> list[dict]:
    """Fetch 2€ standards without an existing design_group_id."""
    rows = sb.query(
        "coins",
        select="eurio_id,country,year,images,design_group_id",
        params={
            "face_value": "eq.2",
            "is_commemorative": "eq.false",
            "design_group_id": "is.null",
        },
    )
    return rows


def fetch_confusion_rows(sb: SupabaseClient, eurio_ids: list[str]) -> list[dict]:
    """Fetch confusion_map rows for the given eurio_ids."""
    if not eurio_ids:
        return []
    in_list = ",".join(eurio_ids)
    rows = sb.query(
        "coin_confusion_map",
        select="eurio_id,top_k_neighbors,nearest_similarity",
        params={
            "eurio_id": f"in.({in_list})",
            "encoder_version": f"eq.{ENCODER_VERSION}",
        },
    )
    return rows


# --------------------------------------------------------------------------
# Graph building
# --------------------------------------------------------------------------


def build_pairs(
    candidates: list[dict],
    confusion_rows: list[dict],
    threshold: float,
) -> list[tuple[str, str, float]]:
    """Extract (a, b, sim) edges where both endpoints are in the candidate set,
    same country, and similarity ≥ threshold. Direction ignored."""
    candidate_ids = {c["eurio_id"] for c in candidates}
    country_of = {c["eurio_id"]: c["country"] for c in candidates}

    pairs: list[tuple[str, str, float]] = []
    for row in confusion_rows:
        a = row["eurio_id"]
        if a not in candidate_ids:
            continue
        for nb in row.get("top_k_neighbors") or []:
            b = nb.get("eurio_id")
            sim = float(nb.get("similarity", 0.0))
            if not b or b not in candidate_ids:
                continue
            if sim < threshold:
                continue
            if country_of[a] != country_of[b]:
                continue
            # Canonicalize order so dedup works
            edge = (a, b, sim) if a < b else (b, a, sim)
            pairs.append(edge)
    # Dedup
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str, float]] = []
    for a, b, sim in pairs:
        if (a, b) in seen:
            continue
        seen.add((a, b))
        deduped.append((a, b, sim))
    return deduped


def connected_components(
    nodes: list[str],
    edges: list[tuple[str, str, float]],
) -> list[list[str]]:
    """Union-Find connected components. Returns components with ≥ 2 members."""
    parent: dict[str, str] = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for a, b, _ in edges:
        union(a, b)

    buckets: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        buckets[find(n)].append(n)
    return [members for members in buckets.values() if len(members) >= 2]


# --------------------------------------------------------------------------
# Group metadata
# --------------------------------------------------------------------------


def _extract_obverse_url(images: object) -> str | None:
    """Same logic as ml/eval/confusion_map.py:_extract_obverse_url."""
    if not images:
        return None
    if isinstance(images, dict):
        obv = images.get("obverse") or images.get("obverse_url")
        if isinstance(obv, str):
            return obv
        if isinstance(obv, list) and obv:
            first = obv[0]
            if isinstance(first, dict):
                return first.get("url")
            if isinstance(first, str):
                return first
        return None
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict) and img.get("role") == "obverse":
                return img.get("url")
    return None


def _theme_token(eurio_id: str) -> str:
    """Extract the theme suffix from eurio_id (everything after `{cc}-{year}-{denom}-`)."""
    parts = eurio_id.split("-", 3)
    return parts[3] if len(parts) >= 4 else "standard"


def build_group(members: list[dict]) -> dict:
    """Build the design_groups row + the canonical eurio_id for the cluster.

    Picks the oldest year as canonical (most established design) and uses
    its obverse for ``shared_obverse_url``. Group id pattern:
    ``{country}-2eur-{theme}-{oldest_year}``.
    """
    by_year = sorted(members, key=lambda m: int(m["year"]))
    canonical = by_year[0]
    country = canonical["country"].lower()
    theme = _theme_token(canonical["eurio_id"])
    oldest_year = int(canonical["year"])
    newest_year = int(by_year[-1]["year"])
    group_id = f"{country}-2eur-{theme}-{oldest_year}"
    if oldest_year == newest_year:
        designation = f"{country.upper()} 2€ {theme} ({oldest_year})"
    else:
        designation = f"{country.upper()} 2€ {theme} ({oldest_year}-{newest_year})"
    return {
        "id": group_id,
        "designation": designation,
        "shared_obverse_url": _extract_obverse_url(canonical.get("images")),
        "canonical_eurio_id": canonical["eurio_id"],
        "members": [m["eurio_id"] for m in by_year],
        "year_range": (oldest_year, newest_year),
    }


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------


def apply_groups(
    sb: SupabaseClient,
    groups: list[dict],
) -> None:
    """Insert the design_groups rows then PATCH coins.design_group_id.

    The design_groups path uses upsert (idempotent on id). The coins path
    uses PATCH per group: PostgREST upsert on coins fails because the row
    has many NOT NULL columns we don't carry here (country, year, …);
    PATCH only updates the listed field which is what we need.
    """
    now = datetime.now(timezone.utc).isoformat()

    dg_rows = [
        {
            "id": g["id"],
            "designation": g["designation"],
            "shared_obverse_url": g["shared_obverse_url"],
            "created_at": now,
            "updated_at": now,
        }
        for g in groups
    ]
    sb.upsert("design_groups", dg_rows, on_conflict="id")
    logger.info("Upserted %d design_groups rows", len(dg_rows))

    total_patched = 0
    for g in groups:
        ids = ",".join(g["members"])
        resp = sb._client.patch(  # type: ignore[attr-defined]
            f"{sb.rest_base}/coins",
            params={"eurio_id": f"in.({ids})"},
            json={"design_group_id": g["id"]},
        )
        resp.raise_for_status()
        total_patched += len(g["members"])
    logger.info(
        "Patched %d coins (design_group_id assigned)", total_patched
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed groups, no DB writes.",
    )
    g.add_argument(
        "--apply",
        action="store_true",
        help="Insert design_groups + UPDATE coins.design_group_id.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Min cosine similarity for an edge (default: {DEFAULT_THRESHOLD}).",
    )
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING).",
    )
    return p


def print_dry_run(groups: list[dict], unmatched: list[dict]) -> None:
    print()
    print("=" * 78)
    print(f"PROPOSED DESIGN GROUPS — {len(groups)} cluster(s)")
    print("=" * 78)
    for i, g in enumerate(groups, 1):
        print(f"\n[{i}] {g['id']}")
        print(f"    designation:   {g['designation']}")
        print(f"    canonical:     {g['canonical_eurio_id']}")
        print(f"    members ({len(g['members'])}):")
        for eid in g["members"]:
            marker = "  ← canonical" if eid == g["canonical_eurio_id"] else ""
            print(f"      - {eid}{marker}")
        if g["shared_obverse_url"]:
            print(f"    shared_obverse: {g['shared_obverse_url'][:70]}…")
    print()
    print("-" * 78)
    print(
        f"Standalone candidates (no edges ≥ threshold): {len(unmatched)}"
    )
    print("-" * 78)
    for c in unmatched[:20]:
        print(f"  - {c['eurio_id']}")
    if len(unmatched) > 20:
        print(f"  …and {len(unmatched) - 20} more")
    print()


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from environment"
        )

    sb = SupabaseClient(url, key)
    try:
        candidates = fetch_candidates(sb)
        logger.info("Fetched %d 2€ standards with NULL design_group_id", len(candidates))
        if not candidates:
            print("No candidates — nothing to do.")
            return 0

        candidate_ids = [c["eurio_id"] for c in candidates]
        confusion_rows = fetch_confusion_rows(sb, candidate_ids)
        logger.info(
            "Fetched %d confusion_map rows for candidates", len(confusion_rows)
        )

        edges = build_pairs(candidates, confusion_rows, args.threshold)
        logger.info(
            "Found %d candidate edges with sim ≥ %.3f (same country)",
            len(edges), args.threshold,
        )

        components = connected_components(candidate_ids, edges)
        logger.info("Built %d connected component(s) of size ≥ 2", len(components))

        coin_by_id = {c["eurio_id"]: c for c in candidates}
        groups: list[dict] = []
        clustered_ids: set[str] = set()
        for members_ids in components:
            members = [coin_by_id[eid] for eid in members_ids]
            g = build_group(members)
            groups.append(g)
            clustered_ids.update(members_ids)

        unmatched = [c for c in candidates if c["eurio_id"] not in clustered_ids]

        if args.dry_run:
            print_dry_run(groups, unmatched)
            print(f"DRY-RUN — no DB writes. Re-run with --apply to commit.")
            return 0

        apply_groups(sb, groups)
        print(
            json.dumps(
                {
                    "applied": True,
                    "groups": len(groups),
                    "coins_grouped": sum(len(g["members"]) for g in groups),
                    "standalone": len(unmatched),
                    "threshold": args.threshold,
                }
            )
        )
        return 0
    finally:
        sb.close()


if __name__ == "__main__":
    raise SystemExit(main())
