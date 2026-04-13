"""Bootstrap the Eurio canonical referential — Phase 2C.1a.

Source: Wikipedia "2 euro commemorative coins" page.
Output: ml/datasets/eurio_referential.json (~610 entries: commemoratives + 5 joint issues).

See docs/research/referential-bootstrap-research.md for the source analysis,
and docs/phases/phase-2c-referential.md §2C.1a for the spec.
"""

import json
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from eurio_referential import (
    SOURCES_DIR,
    compute_eurio_id,
    country_to_iso2,
    load_referential,
    make_entry,
    make_identity,
    parse_date,
    parse_volume,
    save_referential,
    slugify,
    write_snapshot,
)

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/2_euro_commemorative_coins"
USER_AGENT = "Eurio/0.1 referential-bootstrap (https://github.com/Musubi42/Eurio)"

YEAR_COINAGE_RX = re.compile(r"^(20\d{2})\s+coinage$")
YEAR_COMMON_RX = re.compile(r"^(20\d{2})\s+commonly issued coin$")


def fetch_wikipedia_commemo() -> str:
    """Fetch the Wikipedia page and persist a dated snapshot."""
    print(f"Fetching {WIKIPEDIA_URL}")
    resp = httpx.get(
        WIKIPEDIA_URL,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    snapshot = write_snapshot("wikipedia_commemo", resp.text)
    print(f"  snapshot saved to {snapshot} ({len(resp.text)} bytes)")
    return resp.text


def find_table_after(heading: Tag) -> Tag | None:
    """Find the first wikitable after a given heading."""
    return heading.find_next("table", class_="wikitable")


def extract_data_rows(table: Tag) -> list[tuple[Tag, ...]]:
    """Extract data rows from a year/common-issue table.

    Each coin spans 2 rows: first with structured columns (Image, Country, Feature,
    Volume, Date), second with a 'Description: ...' single cell. We pair them.
    """
    rows = table.find_all("tr")
    data_rows: list[tuple[Tag, ...]] = []
    i = 0
    # Skip the header row
    if rows and rows[0].find("th"):
        i = 1
    while i < len(rows):
        row = rows[i]
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) >= 4:
            # Look ahead for description row
            desc_row = rows[i + 1] if i + 1 < len(rows) else None
            data_rows.append((row, desc_row))
            i += 2
        else:
            i += 1
    return data_rows


def parse_data_row(row: Tag, description_row: Tag | None) -> dict | None:
    """Parse a single data row into a dict with country/feature/volume/date/description."""
    cells = row.find_all(["td", "th"], recursive=False)
    if len(cells) < 5:
        return None

    # cells: [Image, Country, Feature, Volume, Date]
    country_raw = cells[1].get_text(" ", strip=True)
    # Strip parasitic delimiters from wikitext templates that leak into rendered text
    country_raw = country_raw.lstrip("|").strip()
    feature_raw = cells[2].get_text(" ", strip=True)
    volume_raw = cells[3].get_text(" ", strip=True)
    date_raw = cells[4].get_text(" ", strip=True)

    description = None
    if description_row:
        desc_cells = description_row.find_all(["td"], recursive=False)
        if desc_cells:
            desc_text = desc_cells[0].get_text(" ", strip=True)
            if desc_text.lower().startswith("description:"):
                description = desc_text.split(":", 1)[1].strip()

    return {
        "country_raw": country_raw,
        "feature_raw": feature_raw,
        "volume_raw": volume_raw,
        "volume": parse_volume(volume_raw),
        "date_raw": date_raw,
        "date_iso": parse_date(date_raw),
        "description": description,
    }


def build_year_coinage_entries(table: Tag, year: int) -> list[dict]:
    """Build canonical entries from a {year} coinage table."""
    entries: list[dict] = []
    for row, desc_row in extract_data_rows(table):
        parsed = parse_data_row(row, desc_row)
        if not parsed:
            continue
        country_iso2 = country_to_iso2(parsed["country_raw"])
        if not country_iso2:
            print(f"  WARN: unknown country {parsed['country_raw']!r} in {year} coinage")
            continue

        feature = parsed["feature_raw"] or ""
        # Strip trailing "Nth of the X series" marker — covers all written ordinals
        # found on Wikipedia commemoratives (Bundesländer goes up to ~Sixteenth).
        ordinal_rx = (
            r"(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|"
            r"Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth|Sixteenth|Seventeenth|"
            r"Eighteenth|Nineteenth|Twentieth)"
        )
        theme = re.split(rf"\s+{ordinal_rx}\s+of\s+the\s+", feature, maxsplit=1)[0]
        theme = re.split(r"\s+(?:Series|series)\s+of\s+", theme, maxsplit=1)[0]
        theme = theme.strip(" .,;:")
        design_slug = slugify(theme) or slugify(feature) or "unknown"

        eurio_id = compute_eurio_id(country_iso2, year, 2.0, design_slug)

        collector_only = country_iso2 in ("VA", "MC")  # Vatican/Monaco produce collector-only

        identity = make_identity(
            country_iso2=country_iso2,
            year=year,
            face_value=2.0,
            is_commemorative=True,
            theme=theme,
            design_description=parsed["description"],
            collector_only=collector_only,
        )
        entry = make_entry(
            eurio_id=eurio_id,
            identity=identity,
            cross_refs={"wikipedia_url": WIKIPEDIA_URL},
            observations={
                "wikipedia": {
                    "feature_raw": feature,
                    "volume": parsed["volume"],
                    "volume_raw": parsed["volume_raw"],
                    "issue_date": parsed["date_iso"],
                    "issue_date_raw": parsed["date_raw"],
                }
            },
            sources_used=["wikipedia_commemo"],
        )
        entries.append(entry)
    return entries


def build_common_issue_entry(table: Tag, year: int) -> dict | None:
    """Build a single canonical entry for a common (joint) issue.

    First data row is the canonical "European Union" entry, subsequent rows are the
    national variants (one per participating country).
    """
    rows_pairs = extract_data_rows(table)
    if not rows_pairs:
        return None

    canonical_row, canonical_desc = rows_pairs[0]
    canonical = parse_data_row(canonical_row, canonical_desc)
    if not canonical:
        return None

    # Subsequent rows = national variants
    variants_iso2: list[str] = []
    by_country: dict[str, int | None] = {}
    for row, desc in rows_pairs[1:]:
        parsed = parse_data_row(row, desc)
        if not parsed:
            continue
        iso2 = country_to_iso2(parsed["country_raw"])
        if iso2 and iso2 != "eu":
            variants_iso2.append(iso2)
            by_country[iso2] = parsed["volume"]

    theme = canonical["feature_raw"].strip(" .,;:")
    design_slug = slugify(theme) or "common-issue"
    eurio_id = compute_eurio_id("eu", year, 2.0, design_slug)

    identity = make_identity(
        country_iso2="eu",
        year=year,
        face_value=2.0,
        is_commemorative=True,
        theme=theme,
        design_description=canonical["description"],
        national_variants=sorted(variants_iso2),
    )
    entry = make_entry(
        eurio_id=eurio_id,
        identity=identity,
        cross_refs={"wikipedia_url": WIKIPEDIA_URL},
        observations={
            "wikipedia": {
                "feature_raw": canonical["feature_raw"],
                "total_volume": canonical["volume"],
                "total_volume_raw": canonical["volume_raw"],
                "issue_date": canonical["date_iso"],
                "issue_date_raw": canonical["date_raw"],
                "mintage_by_country": by_country,
            }
        },
        sources_used=["wikipedia_commemo"],
    )
    return entry


def build_referential_from_html(html: str) -> dict[str, dict]:
    """Parse the full Wikipedia page and return a dict of canonical entries."""
    soup = BeautifulSoup(html, "lxml")
    entries: dict[str, dict] = {}
    duplicates: list[str] = []

    for heading in soup.find_all("h3"):
        title = heading.get_text(strip=True)
        m_year = YEAR_COINAGE_RX.match(title)
        m_common = YEAR_COMMON_RX.match(title)
        if not (m_year or m_common):
            continue
        year = int((m_year or m_common).group(1))
        table = find_table_after(heading)
        if not table:
            print(f"  WARN: no table after {title!r}")
            continue

        if m_year:
            year_entries = build_year_coinage_entries(table, year)
            print(f"  {title}: {len(year_entries)} entries")
            for e in year_entries:
                _insert_with_collision_handling(entries, e, duplicates)
        else:
            common_entry = build_common_issue_entry(table, year)
            if common_entry:
                _insert_with_collision_handling(entries, common_entry, duplicates)
                variants = common_entry["identity"]["national_variants"] or []
                print(f"  {title}: 1 canonical entry + {len(variants)} national variants")

    if duplicates:
        print(f"\nWARN: {len(duplicates)} eurio_id collisions resolved with -v2/-v3 suffixes:")
        for d in duplicates[:10]:
            print(f"  - {d}")
    return entries


def _insert_with_collision_handling(
    entries: dict[str, dict],
    new_entry: dict,
    collision_log: list[str],
) -> None:
    """Insert an entry, suffixing the eurio_id if a collision is detected."""
    eid = new_entry["eurio_id"]
    if eid not in entries:
        entries[eid] = new_entry
        return

    # Collision — assign -v2, -v3, ... suffix
    suffix_n = 2
    while f"{eid}-v{suffix_n}" in entries:
        suffix_n += 1
    new_eid = f"{eid}-v{suffix_n}"
    new_entry["eurio_id"] = new_eid
    new_entry["provenance"]["needs_review"] = True
    new_entry["provenance"]["review_reason"] = (
        f"slug collision with {eid}: distinct themes share the same canonical slug, "
        f"human verification required"
    )
    # Also flag the original
    entries[eid]["provenance"]["needs_review"] = True
    entries[eid]["provenance"]["review_reason"] = (
        f"slug collision: {new_eid} also shares this canonical slug"
    )
    entries[new_eid] = new_entry
    collision_log.append(f"{eid} -> {new_eid}")


def report(entries: dict[str, dict]) -> None:
    """Print a summary report of the built referential."""
    print("\n" + "=" * 60)
    print(f"REPORT — {len(entries)} canonical entries")
    print("=" * 60)

    by_country: dict[str, int] = {}
    by_year: dict[int, int] = {}
    common_count = 0
    no_volume = 0
    collector_only_count = 0

    for e in entries.values():
        ident = e["identity"]
        country = ident["country"]
        year = ident["year"]
        by_country[country] = by_country.get(country, 0) + 1
        by_year[year] = by_year.get(year, 0) + 1
        if country == "eu":
            common_count += 1
        if ident.get("collector_only"):
            collector_only_count += 1
        wiki = e["observations"].get("wikipedia", {})
        if not wiki.get("volume") and not wiki.get("total_volume"):
            no_volume += 1

    print(f"\nBy country ({len(by_country)} countries):")
    for c in sorted(by_country.keys()):
        print(f"  {c}: {by_country[c]}")

    print(f"\nBy year ({len(by_year)} years):")
    for y in sorted(by_year.keys()):
        print(f"  {y}: {by_year[y]}")

    print("\nSpecial counts:")
    print(f"  Joint issues (eu-*): {common_count}")
    print(f"  Collector-only flagged (VA/MC): {collector_only_count}")
    print(f"  Entries without parsed volume: {no_volume}")


BOOTSTRAP_SOURCE_TAG = "wikipedia_commemo"


def main() -> None:
    html = fetch_wikipedia_commemo()
    new_entries = build_referential_from_html(html)

    existing = load_referential()
    print(f"\nExisting referential: {len(existing)} entries")
    print(f"New entries from Wikipedia: {len(new_entries)} entries")

    # The bootstrap is authoritative for its own scope. Drop any prior entry whose
    # provenance was solely the bootstrap source — they may have stale eurio_ids from
    # an earlier run with different slug logic. Entries enriched by other scrapers
    # (lmdlp, ebay, mdp) are preserved.
    dropped = 0
    surviving: dict[str, dict] = {}
    for eid, entry in existing.items():
        sources = entry.get("provenance", {}).get("sources_used", [])
        # Keep entries that have been touched by at least one non-bootstrap source
        if any(s != BOOTSTRAP_SOURCE_TAG for s in sources):
            surviving[eid] = entry
        else:
            dropped += 1
    print(f"  dropped {dropped} stale bootstrap-only entries")
    print(f"  preserved {len(surviving)} entries enriched by other sources")

    # Now insert the fresh bootstrap entries
    for eid, entry in new_entries.items():
        if eid in surviving:
            # Preserve provenance.first_seen and any external observations
            entry["provenance"]["first_seen"] = surviving[eid]["provenance"]["first_seen"]
            for k, v in surviving[eid].get("observations", {}).items():
                if k not in entry["observations"]:
                    entry["observations"][k] = v
            for k, v in surviving[eid].get("cross_refs", {}).items():
                if k not in entry["cross_refs"]:
                    entry["cross_refs"][k] = v
        surviving[eid] = entry

    save_referential(surviving)
    print(f"\nSaved {len(surviving)} entries to ml/datasets/eurio_referential.json")

    report(new_entries)


if __name__ == "__main__":
    main()
