"""Bootstrap the circulation standard coins — Phase 2C.1b.

Source: Wikipedia "{Country}_euro_coins" pages (25 pages, one per country/state).
Output: enrichment of ml/datasets/eurio_referential.json with ~3000 entries.

For each country page, parses the "Circulating mintage quantities" tables
(usually a Face Value pivot) and produces canonical entries of the form:
    {country}-{year}-{face_code}-standard

Special handling:
- Germany: one table per year with rows for each mint (A/D/F/G/J), volumes in millions.
  We aggregate mints per year.
- Vatican / Monaco: collector-only flag preserved.
- 's' / '—' / empty cells: ignored (no entry created).
"""

import json
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from eurio_referential import (
    compute_eurio_id,
    load_referential,
    make_entry,
    make_identity,
    save_referential,
    write_snapshot,
)

USER_AGENT = "Eurio/0.1 referential-bootstrap (https://github.com/Musubi42/Eurio)"
WIKIPEDIA_BASE = "https://en.wikipedia.org/wiki/{adjective}_euro_coins"
COUNTRY_MAPPING = json.loads((Path(__file__).parent / "datasets" / "country_mapping.json").read_text())

def _normalize_denom_header(text: str) -> str:
    """Normalize a denomination header cell to a canonical form like '€0.01'."""
    return text.strip().replace(" ", "").replace(",", ".")


DENOM_HEADER_TO_FACE: dict[str, float] = {
    "€0.01": 0.01,
    "€0.02": 0.02,
    "€0.05": 0.05,
    "€0.10": 0.10,
    "€0.20": 0.20,
    "€0.50": 0.50,
    "€1.00": 1.00,
    "€2.00": 2.00,
}

YEAR_LABEL_RX = re.compile(r"(\d{4})(?:\s+([A-Z]))?")  # "2002" or "2002 A"
NUMERIC_RX = re.compile(r"^[\d.,\u00a0\u202f ]+$")


def fetch_country_page(adjective: str) -> tuple[str, str]:
    """Fetch a country page from Wikipedia and return (url, html). Politeness sleep."""
    url = WIKIPEDIA_BASE.format(adjective=adjective)
    resp = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    time.sleep(0.5)
    return url, resp.text


SPECIMEN_TOKENS = {"s", "—", "-", "n/a", "N/A", "", "— N/a", "N/a", "—N/a"}
GERMAN_DECIMAL_RX = re.compile(r"^\d+,\d{1,3}$")  # e.g. '60,00' or '124,3'
COMPACT_DECIMAL_RX = re.compile(r"^\d+\.\d{1,3}$")  # e.g. '800.0' or '1.234'


COMPACT_MILLIONS_MAX = 10000  # > 10G coins: not a compact-millions value


def parse_volume_cell(text: str) -> int | None:
    """Parse a mintage cell value.

    Wikipedia mixes several numeric formats across country pages:
    - European with thin spaces: '794 066 000'   -> 794066000  (exact units)
    - European with commas:      '794,066,000'   -> 794066000
    - Compact in millions (US):  '800.0'          -> 800_000_000
    - Compact in millions (DE):  '60,00' / '124,3'-> 60_000_000 / 124_300_000
    - Specimen-only / unknown:   's', '—', 'N/a' -> None

    Compact-millions are constrained to values <= COMPACT_MILLIONS_MAX so a
    DE thousands-separator string like '1.234' (= 1234) wouldn't silently be
    interpreted as 1.234 million. Above the threshold we return None and let
    the caller decide.
    """
    if text is None:
        return None
    text = text.strip().replace("\u00a0", " ").replace("\u202f", " ")
    text = re.sub(r"\[[^\]]+\]", "", text).strip()
    if text in SPECIMEN_TOKENS:
        return None
    if not text:
        return None

    if GERMAN_DECIMAL_RX.match(text):
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            return None
        if value > COMPACT_MILLIONS_MAX:
            return None
        return int(value * 1_000_000)

    if COMPACT_DECIMAL_RX.match(text):
        try:
            value = float(text)
        except ValueError:
            return None
        if value > COMPACT_MILLIONS_MAX:
            return None
        return int(value * 1_000_000)

    cleaned = re.sub(r"[\s,]", "", text)
    if cleaned.isdigit():
        return int(cleaned)
    return None


FACE_VALUE_HEADER_RX = re.compile(r"^face\s*value", re.IGNORECASE)


def find_face_value_tables(soup: BeautifulSoup) -> list[Tag]:
    """Find all wikitables whose first header cell starts with 'Face Value' or 'Face value'.

    Tolerant to footnote refs ('Face value[5]'), spacing and capitalization.
    """
    tables = []
    for t in soup.find_all("table", class_="wikitable"):
        first_th = t.find("th")
        if not first_th:
            continue
        label = first_th.get_text(strip=True)
        # Strip trailing footnote refs like [5], [a]
        label = re.sub(r"\[[^\]]+\]$", "", label).strip()
        if FACE_VALUE_HEADER_RX.match(label):
            tables.append(t)
    return tables


def parse_face_value_table(table: Tag) -> dict[tuple[int, float], int]:
    """Parse a Face Value table and return a dict {(year, face_value): volume}.

    Row 0 is the header (Face Value, €0.01, ..., €2.00).
    Rows 1+ each represent a year (or year+mint for Germany).
    """
    rows = table.find_all("tr")
    if not rows:
        return {}

    # Parse header to map column index -> face_value
    header_cells = rows[0].find_all(["th", "td"], recursive=False)
    col_to_face: dict[int, float] = {}
    for j, c in enumerate(header_cells):
        normalized = _normalize_denom_header(c.get_text(strip=True))
        if normalized in DENOM_HEADER_TO_FACE:
            col_to_face[j] = DENOM_HEADER_TO_FACE[normalized]

    if not col_to_face:
        return {}

    aggregated: dict[tuple[int, float], int] = {}
    for row in rows[1:]:
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        label = cells[0].get_text(" ", strip=True)
        m = YEAR_LABEL_RX.search(label)
        if not m:
            continue
        year = int(m.group(1))
        for j, face in col_to_face.items():
            if j >= len(cells):
                continue
            vol = parse_volume_cell(cells[j].get_text(" ", strip=True))
            if vol is None or vol <= 0:
                continue
            key = (year, face)
            aggregated[key] = aggregated.get(key, 0) + vol
    return aggregated


def parse_country_page(
    html: str, iso2: str
) -> tuple[dict[tuple[int, float], int], bool]:
    """Parse all Face Value tables on a country page.

    Returns (mintage_by_year_face, aggregated_across_tables). The aggregated
    flag is True when more than one FV table contributed to the same key,
    which typically means we summed across mints or design eras.
    """
    soup = BeautifulSoup(html, "lxml")
    tables = find_face_value_tables(soup)
    merged: dict[tuple[int, float], int] = {}
    contributing_tables: dict[tuple[int, float], int] = {}
    for t in tables:
        sub = parse_face_value_table(t)
        for key, vol in sub.items():
            merged[key] = merged.get(key, 0) + vol
            contributing_tables[key] = contributing_tables.get(key, 0) + 1
    aggregated = any(n > 1 for n in contributing_tables.values())
    return merged, aggregated


def build_circulation_entries(
    iso2: str,
    mintage: dict[tuple[int, float], int],
    wiki_url: str,
    aggregated: bool,
) -> list[dict]:
    """Build canonical entries for circulation coins of a country."""
    collector_only = iso2 in ("VA", "MC")
    entries: list[dict] = []
    for (year, face_value), volume in sorted(mintage.items()):
        eurio_id = compute_eurio_id(iso2, year, face_value, "standard")
        identity = make_identity(
            country_iso2=iso2,
            year=year,
            face_value=face_value,
            is_commemorative=False,
            theme=None,
            design_description=None,
            collector_only=collector_only,
        )
        entry = make_entry(
            eurio_id=eurio_id,
            identity=identity,
            cross_refs={"wikipedia_url": wiki_url},
            observations={
                "wikipedia": {
                    "mintage_total": volume,
                    "mintage_aggregated_across_tables": aggregated,
                }
            },
            sources_used=["wikipedia_country"],
        )
        entries.append(entry)
    return entries


def bootstrap_all_countries() -> dict[str, dict]:
    """Fetch and parse all 25 country pages, return aggregate entries dict."""
    all_entries: dict[str, dict] = {}
    failed: list[str] = []

    for iso2, info in sorted(COUNTRY_MAPPING.items()):
        adj = info["adjective"]
        print(f"\n[{iso2}] fetching {adj}_euro_coins...")
        try:
            url, html = fetch_country_page(adj)
        except httpx.HTTPError as e:
            print(f"  FAIL: {e}")
            failed.append(iso2)
            continue
        write_snapshot(f"wikipedia_{iso2.lower()}_country", html)
        mintage, aggregated = parse_country_page(html, iso2)
        print(f"  parsed {len(mintage)} (year, denom) cells (aggregated={aggregated})")
        entries = build_circulation_entries(iso2, mintage, url, aggregated)
        for e in entries:
            all_entries[e["eurio_id"]] = e
        print(f"  {len(entries)} circulation entries built for {iso2}")

    if failed:
        print(f"\nFAILED to fetch: {failed}")
    return all_entries


CIRCULATION_SOURCE_TAG = "wikipedia_country"


def main() -> None:
    print(f"Bootstrapping circulation coins from {len(COUNTRY_MAPPING)} country pages\n")
    new_entries = bootstrap_all_countries()
    print(f"\nTotal new circulation entries: {len(new_entries)}")

    existing = load_referential()
    print(f"Existing referential: {len(existing)} entries")

    # Drop any prior circulation-only entries (from earlier runs of this script)
    surviving: dict[str, dict] = {}
    dropped = 0
    for eid, entry in existing.items():
        sources = entry.get("provenance", {}).get("sources_used", [])
        # Drop entries whose ONLY source is wikipedia_country (this script)
        if sources == [CIRCULATION_SOURCE_TAG]:
            dropped += 1
        else:
            surviving[eid] = entry
    print(f"  dropped {dropped} stale circulation-only entries from previous runs")

    # Insert fresh circulation entries
    for eid, entry in new_entries.items():
        if eid in surviving:
            entry["provenance"]["first_seen"] = surviving[eid]["provenance"]["first_seen"]
            # Preserve enrichments added by other scrapers (images, descriptions,
            # sources_used) — a bootstrap re-run must NOT wipe BCE/Wikipedia data.
            if surviving[eid].get("images"):
                entry["images"] = surviving[eid]["images"]
            if surviving[eid]["identity"].get("design_description"):
                entry["identity"]["design_description"] = surviving[eid]["identity"]["design_description"]
            for s in surviving[eid]["provenance"].get("sources_used", []):
                if s not in entry["provenance"]["sources_used"]:
                    entry["provenance"]["sources_used"].append(s)
            for k, v in surviving[eid].get("observations", {}).items():
                if k not in entry["observations"]:
                    entry["observations"][k] = v
            for k, v in surviving[eid].get("cross_refs", {}).items():
                if k not in entry["cross_refs"]:
                    entry["cross_refs"][k] = v
        surviving[eid] = entry

    save_referential(surviving)
    print(f"\nSaved {len(surviving)} entries to ml/datasets/eurio_referential.json")

    # Stats report
    by_country: dict[str, int] = {}
    by_face: dict[float, int] = {}
    by_year: dict[int, int] = {}
    for e in new_entries.values():
        c = e["identity"]["country"]
        f = e["identity"]["face_value"]
        y = e["identity"]["year"]
        by_country[c] = by_country.get(c, 0) + 1
        by_face[f] = by_face.get(f, 0) + 1
        by_year[y] = by_year.get(y, 0) + 1

    print("\n" + "=" * 60)
    print(f"REPORT — {len(new_entries)} circulation entries")
    print("=" * 60)
    print("\nBy country:")
    for c in sorted(by_country.keys()):
        print(f"  {c}: {by_country[c]}")
    print("\nBy face value:")
    for f in sorted(by_face.keys()):
        print(f"  {f}€: {by_face[f]}")
    print(f"\nBy year (range): {min(by_year)} - {max(by_year)} ({len(by_year)} years)")


if __name__ == "__main__":
    main()
