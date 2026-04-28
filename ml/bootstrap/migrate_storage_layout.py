"""One-shot migration of `coin-images` to the per-eurio_id storage layout.

Old layout (legacy Numista pipeline):
    coin-images/{numista_id}/obverse-400.webp
    coin-images/{numista_id}/obverse-120.webp
    coin-images/{numista_id}/reverse-400.webp
    coin-images/{numista_id}/reverse-120.webp

Old layout (initial BCE pipeline, no thumb):
    coin-images/{eurio_id}/obverse_bce.webp

Target:
    coin-images/{eurio_id}/{role}_{source}.webp        # detail
    coin-images/{eurio_id}/{role}_{source}_thumb.webp  # thumb (120px)

For every Numista source, we server-side copy the existing object across all
eurio_ids that share the numista_id (zero CDN round-trips). For every BCE
source missing its thumb, we re-download the existing webp from Storage,
resize to 120px, upload alongside.

Two-phase by design:

    python -m bootstrap.migrate_storage_layout --plan       # dry, prints what will happen
    python -m bootstrap.migrate_storage_layout --apply      # do the writes
    python -m bootstrap.migrate_storage_layout --apply --prune  # also delete legacy {numista_id}/ paths
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from typing import Any

import httpx

from referential.coin_image_storage import (
    BUCKET_NAME,
    THUMB_QUALITY,
    THUMB_WIDTH,
    copy_object,
    encode_webp,
    normalize_legacy_images,
    public_url,
    remove_object,
    storage_key,
    upload_object,
)
from export.sync_to_supabase import load_env

NUMISTA_LEGACY_PATH_RX = re.compile(r"/coin-images/(\d+)/(obverse|reverse)-(\d+)\.webp$")
BCE_LEGACY_PATH_RX = re.compile(r"/coin-images/([^/]+)/(obverse|reverse)_bce\.webp$")


def fetch_all_coins(client: httpx.Client, rest_base: str) -> list[dict]:
    """Page through coins.images for every row that carries any image data."""
    out: list[dict] = []
    offset = 0
    page = 1000
    while True:
        resp = client.get(
            f"{rest_base}/coins",
            params={"select": "eurio_id,images,cross_refs"},
            headers={"Range": f"{offset}-{offset + page - 1}"},
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page:
            break
        offset += page
    return out


def parse_legacy_url(url: str) -> tuple[str, str, str, int | None] | None:
    """Return (kind, identifier, role, size_or_None).

    kind = 'numista' → identifier = numista_id (str), size = 400|120
    kind = 'bce'     → identifier = eurio_id, size = None
    """
    m = NUMISTA_LEGACY_PATH_RX.search(url)
    if m:
        return ("numista", m.group(1), m.group(2), int(m.group(3)))
    m = BCE_LEGACY_PATH_RX.search(url)
    if m:
        return ("bce", m.group(1), m.group(2), None)
    return None


def plan_for_coin(coin: dict, by_numista: dict[str, list[str]]) -> dict[str, Any]:
    """Compute the per-coin migration plan.

    Returns:
        {
          "eurio_id": ...,
          "ops": [
             {"kind": "copy", "src": "...", "dest": "..."},
             {"kind": "thumb", "src_eurio_id": "...", "role": "..."},
          ],
          "new_images": {...},
        }
    """
    eurio_id = coin["eurio_id"]
    legacy = normalize_legacy_images(coin.get("images") or {})
    ops: list[dict[str, Any]] = []
    new_images: dict[str, list[dict[str, Any]]] = {}

    for role in ("obverse", "reverse"):
        for variant in legacy.get(role, []):
            url = variant.get("url") or ""
            parsed = parse_legacy_url(url)
            source = variant.get("source") or "numista"

            new_detail_key = storage_key(eurio_id, role, source)
            new_thumb_key = storage_key(eurio_id, role, source, thumb=True)

            if parsed is None:
                # Already on the new layout (or unknown shape we leave alone).
                new_entry = dict(variant)
                new_entry["source"] = source
                new_images.setdefault(role, []).append(new_entry)
                continue

            kind, ident, parsed_role, size = parsed

            if kind == "numista":
                # Server-side copy detail (400) + thumb (120)
                src_detail = f"{ident}/{parsed_role}-400.webp"
                src_thumb = f"{ident}/{parsed_role}-120.webp"
                # Skip if already at destination (idempotent re-run)
                ops.append({"kind": "copy", "src": src_detail, "dest": new_detail_key})
                ops.append({"kind": "copy", "src": src_thumb, "dest": new_thumb_key})
            elif kind == "bce":
                # Detail already at destination; only generate the thumb.
                ops.append({
                    "kind": "thumb",
                    "src_key": storage_key(eurio_id, role, "bce_comm"),
                    "dest_key": new_thumb_key,
                })

            new_entry = {
                "source": source,
                "url": None,  # filled in later with public_url(supabase_url, ...)
                "thumb_url": None,
                "_detail_key": new_detail_key,
                "_thumb_key": new_thumb_key,
            }
            new_images.setdefault(role, []).append(new_entry)

    return {"eurio_id": eurio_id, "ops": ops, "new_images": new_images}


def finalize_images(plan: dict, supabase_url: str) -> dict[str, list[dict]]:
    """Replace internal _key markers with their public URLs."""
    out: dict[str, list[dict]] = {}
    for role, variants in plan["new_images"].items():
        out[role] = []
        for v in variants:
            entry = {k: val for k, val in v.items() if not k.startswith("_")}
            if "_detail_key" in v:
                entry["url"] = public_url(supabase_url, v["_detail_key"])
            elif entry.get("url") is None:
                entry["url"] = v.get("url")
            if "_thumb_key" in v:
                entry["thumb_url"] = public_url(supabase_url, v["_thumb_key"])
            out[role].append(entry)
    return out


def regen_bce_thumbs(
    rest_client: httpx.Client,
    storage_client: httpx.Client,
    rest_base: str,
    supabase_url: str,
    *,
    limit: int | None,
) -> int:
    """Generate the missing `*_bce_thumb.webp` for every coin with a BCE variant."""
    print("Fetching coins with BCE images ...")
    coins = fetch_all_coins(rest_client, rest_base)
    bce_coins: list[tuple[str, str]] = []  # (eurio_id, role)
    for c in coins:
        for role in ("obverse", "reverse"):
            for v in (c.get("images") or {}).get(role) or []:
                if isinstance(v, dict) and v.get("source") == "bce_comm":
                    bce_coins.append((c["eurio_id"], role))
    if limit is not None:
        bce_coins = bce_coins[:limit]
    print(f"  {len(bce_coins)} BCE variants to inspect")

    created = skipped = failed = 0
    for eurio_id, role in bce_coins:
        thumb_key = storage_key(eurio_id, role, "bce_comm", thumb=True)
        thumb_url = public_url(supabase_url, thumb_key)
        head = httpx.head(thumb_url, timeout=10)
        if head.status_code == 200:
            skipped += 1
            continue
        detail_key = storage_key(eurio_id, role, "bce_comm")
        detail_url = public_url(supabase_url, detail_key)
        try:
            resp = httpx.get(detail_url, timeout=20)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"  fetch FAIL {detail_url}: {e}")
            failed += 1
            continue
        thumb_bytes, _, _ = encode_webp(resp.content, max_width=THUMB_WIDTH, quality=THUMB_QUALITY)
        if upload_object(storage_client, supabase_url, thumb_key, thumb_bytes):
            created += 1
            if created % 25 == 0:
                print(f"  progress: created={created} skipped={skipped} failed={failed}")
        else:
            failed += 1

    print(f"\nDone. created={created} skipped={skipped} failed={failed}")
    return 0


def prune_legacy_objects(
    rest_client: httpx.Client,
    storage_client: httpx.Client,
    rest_base: str,
    supabase_url: str,
) -> int:
    """Find and delete every legacy `{numista_id}/{role}-{size}.webp` object.

    We list from `storage.objects` (cheap, exact) and batch-delete via
    `DELETE /storage/v1/object/{bucket}` which accepts up to 1000 prefixes
    per call. That avoids 1700+ single-shot DELETE HTTPs and the false-400
    "not_found" noise from probing keys that don't exist.
    """
    # Read the legacy keys directly from storage.objects via PostgREST RPC.
    sql = (
        "select name from storage.objects "
        "where bucket_id = 'coin-images' "
        "and (name like '%/obverse-400.webp' or name like '%/obverse-120.webp' "
        "  or name like '%/reverse-400.webp' or name like '%/reverse-120.webp')"
    )
    # PostgREST doesn't expose storage.objects directly, so we use the storage
    # `list` endpoint to enumerate root prefixes, then list each prefix.
    # Simpler path: hit /storage/v1/object/list/{bucket} with an empty prefix
    # (returns max 1000 entries per call).
    legacy_keys: list[str] = []
    offset = 0
    page = 1000
    while True:
        resp = storage_client.post(
            f"{supabase_url}/storage/v1/object/list/coin-images",
            json={"prefix": "", "limit": page, "offset": offset},
            timeout=30,
        )
        if resp.status_code >= 400:
            print(f"  list FAIL: HTTP {resp.status_code} {resp.text[:200]}")
            break
        rows = resp.json()
        if not rows:
            break
        # Top-level entries (folders return as `{name: '287622', id: null, ...}`,
        # files return with metadata.size). For each numeric folder we drill in.
        for row in rows:
            name = row.get("name", "")
            # Only fold the legacy {numista_id} folders (all-digit names).
            if name.isdigit():
                # List this folder's contents.
                inner_off = 0
                while True:
                    inner = storage_client.post(
                        f"{supabase_url}/storage/v1/object/list/coin-images",
                        json={"prefix": name, "limit": page, "offset": inner_off},
                        timeout=30,
                    )
                    if inner.status_code >= 400:
                        break
                    inner_rows = inner.json()
                    if not inner_rows:
                        break
                    for ir in inner_rows:
                        fname = ir.get("name", "")
                        if fname.endswith((".webp",)):
                            legacy_keys.append(f"{name}/{fname}")
                    if len(inner_rows) < page:
                        break
                    inner_off += page
        if len(rows) < page:
            break
        offset += page

    print(f"  found {len(legacy_keys)} legacy objects to delete")
    if not legacy_keys:
        return 0

    # Batch delete: Supabase's DELETE /object/{bucket} accepts {"prefixes": [...]} (up to ~1000).
    removed = 0
    BATCH = 200
    for i in range(0, len(legacy_keys), BATCH):
        batch = legacy_keys[i : i + BATCH]
        resp = storage_client.request(
            "DELETE",
            f"{supabase_url}/storage/v1/object/coin-images",
            json={"prefixes": batch},
            timeout=60,
        )
        if resp.status_code < 400:
            removed += len(batch)
            print(f"  batch {i // BATCH + 1}: deleted {len(batch)}")
        else:
            print(f"  batch {i // BATCH + 1} FAIL: HTTP {resp.status_code} {resp.text[:160]}")
    return removed


def discover_numista(
    rest_client: httpx.Client,
    storage_client: httpx.Client,
    rest_base: str,
    supabase_url: str,
    *,
    limit: int | None,
) -> int:
    """Recover Numista images orphaned in {numista_id}/ by past BCE overwrites.

    For each coin with a cross_refs.numista_id, probe whether the legacy
    {numista_id}/obverse-400.webp object exists in storage. When yes, copy
    detail+thumb for both faces into the per-eurio_id layout and merge a
    Numista variant into coins.images. Pure server-side copy — no Numista CDN
    calls. Idempotent: skips coins where a Numista variant is already present.
    """
    print("Fetching coins with numista_id ...")
    coins = fetch_all_coins(rest_client, rest_base)
    candidates: list[tuple[str, str]] = []  # (eurio_id, numista_id)
    for c in coins:
        nid = (c.get("cross_refs") or {}).get("numista_id")
        if nid is None:
            continue
        # Skip if Numista variant already linked
        existing = (c.get("images") or {}).get("obverse") or []
        if isinstance(existing, list) and any(
            isinstance(v, dict) and v.get("source") == "numista" for v in existing
        ):
            continue
        candidates.append((c["eurio_id"], str(nid)))
    if limit is not None:
        candidates = candidates[:limit]
    print(f"  {len(candidates)} candidate coins (numista_id set, no Numista variant linked yet)")

    # Index coins by eurio_id for quick re-fetch of current images shape.
    by_eurio: dict[str, dict] = {c["eurio_id"]: c for c in coins}

    discovered = copies = patches = no_legacy = failed = 0

    for eurio_id, nid in candidates:
        # Probe whether the Numista detail exists in legacy layout.
        probe_url = public_url(supabase_url, f"{nid}/obverse-400.webp")
        head = httpx.head(probe_url, timeout=10)
        if head.status_code != 200:
            no_legacy += 1
            continue
        discovered += 1

        # Build the Numista variants for both faces (when each legacy file exists).
        new_variants: dict[str, dict[str, Any]] = {}
        for role in ("obverse", "reverse"):
            src_detail = f"{nid}/{role}-400.webp"
            src_thumb = f"{nid}/{role}-120.webp"
            dest_detail = storage_key(eurio_id, role, "numista")
            dest_thumb = storage_key(eurio_id, role, "numista", thumb=True)
            # Probe role-specific (reverse may not exist for all coins)
            face_head = httpx.head(public_url(supabase_url, src_detail), timeout=10)
            if face_head.status_code != 200:
                continue
            ok1 = copy_object(storage_client, supabase_url, src_detail, dest_detail)
            ok2 = copy_object(storage_client, supabase_url, src_thumb, dest_thumb)
            if not (ok1 and ok2):
                failed += 1
                continue
            copies += 1
            new_variants[role] = {
                "source": "numista",
                "url": public_url(supabase_url, dest_detail),
                "thumb_url": public_url(supabase_url, dest_thumb),
            }

        if not new_variants:
            continue

        # Merge into coins.images (preserving existing BCE entries).
        current_images = by_eurio[eurio_id].get("images") or {}
        new_images: dict[str, list[dict]] = {}
        for role in ("obverse", "reverse"):
            existing_role = current_images.get(role)
            role_list = list(existing_role) if isinstance(existing_role, list) else []
            role_list = [v for v in role_list if v.get("source") != "numista"]
            if role in new_variants:
                role_list.append(new_variants[role])
            if role_list:
                new_images[role] = role_list

        resp = rest_client.patch(
            f"{rest_base}/coins",
            params={"eurio_id": f"eq.{eurio_id}"},
            json={"images": new_images},
        )
        if resp.status_code < 400:
            patches += 1
        else:
            print(f"  patch FAIL {eurio_id}: HTTP {resp.status_code}")
            failed += 1

        if patches and patches % 25 == 0:
            print(f"  progress: discovered={discovered} copies={copies} patches={patches}")

    print(f"\nDone. discovered={discovered} copies={copies} patches={patches} "
          f"no_legacy={no_legacy} failed={failed}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="Print the plan, don't write")
    ap.add_argument("--apply", action="store_true", help="Execute the migration")
    ap.add_argument("--prune", action="store_true",
                    help="After --apply, also delete legacy {numista_id}/* objects")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only the first N coins (handy for smoke tests)")
    ap.add_argument(
        "--regen-bce-thumbs",
        action="store_true",
        help="Standalone mode: scan coins.images for BCE variants missing a "
             "thumb in Storage, download the detail webp, resize to 120 and "
             "upload as obverse_bce_thumb.webp. Idempotent.",
    )
    ap.add_argument(
        "--discover-numista",
        action="store_true",
        help="Standalone mode: for every coin with cross_refs.numista_id, "
             "check if a legacy {numista_id}/obverse-400.webp exists in "
             "storage and, if so, server-side copy it into the per-eurio_id "
             "layout and merge it into coins.images.obverse[]. Picks up "
             "Numista images that were orphaned by past BCE runs. Idempotent.",
    )
    args = ap.parse_args()
    if not (args.plan or args.apply or args.regen_bce_thumbs or args.discover_numista):
        ap.error("must pass --plan, --apply, --regen-bce-thumbs, or --discover-numista")

    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (supabase_url and supabase_key):
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing", file=sys.stderr)
        return 2

    rest_headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    storage_headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    with httpx.Client(headers=rest_headers, timeout=60) as rest_client, \
         httpx.Client(headers=storage_headers, timeout=60) as storage_client:

        if args.regen_bce_thumbs:
            return regen_bce_thumbs(
                rest_client, storage_client, rest_base, supabase_url,
                limit=args.limit,
            )

        if args.discover_numista:
            return discover_numista(
                rest_client, storage_client, rest_base, supabase_url,
                limit=args.limit,
            )

        print("Fetching coins ...")
        coins = fetch_all_coins(rest_client, rest_base)
        if args.limit is not None:
            coins = coins[: args.limit]
        print(f"  {len(coins)} coins (limit applied: {args.limit})" if args.limit
              else f"  {len(coins)} coins")

        # Group by numista_id so we can dedupe copies across siblings.
        by_numista: dict[str, list[str]] = {}
        for c in coins:
            nid = (c.get("cross_refs") or {}).get("numista_id")
            if nid is not None:
                by_numista.setdefault(str(nid), []).append(c["eurio_id"])

        plans = [plan_for_coin(c, by_numista) for c in coins]
        ops_total = sum(len(p["ops"]) for p in plans)
        print(f"  {sum(1 for p in plans if p['ops'])} coins to migrate, "
              f"{ops_total} storage ops")

        if args.plan:
            for p in plans[:5]:
                if not p["ops"]:
                    continue
                print(f"\n  {p['eurio_id']}:")
                for op in p["ops"][:6]:
                    print(f"    {op}")
            print("\n--plan: nothing written.")
            return 0

        copies = thumbs = patches = failures = 0
        copy_seen: set[tuple[str, str]] = set()
        for i, plan in enumerate(plans, 1):
            if not plan["ops"]:
                continue
            eurio_id = plan["eurio_id"]
            for op in plan["ops"]:
                if op["kind"] == "copy":
                    pair = (op["src"], op["dest"])
                    if pair in copy_seen:
                        continue
                    copy_seen.add(pair)
                    if copy_object(storage_client, supabase_url, op["src"], op["dest"]):
                        copies += 1
                    else:
                        failures += 1
                elif op["kind"] == "thumb":
                    # Download the existing detail webp, resize to 120, upload.
                    src_url = public_url(supabase_url, op["src_key"])
                    try:
                        resp = httpx.get(src_url, timeout=20)
                        resp.raise_for_status()
                        data = resp.content
                    except httpx.HTTPError as e:
                        print(f"    thumb fetch FAIL {src_url}: {e}")
                        failures += 1
                        continue
                    thumb_bytes, _, _ = encode_webp(data, max_width=THUMB_WIDTH, quality=THUMB_QUALITY)
                    if upload_object(storage_client, supabase_url, op["dest_key"], thumb_bytes):
                        thumbs += 1
                    else:
                        failures += 1

            new_images = finalize_images(plan, supabase_url)
            resp = rest_client.patch(
                f"{rest_base}/coins",
                params={"eurio_id": f"eq.{eurio_id}"},
                json={"images": new_images},
            )
            if resp.status_code < 400:
                patches += 1
            else:
                print(f"    patch FAIL {eurio_id}: HTTP {resp.status_code} {resp.text[:200]}")
                failures += 1

            if i % 50 == 0:
                print(f"  progress {i}/{len(plans)}  copies={copies} thumbs={thumbs} patches={patches}")

        print(f"\nMigration done. copies={copies} thumbs={thumbs} patches={patches} failures={failures}")

        if args.prune:
            print("\nPruning legacy {numista_id}/* objects ...")
            removed = prune_legacy_objects(rest_client, storage_client, rest_base, supabase_url)
            print(f"  removed {removed} legacy objects")

    return 0


if __name__ == "__main__":
    sys.exit(main())
