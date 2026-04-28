"""Resolve `class_id → confusion zone` for the on-the-fly augmentation
pipeline.

Each training class (eurio_id or design_group_id) maps to one of the three
zones — green / orange / red — via ``coin_confusion_map.zone``. A class with
multiple member coins inherits the *worst* zone among its members (red >
orange > green): if any member is hard to disambiguate, the whole class
needs the aggressive recipe.

Classes without a confusion-map entry default to ``orange`` — a conservative
middle ground that exercises perspective + relighting + light overlays.
"""

from __future__ import annotations

import os
from typing import Iterable

from eval.class_resolver import Resolver

ZONE_RANK: dict[str, int] = {"green": 0, "orange": 1, "red": 2}
DEFAULT_ZONE = "orange"
VALID_ZONES = ("green", "orange", "red")


def _worse(a: str, b: str) -> str:
    return a if ZONE_RANK.get(a, -1) >= ZONE_RANK.get(b, -1) else b


def _make_supabase_client():
    """Build a SupabaseClient from env. Returns None if env is incomplete."""
    url = os.environ.get("SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        return None
    from api.supabase_client import SupabaseClient

    return SupabaseClient(url, key)


def fetch_eurio_zones() -> dict[str, str]:
    """Fetch all rows from ``coin_confusion_map`` and return ``{eurio_id: zone}``.

    Returns an empty dict if Supabase is unreachable or the table is empty —
    callers should fall back to ``DEFAULT_ZONE`` for unknown ids.
    """
    client = _make_supabase_client()
    if client is None:
        print("[zone_resolver] Supabase env missing — defaulting all classes to orange")
        return {}
    try:
        rows = client.query(
            "coin_confusion_map",
            select="eurio_id,zone",
        )
    except Exception as exc:
        print(f"[zone_resolver] confusion_map fetch failed: {exc} — defaulting to orange")
        return {}
    out: dict[str, str] = {}
    for r in rows:
        zone = r.get("zone")
        eid = r.get("eurio_id")
        if zone in VALID_ZONES and eid:
            out[eid] = zone
    return out


def resolve_class_zones(
    class_ids: Iterable[str],
    resolver: Resolver,
    eurio_zones: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map each class_id to its zone (worst zone among its members).

    `eurio_zones` is optional — if omitted, fetched from Supabase. Pass it in
    when you want to call this multiple times without re-querying.
    """
    if eurio_zones is None:
        eurio_zones = fetch_eurio_zones()

    out: dict[str, str] = {}
    for class_id in class_ids:
        descriptor = resolver.for_class(class_id)
        if descriptor is None:
            out[class_id] = DEFAULT_ZONE
            continue
        members = [eurio_zones.get(eid) for eid in descriptor.eurio_ids]
        members = [z for z in members if z in VALID_ZONES]
        if not members:
            out[class_id] = DEFAULT_ZONE
            continue
        worst = members[0]
        for z in members[1:]:
            worst = _worse(worst, z)
        out[class_id] = worst
    return out
