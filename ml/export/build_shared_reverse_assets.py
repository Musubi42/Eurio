"""Build the packaged common-side (carte) WebP assets for the APK.

The 2 € common side has exactly two map designs (v1 ≤2006, v2 ≥2007). They are
identical across all coins of an era, so we extract one clean representative
reverse photo per era, re-encode to WebP, and drop it into the Android assets
folder. These files are packaged in the APK (NOT hosted on Storage) and are
referenced by the `shared_reverse.asset_name` column.

Provenance (representative coins, German standard issues — clean centred maps):
    2eur-map-v1  ← de-2002-2eur-standard-1st-map
    2eur-map-v2  ← de-2008-2eur-standard-2nd-map

Usage::
    python -m export.build_shared_reverse_assets          # download + write assets
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

_ML_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ML_ROOT.parent
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

from export.app_export.io import get_sqlite_con  # noqa: E402
from referential.coin_image_storage import encode_webp  # noqa: E402

# Written to BOTH the APK assets (committed, packaged) and the proto data dir
# (gitignored, so the proto mimics the app with the same carte visuals).
_ASSET_DIRS = [
    _REPO_ROOT / "app-android" / "src" / "main" / "assets" / "shared_reverse",
    _REPO_ROOT / "docs" / "design" / "prototype" / "data" / "shared_reverse",
]
_MAX_WIDTH = 512

# shared_reverse.id -> (asset filename, representative coin eurio_id)
_ASSETS = {
    "2eur-map-v1": ("reverse_2eur_v1.webp", "de-2002-2eur-standard-1st-map"),
    "2eur-map-v2": ("reverse_2eur_v2.webp", "de-2008-2eur-standard-2nd-map"),
}


def _reverse_url(con, eurio_id: str) -> str | None:
    row = con.execute(
        "SELECT url FROM coin_canonical_images "
        "WHERE eurio_id=? AND role='reverse' AND url IS NOT NULL LIMIT 1",
        (eurio_id,),
    ).fetchone()
    return row["url"] if row else None


def main() -> int:
    con = get_sqlite_con()
    for d in _ASSET_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=30, follow_redirects=True)
    rc = 0
    try:
        for sr_id, (filename, eurio_id) in _ASSETS.items():
            url = _reverse_url(con, eurio_id)
            if not url:
                print(f"  {sr_id}: no reverse url for {eurio_id}", file=sys.stderr)
                rc = 1
                continue
            resp = client.get(url)
            resp.raise_for_status()
            data, w, h = encode_webp(resp.content, max_width=_MAX_WIDTH)
            for d in _ASSET_DIRS:
                (d / filename).write_bytes(data)
            print(f"  {sr_id}: {filename} ({w}x{h}, {len(data)} bytes) ← {eurio_id}")
    finally:
        client.close()
        con.close()
    for d in _ASSET_DIRS:
        print(f"  wrote: {d.relative_to(_REPO_ROOT)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
