"""Display-layer i18n helpers shared across ml/ scripts.

These helpers turn DB-flavored coin rows (raw ISO country codes, decimal
face values, English `theme` strings, slug `eurio_id`s) into UI-ready
strings consumed by the Android cohortTest bundle and any future admin
view that wants the same human shape.

The intentionally small surface keeps the i18n burden close to the data
it labels. No phrase translation: when a French coin name is missing
upstream we fall back to whatever English we have, then to a typed
default ("Type courant" for circulation), then to a slug-derived label.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

NBSP = " "
DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"
COUNTRY_FR_PATH = DATASETS_DIR / "country_fr.json"


@lru_cache(maxsize=1)
def _country_fr_table() -> dict[str, str]:
    return json.loads(COUNTRY_FR_PATH.read_text(encoding="utf-8"))


def country_fr(iso: str | None) -> str:
    """Return the French country name for an ISO 3166-1 alpha-2 code.

    Falls back to the uppercase ISO code if unknown so the caller can
    still render something deterministic.
    """
    if not iso:
        return ""
    code = iso.upper()
    return _country_fr_table().get(code, code)


def flag_emoji(iso: str | None) -> str:
    """Return the regional-indicator pair for an ISO 3166-1 alpha-2 code."""
    if not iso or len(iso) != 2:
        return ""
    return "".join(chr(ord(c) + 0x1F1A5) for c in iso.upper())


def format_face_value(value: float | int | None) -> str:
    """Format a euro face value the way French typography wants it.

    >>> format_face_value(2.0)
    '2\\xa0€'
    >>> format_face_value(0.5)
    '50\\xa0c'
    >>> format_face_value(0.1)
    '10\\xa0c'
    """
    if value is None:
        return ""
    if value >= 1:
        whole = int(round(value)) if value == int(value) else value
        return f"{whole}{NBSP}€"
    cents = int(round(value * 100))
    return f"{cents}{NBSP}c"


def _slug_fallback_title(eurio_id: str) -> str:
    """Best-effort human title from the eurio_id slug only.

    `<country>-<year>-<denom>-<slug>` → titlecased "<slug>" with hyphens
    turned into spaces. This is the last-resort branch when neither
    `name_fr` nor `theme`/`name_en` is populated upstream — readable but
    not pretty, and a clear signal that catalog enrichment is missing.
    """
    parts = eurio_id.split("-")
    if len(parts) < 4:
        return eurio_id
    slug = "-".join(parts[3:])
    return slug.replace("-", " ").strip().title()


def display_title(coin: dict[str, Any]) -> str:
    """Pick the best human title we have for a catalog coin row.

    Priority: `name_fr` → `name_en` (≈ `theme` upstream) →
    "Type courant" for circulation issues → slug fallback.
    """
    for key in ("name_fr", "name_en"):
        v = coin.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    if coin.get("issue_type") == "circulation":
        return "Type courant"
    eurio_id = coin.get("eurio_id") or ""
    return _slug_fallback_title(eurio_id)


def coin_display(coin: dict[str, Any]) -> dict[str, Any]:
    """Build the UI-ready display block consumed by the Android client."""
    iso = (coin.get("country") or "").upper() or None
    year = coin.get("year")
    face_value = coin.get("face_value")
    face_value_label = format_face_value(face_value)
    eyebrow_parts = [country_fr(iso) if iso else None]
    if year is not None:
        eyebrow_parts.append(str(year))
    if face_value_label:
        eyebrow_parts.append(face_value_label)
    eyebrow_compact = " · ".join(p for p in eyebrow_parts if p)
    return {
        "title": display_title(coin),
        "country_iso": iso or "",
        "country_fr": country_fr(iso) if iso else "",
        "flag_emoji": flag_emoji(iso),
        "year": year,
        "face_value_label": face_value_label,
        "image_obverse_url": coin.get("image_obverse_url"),
        "eyebrow_compact": eyebrow_compact,
    }
