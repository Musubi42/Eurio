"""Bootstrap German circulation coins from de.wikipedia — Phase 2C.1c.

The English Wikipedia "German euro coins" page only carries face-value mintage
tables for 2002-2016. The German Wikipedia page "Auflagen der deutschen
Euromünzen" has the full 2002-2024 data with per-mint breakdown across the
five German mint marks (A=Berlin, D=Munich, F=Stuttgart, G=Karlsruhe,
J=Hamburg).

Each denomination has its own table (8 tables, one per face value). Rows are
years, columns are mints + Σ total. Values use period as thousand separator
(`800.000.000`). The Σ column is unreliable in the source (typos with leading
zeros / stray dots) so we always sum the per-mint values instead.

This script replaces any prior DE circulation entries tagged with the older
`wikipedia_country` source.
"""

import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from referential.eurio_referential import (
    compute_eurio_id,
    load_referential,
    make_entry,
    make_identity,
    save_referential,
    write_snapshot,
)

WIKIPEDIA_URL = "https://de.wikipedia.org/wiki/Auflagen_der_deutschen_Euromünzen"
USER_AGENT = "Eurio/0.1 referential-bootstrap (https://github.com/Musubi42/Eurio)"

DENOM_HEADINGS: dict[str, float] = {
    "1 Cent": 0.01,
    "2 Cent": 0.02,
    "5 Cent": 0.05,
    "10 Cent": 0.10,
    "20 Cent": 0.20,
    "50 Cent": 0.50,
    "1 Euro": 1.00,
    "2 Euro": 2.00,
}

MINT_COLUMNS = ("A", "D", "F", "G", "J")
DASH_TOKENS = {"–", "—", "-", ""}
YEAR_RX = re.compile(r"^(20\d{2})$")
SOURCE_TAG = "wikipedia_de_auflagen"


def fetch_page() -> str:
    print(f"Fetching {WIKIPEDIA_URL}")
    resp = httpx.get(
        WIKIPEDIA_URL,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    snapshot = write_snapshot("wikipedia_de_auflagen", resp.text)
    print(f"  snapshot saved to {snapshot} ({len(resp.text)} bytes)")
    time.sleep(0.5)
    return resp.text


def parse_de_value(text: str) -> int | None:
    """Parse a German thousands-separator value like '800.000.000'."""
    if text is None:
        return None
    text = text.strip().replace("\u00a0", " ")
    if text in DASH_TOKENS:
        return None
    cleaned = re.sub(r"[\s.]", "", text)
    if not cleaned.isdigit():
        return None
    return int(cleaned)


def parse_denom_table(table: Tag) -> dict[int, dict[str, int]]:
    """Parse one denomination table: returns {year: {mint: volume}}."""
    rows = table.find_all("tr")
    if not rows:
        return {}
    header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"], recursive=False)]
    mint_to_col: dict[str, int] = {}
    for j, h in enumerate(header_cells):
        if h in MINT_COLUMNS:
            mint_to_col[h] = j

    by_year: dict[int, dict[str, int]] = {}
    for row in rows[1:]:
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        label = cells[0].get_text(" ", strip=True)
        m = YEAR_RX.match(label)
        if not m:
            continue
        year = int(m.group(1))
        per_mint: dict[str, int] = {}
        for mint, j in mint_to_col.items():
            if j >= len(cells):
                continue
            val = parse_de_value(cells[j].get_text(" ", strip=True))
            if val is not None and val > 0:
                per_mint[mint] = val
        if per_mint:
            by_year[year] = per_mint
    return by_year


def parse_page(html: str) -> dict[float, dict[int, dict[str, int]]]:
    """Return {face_value: {year: {mint: volume}}}."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[float, dict[int, dict[str, int]]] = {}
    for h in soup.find_all("h3"):
        label = h.get_text(" ", strip=True)
        if label not in DENOM_HEADINGS:
            continue
        face_value = DENOM_HEADINGS[label]
        table = h.find_next("table", class_="wikitable")
        if not table:
            print(f"  WARN: no table after {label!r}")
            continue
        out[face_value] = parse_denom_table(table)
        years = sorted(out[face_value].keys())
        print(f"  {label}: {len(years)} years ({years[0]}-{years[-1]})")
    return out


def build_entries(parsed: dict[float, dict[int, dict[str, int]]]) -> dict[str, dict]:
    """Build canonical DE circulation entries with per-mint observations."""
    entries: dict[str, dict] = {}
    for face_value, by_year in parsed.items():
        for year, per_mint in by_year.items():
            total = sum(per_mint.values())
            eurio_id = compute_eurio_id("DE", year, face_value, "standard")
            identity = make_identity(
                country_iso2="DE",
                year=year,
                face_value=face_value,
                is_commemorative=False,
                theme=None,
                design_description=None,
                collector_only=False,
            )
            entry = make_entry(
                eurio_id=eurio_id,
                identity=identity,
                cross_refs={"wikipedia_url": WIKIPEDIA_URL},
                observations={
                    "wikipedia": {
                        "mintage_total": total,
                        "mintage_aggregated_across_tables": False,
                        "by_mint": per_mint,
                    }
                },
                sources_used=[SOURCE_TAG],
            )
            entries[eurio_id] = entry
    return entries


def main() -> None:
    html = fetch_page()
    parsed = parse_page(html)
    new_entries = build_entries(parsed)
    print(f"\nTotal new DE entries: {len(new_entries)}")

    existing = load_referential()
    print(f"Existing referential: {len(existing)} entries")

    surviving: dict[str, dict] = {}
    dropped = 0
    for eid, entry in existing.items():
        sources = entry.get("provenance", {}).get("sources_used", [])
        is_de = entry.get("identity", {}).get("country") == "DE"
        is_circulation = not entry.get("identity", {}).get("is_commemorative", False)
        # Drop only DE circulation entries previously bootstrapped from this script
        # OR from the older wikipedia_country source (replaced by this richer source).
        if is_de and is_circulation and sources in ([SOURCE_TAG], ["wikipedia_country"]):
            dropped += 1
        else:
            surviving[eid] = entry
    print(f"  dropped {dropped} stale DE circulation entries")

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


if __name__ == "__main__":
    main()
