"""Upload each app coin's canonical AVERS (obverse / national side) to Supabase
Storage and populate the `coin_image` table. P3 of the app-facing rebuild.

The common side (carte) is NOT hosted here — it is packaged in the APK via
`shared_reverse` (see export/build_shared_reverse_assets.py). Storage only holds
the unique national side, fetched on-demand by the app.

Per coin we pick the best obverse source by priority:
    bce_official (local webp) > eurlex_jo (local webp) > numista_api (url, downloaded)

Storage key (app-facing, single canonical obverse, no source suffix):
    coin-images/{eurio_id}/obverse.webp

Usage::
    python -m export.upload_app_obverse --dry-run    # resolve sources, print plan
    python -m export.upload_app_obverse --apply       # empty bucket + upload + populate
    python -m export.upload_app_obverse --apply --no-empty   # keep existing objects
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

_ML_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ML_ROOT.parent
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

from export.app_export.io import delete_all, get_pg_client, get_sqlite_con, upsert  # noqa: E402
from export.sync_to_supabase import load_env  # noqa: E402
from referential.coin_image_storage import (  # noqa: E402
    BUCKET_NAME,
    encode_webp,
    upload_object,
)

# Best-source priority for the obverse (national side).
_SOURCE_PRIORITY = {"bce_official": 1, "eurlex_jo": 2, "numista_api": 3}
_DETAIL_MAX_WIDTH = 400
_OBVERSE_KEY = "{eurio_id}/obverse.webp"


def resolve_obverse_sources(con) -> list[dict]:
    """One winning obverse row per coin (best source), with local_path or url."""
    rows = con.execute(
        """
        SELECT i.eurio_id, i.source, i.local_path, i.url
        FROM coin_canonical_images i
        WHERE i.role = 'obverse'
          AND i.eurio_id IN (SELECT eurio_id FROM coins)
        """
    ).fetchall()
    best: dict[str, dict] = {}
    for r in rows:
        prio = _SOURCE_PRIORITY.get(r["source"], 99)
        cur = best.get(r["eurio_id"])
        if cur is None or prio < cur["_prio"]:
            best[r["eurio_id"]] = {
                "eurio_id": r["eurio_id"],
                "source": r["source"],
                "local_path": r["local_path"],
                "url": r["url"],
                "_prio": prio,
            }
    return sorted(best.values(), key=lambda d: d["eurio_id"])


def _retry(fn, *, tries: int = 3, what: str = ""):
    """Call fn() up to `tries` times, swallowing httpx errors between attempts."""
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except httpx.HTTPError as exc:
            last = exc
            if attempt < tries:
                continue
    print(f"    {what} FAIL after {tries} tries: {last}", file=sys.stderr)
    return None


def _load_raw(client: httpx.Client, entry: dict) -> bytes | None:
    """Return the raw image bytes for an obverse entry (local file or download)."""
    local = entry.get("local_path")
    if local:
        path = _REPO_ROOT / local
        if path.is_file():
            return path.read_bytes()
    url = entry.get("url")
    if url:
        def _get():
            resp = client.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
        return _retry(_get, what=f"download {entry['eurio_id']}")
    return None


def empty_bucket(client: httpx.Client, supabase_url: str) -> None:
    """Empty the coin-images bucket (removes all objects).

    The empty operation propagates asynchronously server-side; we pause briefly
    so it does not race with (and delete) the first objects we re-upload.
    """
    resp = client.post(f"{supabase_url}/storage/v1/bucket/{BUCKET_NAME}/empty")
    resp.raise_for_status()
    time.sleep(5)
    print(f"  bucket '{BUCKET_NAME}' emptied")


def run(apply: bool, empty: bool) -> int:
    con = get_sqlite_con()
    entries = resolve_obverse_sources(con)
    n_local = sum(1 for e in entries if e["local_path"])
    n_url = len(entries) - n_local
    print(f"  obverse to process: {len(entries)} coins ({n_local} local, {n_url} download)")

    if not apply:
        by_source: dict[str, int] = {}
        for e in entries:
            by_source[e["source"]] = by_source.get(e["source"], 0) + 1
        for src, n in sorted(by_source.items()):
            print(f"    {src}: {n}")
        con.close()
        return 0

    env = load_env()
    supabase_url = env["SUPABASE_URL"].rstrip("/")
    key = env["SUPABASE_SERVICE_ROLE_KEY"]
    storage = httpx.Client(
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=60,
    )

    if empty:
        empty_bucket(storage, supabase_url)

    image_rows: list[dict] = []
    ok = fail = 0
    for i, e in enumerate(entries, 1):
        raw = _load_raw(storage, e)
        if raw is None:
            fail += 1
            continue
        try:
            data, w, h = encode_webp(raw, max_width=_DETAIL_MAX_WIDTH)
        except Exception as exc:
            print(f"    encode FAIL {e['eurio_id']}: {exc}", file=sys.stderr)
            fail += 1
            continue
        skey = _OBVERSE_KEY.format(eurio_id=e["eurio_id"])
        uploaded = _retry(
            lambda: upload_object(storage, supabase_url, skey, data),
            what=f"upload {e['eurio_id']}",
        )
        if not uploaded:
            fail += 1
            continue
        image_rows.append({
            "eurio_id": e["eurio_id"],
            "role": "obverse",
            "storage_path": skey,
            "source": e["source"],
            "license": None,
            "width": w,
            "height": h,
        })
        ok += 1
        if i % 50 == 0:
            print(f"    {i}/{len(entries)} processed")

    storage.close()
    con.close()
    print(f"  uploaded {ok}, failed {fail}")

    # Populate coin_image (full refresh).
    pg = get_pg_client()
    try:
        delete_all(pg, "coin_image", "id")
        upsert(pg, "coin_image", image_rows)
    finally:
        pg.close()
    print(f"  coin_image: {len(image_rows)} rows upserted")
    return 0 if fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Upload + populate coin_image.")
    mode.add_argument("--dry-run", action="store_true", help="Resolve sources, print plan.")
    ap.add_argument("--no-empty", action="store_true", help="Do not empty the bucket first.")
    args = ap.parse_args()
    print(f"[{'apply' if args.apply else 'dry-run'}]")
    return run(apply=args.apply, empty=not args.no_empty)


if __name__ == "__main__":
    sys.exit(main())
