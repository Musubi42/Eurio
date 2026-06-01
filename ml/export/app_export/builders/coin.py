"""Builders for the 'coin' and 'shared_reverse' app-facing Supabase tables.

Pure functions: (sqlite3.Connection) -> list[dict].
No network, no side effects.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from export.app_export.io import json_scalar

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SHAPE_TRANSLATION_RE = re.compile(r"\s*\([^)]*[Tt]raduit[^)]*\)", re.IGNORECASE)

_MULE_SHARED_REVERSE: dict[str, str] = {
    "fi-2006-2eur-standard-1st-type-2nd-map-mule": "2eur-map-v2",
    "de-2008-2eur-federal-state-of-hamburg-mule": "2eur-map-v2",
}

_NOW_ISO = datetime.now(tz=timezone.utc).isoformat()


def _load_observations(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Return {eurio_id: {observation_type: payload_json}} for all rows.

    When multiple rows share the same (eurio_id, observation_type) the last
    one by rowid wins (effectively the most recently recorded).
    """
    cur = con.cursor()
    cur.execute(
        "SELECT eurio_id, observation_type, payload_json "
        "FROM coin_observations "
        "ORDER BY id ASC"
    )
    result: dict[str, dict[str, Any]] = {}
    for row in cur.fetchall():
        eid = row["eurio_id"]
        otype = row["observation_type"]
        if eid not in result:
            result[eid] = {}
        result[eid][otype] = row["payload_json"]
    return result


def _decode_shape(payload_json: str | None) -> str | None:
    """Decode a shape observation, stripping translation parentheticals."""
    raw = json_scalar(payload_json)
    if raw is None:
        return None
    return _SHAPE_TRANSLATION_RE.sub("", str(raw)).strip()


def _decode_mintage(payload_json: str | None) -> int | None:
    """Extract integer mintage from a mintage_official observation payload."""
    if payload_json is None:
        return None
    try:
        obj = json.loads(payload_json)
        if isinstance(obj, dict) and "value" in obj:
            v = obj["value"]
            return int(v) if v is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _decode_demonetized(payload_json: str | None) -> bool | None:
    """Extract is_demonetized bool from a demonetization observation payload."""
    if payload_json is None:
        return None
    try:
        obj = json.loads(payload_json)
        if isinstance(obj, dict) and "is_demonetized" in obj:
            val = obj["is_demonetized"]
            return bool(val) if val is not None else None
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _resolve_shared_reverse(eurio_id: str, year: int) -> str:
    """Return shared_reverse_id for a 2€ coin."""
    if eurio_id in _MULE_SHARED_REVERSE:
        return _MULE_SHARED_REVERSE[eurio_id]
    return "2eur-map-v2" if year >= 2007 else "2eur-map-v1"


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_coin(con: sqlite3.Connection) -> list[dict]:
    """Build rows for the app-facing 'coin' table.

    Sources: coins + coin_observations.
    Returns one dict per coin (689 rows expected) with keys matching
    exactly the target Supabase columns.
    """
    observations = _load_observations(con)

    cur = con.cursor()
    cur.execute(
        "SELECT eurio_id, country, country_name, year, face_value, "
        "       is_commemorative, collector_only, theme, design_description, "
        "       design_group_id, variant_kind, canonical_eurio_id, series_id, "
        "       updated_at "
        "FROM coins"
    )
    rows = cur.fetchall()

    result: list[dict] = []
    for row in rows:
        eid = row["eurio_id"]
        obs = observations.get(eid, {})

        # theme: prefer coin_observations, fallback to coins.theme
        theme_raw = obs.get("theme")
        theme = json_scalar(theme_raw) if theme_raw is not None else row["theme"]

        # physical characteristics from coin_observations
        diameter_mm = json_scalar(obs.get("diameter_mm"))
        weight_g = json_scalar(obs.get("weight_g"))
        thickness_mm = json_scalar(obs.get("thickness_mm"))
        composition = json_scalar(obs.get("composition"))
        shape = _decode_shape(obs.get("shape"))
        orientation = json_scalar(obs.get("orientation"))
        edge_description = json_scalar(obs.get("edge_description"))
        edge_lettering = json_scalar(obs.get("edge_lettering"))
        obverse_lettering = json_scalar(obs.get("obverse_lettering"))
        reverse_lettering = json_scalar(obs.get("reverse_lettering"))

        # mintage from mintage_official observation (coins.mintage is always NULL)
        mintage = _decode_mintage(obs.get("mintage_official"))

        # demonetization
        demonetized = _decode_demonetized(obs.get("demonetization"))

        # face_value_cents as int
        face_value_cents = round((row["face_value"] or 0) * 100)

        # shared_reverse_id
        shared_reverse_id = _resolve_shared_reverse(eid, row["year"])

        result.append({
            "eurio_id": eid,
            "country": row["country"],
            "country_name": row["country_name"],
            "year": row["year"],
            "face_value_cents": face_value_cents,
            "is_commemorative": bool(row["is_commemorative"]),
            "collector_only": bool(row["collector_only"]),
            "theme": theme,
            "design_description": row["design_description"],
            "mintage": mintage,
            "diameter_mm": float(diameter_mm) if diameter_mm is not None else None,
            "weight_g": float(weight_g) if weight_g is not None else None,
            "thickness_mm": float(thickness_mm) if thickness_mm is not None else None,
            "composition": composition,
            "shape": shape,
            "orientation": orientation,
            "edge_description": edge_description,
            "edge_lettering": edge_lettering,
            "obverse_lettering": obverse_lettering,
            "reverse_lettering": reverse_lettering,
            "demonetized": demonetized,
            "demonetized_on": None,
            "design_group_id": row["design_group_id"],
            "variant_kind": row["variant_kind"],
            "canonical_eurio_id": row["canonical_eurio_id"],
            "series_id": None,
            "shared_reverse_id": shared_reverse_id,
            "updated_at": row["updated_at"] or _NOW_ISO,
        })

    return result


def build_shared_reverse(con: sqlite3.Connection) -> list[dict]:  # noqa: ARG001
    """Return the static shared_reverse catalogue (2 rows)."""
    return [
        {
            "id": "2eur-map-v1",
            "label": "2 euro — Première carte (≤2006)",
            "asset_name": "reverse_2eur_v1.webp",
            "map_version": 1,
            "applies_to": "face_value=2.0 AND year<2007",
        },
        {
            "id": "2eur-map-v2",
            "label": "2 euro — Deuxième carte (≥2007)",
            "asset_name": "reverse_2eur_v2.webp",
            "map_version": 2,
            "applies_to": "face_value=2.0 AND year>=2007",
        },
    ]
