"""Enrich the Eurio referential with Numista type IDs and images.

Adds "numista_id" to the cross_refs dict of matching coins in
eurio_referential.json, then optionally patches Supabase directly.

With --images, also fetches official coin photos from Numista API,
resizes them (400px detail + 120px thumbnail as WebP), uploads to
Supabase Storage, and updates the images JSONB column.

Usage:
    python ml/enrich_from_numista.py              # Enrich numista_id only
    python ml/enrich_from_numista.py --images     # + fetch/resize/upload images
    python ml/enrich_from_numista.py --dry-run    # Preview without writing
    python ml/enrich_from_numista.py --no-supabase # Referential only, skip Supabase
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from referential.eurio_referential import load_referential, save_referential
from referential.import_numista import get_type_details
from referential.numista_keys import KeyManager
from referential.coin_image_storage import (
    BUCKET_NAME,
    ImageVariant,
    copy_variant,
    merge_variant,
    storage_key,
    upload_variant,
)
from export.sync_to_supabase import load_env
from state.sources_runs import record_run

# ---------------------------------------------------------------------------
# Hardcoded mapping: Numista type ID -> matching criteria
#
# For standard coins, one Numista type covers a design era (multiple years).
# For commemoratives, we match by eurio_id directly to avoid ambiguity.
# ---------------------------------------------------------------------------

NUMISTA_MAPPING: list[dict[str, Any]] = [
    {
        "numista_id": 87,
        "description": "1 Euro Spain - Juan Carlos I",
        "country": "ES",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 1999,
        "max_year": 2014,
    },
    {
        "numista_id": 111,
        "description": "1 Euro Germany - Eagle",
        "country": "DE",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 2002,
        "max_year": None,  # same design all years
    },
    {
        "numista_id": 135,
        "description": "1 Euro Italy - Vitruvian Man",
        "country": "IT",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 2002,
        "max_year": None,  # same design all years
    },
    {
        "numista_id": 159,
        "description": "1 Euro Portugal - Royal Seal (old design)",
        "country": "PT",
        "face_value": 1.0,
        "is_commemorative": False,
        "min_year": 2002,
        "max_year": 2007,  # Portugal changed design in 2008
    },
    {
        # Commemorative: match by eurio_id to avoid ambiguity
        # (Germany has 2 commémo 2EUR in 2020: Kniefall + Sanssouci)
        "numista_id": 226447,
        "description": "2 Euro Germany 2020 - Kniefall von Warschau",
        "eurio_id": "de-2020-2eur-50-years-since-the-kniefall-von-warschau",
    },
]

NUMISTA_DETAIL_WIDTH = 400  # downscale Numista source to 400 for detail
NUMISTA_CDN_DELAY = 0.5  # seconds between image downloads


def find_matching_entries(
    referential: dict[str, dict[str, Any]],
    mapping: dict[str, Any],
) -> list[str]:
    """Return eurio_ids matching a Numista type mapping entry."""
    # Direct eurio_id match (for commemoratives)
    if "eurio_id" in mapping:
        eid = mapping["eurio_id"]
        return [eid] if eid in referential else []

    # Range match for standard coins
    matches = []
    for eurio_id, entry in referential.items():
        ident = entry.get("identity", {})
        if ident.get("country") != mapping["country"]:
            continue
        if ident.get("face_value") != mapping["face_value"]:
            continue
        if bool(ident.get("is_commemorative")) != mapping["is_commemorative"]:
            continue
        year = ident.get("year")
        if year is None:
            continue
        if mapping.get("min_year") and year < mapping["min_year"]:
            continue
        if mapping.get("max_year") and year > mapping["max_year"]:
            continue
        matches.append(eurio_id)
    return sorted(matches)


def _mapping_country(mapping: dict[str, Any]) -> str | None:
    """Return the ISO2 country a mapping entry targets (explicit field or eurio_id prefix)."""
    if mapping.get("country"):
        return mapping["country"].upper()
    eid = mapping.get("eurio_id") or ""
    head = eid.split("-", 1)[0]
    return head.upper() if len(head) == 2 else None


def enrich_referential(
    referential: dict[str, dict[str, Any]],
    mapping_list: list[dict[str, Any]] | None = None,
) -> tuple[int, list[tuple[str, int]]]:
    """Add numista_id to cross_refs for all matching entries.

    Returns (total_enriched, list of (eurio_id, numista_id) pairs).
    """
    today = date.today().isoformat()
    enriched: list[tuple[str, int]] = []
    mappings = mapping_list if mapping_list is not None else NUMISTA_MAPPING

    for mapping in mappings:
        numista_id = mapping["numista_id"]
        matched = find_matching_entries(referential, mapping)

        if not matched:
            print(f"  WARNING: no match for Numista {numista_id} ({mapping['description']})")
            continue

        for eurio_id in matched:
            entry = referential[eurio_id]
            if "cross_refs" not in entry:
                entry["cross_refs"] = {}
            entry["cross_refs"]["numista_id"] = numista_id
            entry["provenance"]["last_updated"] = today
            enriched.append((eurio_id, numista_id))

        print(f"  Numista {numista_id:>6} -> {len(matched):>2} coins  ({mapping['description']})")

    return len(enriched), enriched


# ---------------------------------------------------------------------------
# Image pipeline: fetch from Numista → resize → WebP → upload to Storage
# ---------------------------------------------------------------------------


def _extract_type_mintage(details: dict[str, Any]) -> int | None:
    """Pick the mintage figure from a Numista /types/{id} response when unambiguous.

    For multi-issue types (circulation coins covering many years) Numista returns
    a per-issue mintage list, not a single number — we can't safely reduce that
    to a coin-row scalar, so we return None. For single-issue commemorative types
    we lift the lone issue's mintage.
    """
    direct = details.get("mintage")
    if isinstance(direct, int) and direct > 0:
        return direct
    issues = details.get("issues")
    if isinstance(issues, list) and len(issues) == 1:
        m = issues[0].get("mintage")
        if isinstance(m, int) and m > 0:
            return m
    return None


def fetch_numista_image_urls(
    km: KeyManager,
    mapping_list: list[dict[str, Any]] | None = None,
) -> tuple[dict[int, dict[str, str]], dict[int, int]]:
    """Fetch obverse/reverse image URLs + mintage from Numista API for each mapped type.

    Returns ({numista_id: {"obverse": url, "reverse": url}}, {numista_id: mintage}).
    Uses 1 API call per type.
    """
    urls: dict[int, dict[str, str]] = {}
    mintages: dict[int, int] = {}
    mappings = mapping_list if mapping_list is not None else NUMISTA_MAPPING
    for mapping in mappings:
        nid = mapping["numista_id"]
        print(f"  GET /types/{nid} ...", end=" ", flush=True)
        try:
            details = km.call(get_type_details, nid)
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"FAIL ({e})")
            continue

        obverse_url = details.get("obverse", {}).get("picture")
        reverse_url = details.get("reverse", {}).get("picture")
        urls[nid] = {}
        if obverse_url:
            urls[nid]["obverse"] = obverse_url
        if reverse_url:
            urls[nid]["reverse"] = reverse_url

        mintage = _extract_type_mintage(details)
        if mintage:
            mintages[nid] = mintage

        print(
            f"OK (obverse={'yes' if obverse_url else 'no'}, "
            f"reverse={'yes' if reverse_url else 'no'}, "
            f"mintage={mintage if mintage else 'n/a'})"
        )
        time.sleep(0.5)  # respect Numista API rate limit

    return urls, mintages


def download_image(url: str) -> bytes | None:
    """Download a single image from Numista CDN."""
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
        print(f"    bad response: HTTP {resp.status_code}, {len(resp.content)} bytes")
    except httpx.HTTPError as e:
        print(f"    download error: {e}")
    return None


def process_images(
    image_urls: dict[int, dict[str, str]],
    enriched: list[tuple[str, int]],
    referential: dict[str, dict[str, Any]],
    dry_run: bool = False,
    skip_supabase: bool = False,
) -> None:
    """Download Numista images, encode + upload to the first eurio_id of each
    numista group, then server-side copy to siblings (same numista_id covers
    multiple eurio_ids — one CDN fetch is enough).

    Updates `entry["images"]` to the new array shape and patches Supabase.
    """
    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not dry_run and not skip_supabase and (not supabase_url or not supabase_key):
        print("  WARNING: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found, skipping upload")
        skip_supabase = True

    today = date.today().isoformat()

    # Group eurio_ids by numista_id so we can upload once + copy to siblings.
    eurio_ids_by_nid: dict[int, list[str]] = {}
    for eurio_id, nid in enriched:
        eurio_ids_by_nid.setdefault(nid, []).append(eurio_id)

    storage_headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }
    rest_headers = {
        **storage_headers,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    uploaded = 0
    copied = 0
    failed = 0
    patched = 0

    with httpx.Client(headers=storage_headers, timeout=60) as storage_client, \
         httpx.Client(headers=rest_headers, timeout=60) as rest_client:

        for nid, eurio_ids in eurio_ids_by_nid.items():
            face_urls = image_urls.get(nid) or {}
            if not face_urls:
                continue
            print(f"\n  Numista {nid} → {len(eurio_ids)} eurio_id(s)")

            # variants_per_face[face] = ImageVariant from the canonical (first) upload
            variants_per_face: dict[str, ImageVariant] = {}
            primary = eurio_ids[0]

            for face in ("obverse", "reverse"):
                src_url = face_urls.get(face)
                if not src_url:
                    continue
                print(f"    {face}: GET CDN ...", end=" ", flush=True)
                if dry_run:
                    print("(dry-run)")
                    continue
                raw = download_image(src_url)
                if not raw:
                    failed += 1
                    continue
                print(f"{len(raw) // 1024} KB")

                if skip_supabase:
                    continue

                variant = upload_variant(
                    storage_client, supabase_url,
                    primary, face, "numista",
                    raw,
                    detail_max_width=NUMISTA_DETAIL_WIDTH,
                )
                if variant is None:
                    failed += 1
                    continue
                uploaded += 1
                print(f"      → {primary}/{face}_numista.webp "
                      f"{variant['width']}×{variant['height']} ({variant['bytes'] // 1024} KB)")
                variants_per_face[face] = variant

                # Server-side copy to the other eurio_ids sharing this numista_id.
                for sibling in eurio_ids[1:]:
                    sib_var = copy_variant(
                        storage_client, supabase_url,
                        src_eurio_id=primary, dest_eurio_id=sibling,
                        role=face, source="numista",
                        width=variant["width"], height=variant["height"], bytes_=variant["bytes"],
                    )
                    if sib_var is not None:
                        copied += 1
                    else:
                        failed += 1

                time.sleep(NUMISTA_CDN_DELAY)

            if not variants_per_face:
                continue

            # Update each eurio_id's coins.images (and the local referential).
            for eurio_id in eurio_ids:
                entry = referential[eurio_id]
                images = entry.get("images") or {}
                for face, variant in variants_per_face.items():
                    if eurio_id == primary:
                        v = variant
                    else:
                        # Reconstruct the per-eurio_id URL (same shape, different prefix)
                        v = {
                            **variant,
                            "url": variant["url"].replace(f"/{primary}/", f"/{eurio_id}/"),
                            "thumb_url": variant.get("thumb_url", "").replace(
                                f"/{primary}/", f"/{eurio_id}/"
                            ),
                        }
                    images = merge_variant(images, face, v)
                entry["images"] = images
                entry.setdefault("provenance", {})["last_updated"] = today

                if not dry_run and not skip_supabase:
                    resp = rest_client.patch(
                        f"{rest_base}/coins",
                        params={"eurio_id": f"eq.{eurio_id}"},
                        json={"images": entry["images"]},
                    )
                    if resp.status_code < 400:
                        patched += 1
                    else:
                        print(f"    patch FAIL {eurio_id}: HTTP {resp.status_code}")

    if not dry_run:
        print(f"\n  Storage: {uploaded} uploaded, {copied} server-side copied, {failed} failed")
        print(f"  DB: patched {patched} coins.images")


# ---------------------------------------------------------------------------
# Supabase cross_refs update (existing)
# ---------------------------------------------------------------------------


def update_supabase_cross_refs(
    enriched: list[tuple[str, int]], referential: dict[str, dict[str, Any]]
) -> None:
    """Patch cross_refs in Supabase for enriched coins."""
    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("  SKIP Supabase: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found in .env")
        return

    base = url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    patched = 0
    errors = 0
    with httpx.Client(headers=headers, timeout=60) as client:
        for eurio_id, _ in enriched:
            cross_refs = referential[eurio_id].get("cross_refs", {})
            resp = client.patch(
                f"{base}/coins",
                params={"eurio_id": f"eq.{eurio_id}"},
                json={"cross_refs": cross_refs},
            )
            if resp.status_code >= 400:
                print(f"    FAIL {eurio_id}: HTTP {resp.status_code} {resp.text[:200]}")
                errors += 1
            else:
                patched += 1

    print(f"  Supabase: patched {patched} coins" + (f", {errors} errors" if errors else ""))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def discover_existing_mappings(
    referential: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a mapping list from numista_ids already present in the referential.

    Use this with `--scan-referential` to fetch images for coins that have been
    matched to a Numista type by previous runs of `batch_match_numista.py`,
    without needing a hardcoded `NUMISTA_MAPPING` entry.
    """
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for entry in referential.values():
        nid = (entry.get("cross_refs") or {}).get("numista_id")
        if not isinstance(nid, int) or nid in seen:
            continue
        seen.add(nid)
        ident = entry.get("identity", {})
        out.append({
            "numista_id": nid,
            "description": f"{ident.get('country', '??')} {ident.get('year', '?')} "
                           f"{ident.get('face_value', '?')} — discovered",
            "country": ident.get("country"),
            "face_value": float(ident.get("face_value")) if ident.get("face_value") is not None else None,
            "is_commemorative": bool(ident.get("is_commemorative")),
            "min_year": ident.get("year"),
            "max_year": ident.get("year"),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--no-supabase", action="store_true", help="Skip Supabase updates")
    parser.add_argument("--images", action="store_true", help="Fetch, resize & upload coin images")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N mapping entries")
    parser.add_argument("--countries", default=None, help="Comma-separated ISO2 country filter")
    parser.add_argument(
        "--scan-referential",
        action="store_true",
        help="Process every numista_id already mapped in the referential "
             "(instead of the hardcoded NUMISTA_MAPPING).",
    )
    args = parser.parse_args()

    countries_filter: set[str] | None = None
    if args.countries:
        countries_filter = {c.strip().upper() for c in args.countries.split(",") if c.strip()}

    env = load_env()

    print("Loading referential...")
    referential = load_referential()
    print(f"  {len(referential)} entries loaded")

    if args.scan_referential:
        mapping_list = discover_existing_mappings(referential)
        print(f"  --scan-referential: {len(mapping_list)} numista_ids discovered in referential")
    else:
        mapping_list = NUMISTA_MAPPING
    if countries_filter:
        before = len(mapping_list)
        mapping_list = [m for m in mapping_list if _mapping_country(m) in countries_filter]
        print(f"  --countries {sorted(countries_filter)}: {len(mapping_list)}/{before} mappings kept")
    if args.limit is not None:
        mapping_list = mapping_list[: args.limit]
        print(f"  --limit {args.limit}: processing {len(mapping_list)} mapping(s)")

    print("\nMatching Numista IDs:")
    total, enriched = enrich_referential(referential, mapping_list)
    print(f"\n  Total: {total} coins enriched with numista_id")

    if not enriched:
        print("Nothing to do.")
        return 0

    # --- Image pipeline ---
    if args.images:
        try:
            km = KeyManager()
        except RuntimeError as e:
            print(f"\nERROR: {e}")
            return 2

        print(f"\nFetching image URLs from Numista API ({len(mapping_list)} calls)...")
        image_urls, mintages = fetch_numista_image_urls(km, mapping_list)
        print(f"  Got URLs for {len(image_urls)} types, mintage for {len(mintages)}")

        # Apply Numista mintage to every matched coin (priority source over BCE).
        for eurio_id, nid in enriched:
            m = mintages.get(nid)
            if m:
                referential[eurio_id].setdefault("identity", {})["mintage"] = m

        print("\nProcessing images (download → resize → upload)...")
        process_images(
            image_urls,
            enriched,
            referential,
            dry_run=args.dry_run,
            skip_supabase=args.no_supabase,
        )

    # --- Save referential ---
    if args.dry_run:
        print("\n--dry-run: not writing anything.")
        return 0

    print("\nSaving referential...")
    save_referential(referential)
    print("  Done.")

    # --- Patch Supabase cross_refs ---
    if not args.no_supabase:
        print("\nUpdating Supabase cross_refs...")
        update_supabase_cross_refs(enriched, referential)

    if args.images:
        record_run("numista_images", "enrich_with_images",
                   calls=len(image_urls), added_coins=total)
    else:
        record_run("numista_enrich", "enrich", calls=0, added_coins=total)

    print("\nNext steps:")
    print("  go-task android:snapshot   # regenerate catalog_snapshot.json")
    print("  go-task android:build      # rebuild APK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
