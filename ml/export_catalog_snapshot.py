"""Export a catalog snapshot from Supabase into the Android assets folder.

Reads the canonical tables (coins, coin_series, sets, set_members) via
PostgREST using the service role key and writes a single JSON file:

    app-android/src/main/assets/catalog_snapshot.json

The snapshot is embedded in every APK build so that the app is usable
offline on first launch (before any network sync). The Android
`CatalogBootstrapper` reads it at first run and hydrates Room.

Schema of the emitted JSON mirrors
`com.musubi.eurio.data.local.bootstrap.CatalogSnapshot`:

    {
      "catalog_version": "2026-04-15T12:00:00Z",
      "generated_at":    "2026-04-15T12:00:00Z",
      "coins": [ { eurio_id, numista_id, country, year, face_value,
                   issue_type, series_id, name_fr, name_en,
                   image_obverse_url, image_reverse_url, mintage,
                   is_withdrawn, withdrawal_reason, design_description,
                   theme_code }, ... ],
      "coin_series": [ { id, country, designation, designation_i18n,
                         minting_started_at, minting_ended_at,
                         minting_end_reason, supersedes_series_id }, ... ],
      "sets": [ { id, kind, name_i18n, description_i18n, criteria,
                  param_key, reward, display_order, category, icon,
                  expected_count, active }, ... ],
      "set_members": [ { set_id, eurio_id, position }, ... ]
    }

Usage:
    python ml/export_catalog_snapshot.py              # write the file
    python ml/export_catalog_snapshot.py --dry-run    # print counts only
    python ml/export_catalog_snapshot.py --only-active-sets   # filter sets.active
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from sync_to_supabase import load_env

SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent
    / "app-android"
    / "src"
    / "main"
    / "assets"
    / "catalog_snapshot.json"
)

# Columns we actually need on the mobile client — kept explicit to avoid
# shipping legacy/internal columns (created_at, updated_at, etc).
# Schéma réel (voir supabase/types/database.ts) : les coins n'ont ni `name`
# ni `name_i18n` ni `theme_code` ni `numista_id` direct. On tire le Numista ID
# depuis cross_refs et on dérive un libellé d'affichage depuis theme/face_value.
COIN_COLUMNS = [
    "eurio_id",
    "country",
    "year",
    "face_value",
    "issue_type",
    "series_id",
    "images",
    "cross_refs",
    "mintage",
    "is_commemorative",
    "is_withdrawn",
    "withdrawal_reason",
    "design_description",
    "theme",
]

COIN_SERIES_COLUMNS = [
    "id",
    "country",
    "designation",
    "designation_i18n",
    "minting_started_at",
    "minting_ended_at",
    "minting_end_reason",
    "supersedes_series_id",
]

SET_COLUMNS = [
    "id",
    "kind",
    "name_i18n",
    "description_i18n",
    "criteria",
    "param_key",
    "reward",
    "display_order",
    "category",
    "icon",
    "expected_count",
    "active",
]

SET_MEMBER_COLUMNS = ["set_id", "eurio_id", "position"]

# PostgREST paginates at 1000 rows by default. We bump the ceiling via the
# Range-Unit / Prefer=count=exact headers and fetch in chunks just in case.
PAGE_SIZE = 1000


def fetch_table(
    client: httpx.Client, base_url: str, table: str, columns: list[str]
) -> list[dict[str, Any]]:
    """Fetch all rows of a table via PostgREST paginated requests."""
    select = ",".join(columns)
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        headers = {"Range-Unit": "items", "Range": f"{offset}-{offset + PAGE_SIZE - 1}"}
        params = {"select": select}
        resp = client.get(f"{base_url}/{table}", params=params, headers=headers)
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, list):
            raise RuntimeError(f"Unexpected response shape from {table}: {page!r}")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def _extract_numista_id(cross_refs: Any) -> int | None:
    """Best-effort extract of a Numista ID from the coins.cross_refs JSONB.
    The convention is a list of {source, source_native_id, ...} entries ;
    we keep the first entry where source == 'numista' if any.
    """
    if not cross_refs:
        return None
    if isinstance(cross_refs, dict):
        val = cross_refs.get("numista") or cross_refs.get("numista_id")
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
        return None
    if isinstance(cross_refs, list):
        for entry in cross_refs:
            if not isinstance(entry, dict):
                continue
            if entry.get("source") == "numista":
                nid = entry.get("source_native_id") or entry.get("native_id") or entry.get("id")
                if isinstance(nid, int):
                    return nid
                if isinstance(nid, str) and nid.isdigit():
                    return int(nid)
    return None


def _derive_name(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (name_fr, name_en). Real schema has no name column so we
    fall back to `theme` for commemos (no i18n) and leave circulation
    rows nameless (the UI will compose "{face}€ · {country} · {year}")."""
    theme = row.get("theme")
    if theme:
        return theme, theme
    return None, None


def flatten_coin(row: dict[str, Any]) -> dict[str, Any]:
    """Map a Supabase `coins` row to the CoinDto shape expected by Android."""
    images = row.get("images") or {}
    image_obverse = None
    image_reverse = None
    if isinstance(images, dict):
        image_obverse = (
            images.get("obverse")
            or images.get("obverse_url")
            or images.get("front")
        )
        image_reverse = (
            images.get("reverse")
            or images.get("reverse_url")
            or images.get("back")
        )
    name_fr, name_en = _derive_name(row)
    return {
        "eurio_id": row["eurio_id"],
        "numista_id": _extract_numista_id(row.get("cross_refs")),
        "country": row.get("country"),
        "year": row.get("year"),
        "face_value": row.get("face_value"),
        "issue_type": row.get("issue_type"),
        "series_id": row.get("series_id"),
        "name_fr": name_fr,
        "name_en": name_en,
        "image_obverse_url": image_obverse,
        "image_reverse_url": image_reverse,
        "mintage": row.get("mintage"),
        "is_withdrawn": bool(row.get("is_withdrawn")) if row.get("is_withdrawn") is not None else False,
        "withdrawal_reason": row.get("withdrawal_reason"),
        "design_description": row.get("design_description"),
        "theme_code": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print counts, do not write the file")
    parser.add_argument(
        "--only-active-sets",
        action="store_true",
        help="Filter out sets where active=false (default keeps all)",
    )
    args = parser.parse_args()

    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("error: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing in .env", file=sys.stderr)
        return 2

    base_url = url.rstrip("/") + "/rest/v1"
    now = datetime.now(timezone.utc).isoformat()

    with httpx.Client(
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
        timeout=120,
    ) as client:
        print("→ Fetching coins ...")
        coin_rows = fetch_table(client, base_url, "coins", COIN_COLUMNS)
        print(f"  {len(coin_rows)} coins")

        print("→ Fetching coin_series ...")
        series_rows = fetch_table(client, base_url, "coin_series", COIN_SERIES_COLUMNS)
        print(f"  {len(series_rows)} series")

        print("→ Fetching sets ...")
        set_rows = fetch_table(client, base_url, "sets", SET_COLUMNS)
        if args.only_active_sets:
            set_rows = [r for r in set_rows if r.get("active")]
        print(f"  {len(set_rows)} sets")

        print("→ Fetching set_members ...")
        member_rows = fetch_table(client, base_url, "set_members", SET_MEMBER_COLUMNS)
        print(f"  {len(member_rows)} set_members")

    snapshot = {
        "catalog_version": now,
        "generated_at": now,
        "coins": [flatten_coin(r) for r in coin_rows],
        "coin_series": series_rows,
        "sets": set_rows,
        "set_members": member_rows,
    }

    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    size_kb = len(payload.encode("utf-8")) / 1024
    print(f"Snapshot ready : {size_kb:.1f} KB, catalog_version={now}")

    if args.dry_run:
        print("Dry-run — not writing.")
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(payload, encoding="utf-8")
    print(f"Wrote {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
