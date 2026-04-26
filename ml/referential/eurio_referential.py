"""Helpers for the Eurio canonical coin referential.

See docs/research/data-referential-architecture.md for the full schema spec.
"""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from anyascii import anyascii

REFERENTIAL_PATH = Path(__file__).parent.parent / "datasets" / "eurio_referential.json"
SOURCES_DIR = Path(__file__).parent.parent / "datasets" / "sources"

COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    # 21 eurozone members (BG joined 2026-01-01)
    "Austria": "AT",
    "Belgium": "BE",
    "Bulgaria": "BG",
    "Croatia": "HR",
    "Cyprus": "CY",
    "Estonia": "EE",
    "Finland": "FI",
    "France": "FR",
    "Germany": "DE",
    "Greece": "GR",
    "Ireland": "IE",
    "Italy": "IT",
    "Latvia": "LV",
    "Lithuania": "LT",
    "Luxembourg": "LU",
    "Malta": "MT",
    "Netherlands": "NL",
    "Portugal": "PT",
    "Slovakia": "SK",
    "Slovenia": "SI",
    "Spain": "ES",
    # 4 third-state monetary agreements
    "Andorra": "AD",
    "Monaco": "MC",
    "San Marino": "SM",
    "Vatican City": "VA",
    "Vatican": "VA",
    # Special pseudo-country for joint issues
    "European Union": "eu",
}

ISO2_TO_NAME: dict[str, str] = {v: k for k, v in COUNTRY_NAME_TO_ISO2.items() if v != "eu"}
ISO2_TO_NAME["eu"] = "European Union"

# French country names — used by lamonnaiedelapiece, Monnaie de Paris, eBay FR marketplace, etc.
ISO2_TO_NAME_FR: dict[str, str] = {
    "AD": "Andorre",
    "AT": "Autriche",
    "BE": "Belgique",
    "BG": "Bulgarie",
    "CY": "Chypre",
    "DE": "Allemagne",
    "EE": "Estonie",
    "ES": "Espagne",
    "FI": "Finlande",
    "FR": "France",
    "GR": "Grèce",
    "HR": "Croatie",
    "IE": "Irlande",
    "IT": "Italie",
    "LT": "Lituanie",
    "LU": "Luxembourg",
    "LV": "Lettonie",
    "MC": "Monaco",
    "MT": "Malte",
    "NL": "Pays-Bas",
    "PT": "Portugal",
    "SI": "Slovénie",
    "SK": "Slovaquie",
    "SM": "Saint-Marin",
    "VA": "Vatican",
    "eu": "zone euro",
}

COUNTRY_NAME_FR_TO_ISO2: dict[str, str] = {
    "Allemagne": "DE",
    "Andorre": "AD",
    "Autriche": "AT",
    "Belgique": "BE",
    "Bulgarie": "BG",
    "Chypre": "CY",
    "Croatie": "HR",
    "Espagne": "ES",
    "Estonie": "EE",
    "Finlande": "FI",
    "France": "FR",
    "Grèce": "GR",
    "Irlande": "IE",
    "Italie": "IT",
    "Lettonie": "LV",
    "Lituanie": "LT",
    "Luxembourg": "LU",
    "Malte": "MT",
    "Monaco": "MC",
    "Pays-Bas": "NL",
    "Portugal": "PT",
    "Saint Marin": "SM",
    "Saint-Marin": "SM",
    "Slovaquie": "SK",
    "Slovénie": "SI",
    "Vatican": "VA",
}


def slugify(text: str, max_len: int = 60) -> str:
    """Produce a kebab-case slug suitable for an eurio_id design component.

    Uses anyascii to transliterate non-Latin scripts (Greek, Cyrillic,
    Maltese H/G with dot, etc.) before normalisation. Truncates on word
    boundary to avoid mid-word cuts.
    """
    if not text:
        return ""
    text = text.replace("\u2013", " ").replace("\u2014", " ")
    text = anyascii(text)
    text = text.lower()
    text = re.sub(r"['\u2019]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_len:
        cut = text[:max_len]
        if "-" in cut:
            cut = cut.rsplit("-", 1)[0]
        text = cut.rstrip("-")
    return text


def compute_eurio_id(
    country_iso2: str,
    year: int,
    face_value: float,
    design_slug: str,
) -> str:
    """Compute the canonical Eurio ID for a coin.

    Format: {country}-{year}-{face_code}-{design_slug}

    Examples:
        compute_eurio_id("HR", 2025, 2.0, "amphitheatre-pula")
            -> "hr-2025-2eur-amphitheatre-pula"
        compute_eurio_id("FR", 2020, 0.5, "standard")
            -> "fr-2020-50c-standard"
    """
    face_code = format_face_value(face_value)
    return f"{country_iso2.lower()}-{year}-{face_code}-{design_slug}"


def format_face_value(face_value: float) -> str:
    """Map a numeric face value to its compact string code."""
    cents_map = {0.01: "1c", 0.02: "2c", 0.05: "5c", 0.10: "10c", 0.20: "20c", 0.50: "50c"}
    if face_value in cents_map:
        return cents_map[face_value]
    if face_value == 1.0:
        return "1eur"
    if face_value == 2.0:
        return "2eur"
    raise ValueError(f"Unsupported face value: {face_value}")


VOLUME_RX = re.compile(r"([\d][\d,. \u00a0\u202f]*)")


def parse_volume(text: str) -> int | None:
    """Parse a volume string like '510,000 coins' or '36 771 000 coins' into an int."""
    if not text:
        return None
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    m = VOLUME_RX.search(text)
    if not m:
        return None
    raw = m.group(1)
    cleaned = re.sub(r"[,. ]", "", raw)
    if not cleaned.isdigit():
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


DATE_FORMATS = (
    "%d %B %Y",
    "%B %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
)


def parse_date(text: str) -> str | None:
    """Parse a date string into ISO YYYY-MM-DD if possible, else return raw text."""
    if not text:
        return None
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def country_to_iso2(name: str) -> str | None:
    """Map a country name (Wikipedia format) to ISO 3166-1 alpha-2."""
    if not name:
        return None
    name = name.strip()
    if name in COUNTRY_NAME_TO_ISO2:
        return COUNTRY_NAME_TO_ISO2[name]
    # Try fuzzy fallbacks
    name_clean = re.sub(r"\s+", " ", name).strip()
    if name_clean in COUNTRY_NAME_TO_ISO2:
        return COUNTRY_NAME_TO_ISO2[name_clean]
    return None


def make_identity(
    country_iso2: str,
    year: int,
    face_value: float,
    is_commemorative: bool,
    theme: str | None = None,
    design_description: str | None = None,
    national_variants: list[str] | None = None,
    collector_only: bool = False,
) -> dict[str, Any]:
    """Build the immutable identity sub-document of a coin entry.

    JOUE references live in cross_refs.joue_code, not in identity.
    """
    return {
        "country": country_iso2,
        "country_name": ISO2_TO_NAME.get(country_iso2, country_iso2),
        "year": year,
        "face_value": face_value,
        "currency": "EUR",
        "is_commemorative": is_commemorative,
        "theme": theme,
        "design_description": design_description,
        "national_variants": national_variants,
        "collector_only": collector_only,
    }


def make_entry(
    eurio_id: str,
    identity: dict[str, Any],
    cross_refs: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
    images: list[dict[str, Any]] | None = None,
    sources_used: list[str] | None = None,
) -> dict[str, Any]:
    """Build a fresh referential entry with proper provenance."""
    today = date.today().isoformat()
    return {
        "eurio_id": eurio_id,
        "identity": identity,
        "cross_refs": cross_refs or {},
        "observations": observations or {},
        "images": images or [],
        "provenance": {
            "first_seen": today,
            "last_updated": today,
            "sources_used": sources_used or [],
            "needs_review": False,
            "review_reason": None,
        },
    }


def load_referential(path: Path = REFERENTIAL_PATH) -> dict[str, dict[str, Any]]:
    """Load the existing referential as a dict keyed by eurio_id, or return empty."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if isinstance(raw, list):
        return {e["eurio_id"]: e for e in raw}
    if isinstance(raw, dict) and "entries" in raw:
        return {e["eurio_id"]: e for e in raw["entries"]}
    return raw


def save_referential(data: dict[str, dict[str, Any]], path: Path = REFERENTIAL_PATH) -> None:
    """Persist the referential as a sorted JSON array."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(data.values(), key=lambda e: e["eurio_id"])
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(entries),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def write_snapshot(name: str, content: str | bytes) -> Path:
    """Write a raw immutable source snapshot, dated."""
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    suffix = ".html" if isinstance(content, str) else ".bin"
    path = SOURCES_DIR / f"{name}_{today}{suffix}"
    if isinstance(content, str):
        path.write_text(content)
    else:
        path.write_bytes(content)
    return path
