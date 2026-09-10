"""In-process adapter that returns 5 fixture coins.

`download_raw()` FABRIQUE l'image (PIL : un disque clair sur fond sombre,
texturé par le numista_id pour que les 5 phash diffèrent) et l'écrit dans
`dest`, pour que l'orchestrateur voie un vrai artefact disque (taille,
sha256, dimensions) et que la détection y trouve une pièce. Il ne lit plus
`ml/datasets/<numista_id>/obverse.jpg` : ce dossier est gitignoré, et sept
tests (`test_orchestrator*.py`) ne passaient que là où il traînait
(run CI 34493861491, 2026-09-10).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sources._base.adapter import DiscoveredItem, RawDownloadResult, SourceQuery

#: Côté de l'image fabriquée, en pixels. Assez grand pour que Hough/contour
#: trouvent le disque, assez petit pour rester négligeable dans un tmp_path.
_SIDE = 320

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

    def discover(
        self,
        query: SourceQuery,
        *,
        record_search=None,
        record_discarded=None,
    ) -> Iterable[DiscoveredItem]:
        limit = query.limit if query.limit is not None else len(MOCK_FIXTURES)
        items_emitted = 0
        for nid, country, year, price, title in MOCK_FIXTURES[:limit]:
            if query.country and query.country != country:
                continue
            if query.year and query.year != year:
                continue
            items_emitted += 1
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
        if nid is None:
            raise ValueError(f"Mock item without numista_id: {item.source_ref}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        synthesize_obverse(int(nid)).save(dest, format="JPEG", quality=90)
        data = dest.read_bytes()
        return RawDownloadResult(
            storage_path=dest,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )


def synthesize_obverse(numista_id: int):
    """Une « pièce » déterministe par numista_id : disque clair centré sur fond
    sombre, avec quelques rectangles gris tirés d'un `random` semé par l'id —
    c'est cette texture qui rend les phash distincts d'un id à l'autre."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (_SIDE, _SIDE), (24, 28, 32))
    draw = ImageDraw.Draw(img)
    r = _SIDE * 0.38
    c = _SIDE / 2
    draw.ellipse((c - r, c - r, c + r, c + r), fill=(214, 196, 120))
    rng = random.Random(numista_id)
    for _ in range(12):
        x = c + rng.uniform(-r * 0.6, r * 0.6)
        y = c + rng.uniform(-r * 0.6, r * 0.6)
        w = rng.uniform(4, r * 0.3)
        h = rng.uniform(4, r * 0.3)
        g = rng.randint(60, 170)
        draw.rectangle((x, y, x + w, y + h), fill=(g, g, g))
    return img
