"""In-process adapter that returns 5 fixture coins.

Backed by `ml/datasets/<numista_id>/obverse.jpg` for the 5 ids below.
The adapter copies the file on `download_raw()` so the orchestrator
sees a real on-disk artifact (size, sha256, image dims).
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sources._base.adapter import DiscoveredItem, RawDownloadResult, SourceQuery

_DATASETS_ROOT = Path(__file__).resolve().parents[2] / "datasets"

# (numista_id, country, year, denom_eur, listing_title) — covers a mix
# of countries and denominations so the resolve step has variety later.
MOCK_FIXTURES: tuple[tuple[int, str, int, float, str], ...] = (
    (64,  "FR", 2002, 2.00, "France 2 euro 2002 — fixture"),
    (80,  "DE", 2002, 1.00, "Germany 1 euro 2002 — fixture"),
    (88,  "ES", 2002, 0.50, "Spain 50 cents 2002 — fixture"),
    (96,  "IT", 2002, 0.20, "Italy 20 cents 2002 — fixture"),
    (104, "BE", 2002, 0.10, "Belgium 10 cents 2002 — fixture"),
)


@dataclass
class MockAdapter:
    source_id: str = "mock"

    def discover(self, query: SourceQuery) -> Iterable[DiscoveredItem]:
        limit = query.limit if query.limit is not None else len(MOCK_FIXTURES)
        for nid, country, year, price, title in MOCK_FIXTURES[:limit]:
            if query.country and query.country != country:
                continue
            if query.year and query.year != year:
                continue
            yield DiscoveredItem(
                source_ref=f"mock-{nid}",
                source_url=f"mock://numista/{nid}/obverse",
                listing_title=title,
                listing_country=country,
                listing_year=year,
                listing_price=price,
                listing_currency="EUR",
                raw_payload={"numista_id": nid, "fixture": True},
            )

    def download_raw(self, item: DiscoveredItem, dest: Path) -> RawDownloadResult:
        nid = item.raw_payload["numista_id"] if item.raw_payload else None
        src = _DATASETS_ROOT / str(nid) / "obverse.jpg"
        if not src.is_file():
            raise FileNotFoundError(f"Mock fixture missing: {src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        data = dest.read_bytes()
        return RawDownloadResult(
            storage_path=dest,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
