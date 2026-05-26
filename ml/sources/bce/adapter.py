"""BCE source adapter — sub-chunk 1 (discover + download_raw).

One discovery_search = one ``comm_{year}.en.html`` page. Each ``<h3>``
declares one country; joint issues list N country headers sharing the
same image. Entries are matched against (country, year) candidates from
``eurio.db`` (commémo 2 €) — single candidate auto-matches, multiple
candidates go through a fuzzy slug score with a gap-ratio guard.

The HTML snapshots are kept under
``ml/datasets/sources/bce_comm_{year}_{YYYY-MM-DD}.html`` so a same-day
re-run does zero HTTP work and so we can audit/re-parse offline.

Cropping (1 disque vs 2 disques côte à côte) arrive en sub-chunk 2 ;
``download_raw`` ne fait pour l'instant que persister le JPG brut.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import httpx

from sources._base.adapter import (
    DiscardedListingRecord,
    DiscoveredItem,
    RawDownloadResult,
    RecordDiscardedFn,
    RecordSearchFn,
    SourceQuery,
)
from sources._base.dedup import DiscoverySearchRecord

logger = logging.getLogger(__name__)

SOURCE_ID = "bce"
BCE_BASE = "https://www.ecb.europa.eu/euro/coins/comm/html/"
BCE_YEAR_URL_TPL = BCE_BASE + "comm_{year}.en.html"
USER_AGENT = "Eurio/0.1 bce-images-scraper (https://github.com/Musubi42/Eurio)"

# BCE lag : la page d'une année est publiée ~12 mois après. Default range
# = 2004 → current_year-1.
FIRST_BCE_YEAR = 2004
RATE_LIMIT_SEC = 1.0

_SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "datasets" / "sources"


@dataclass(frozen=True)
class _RefCoin:
    eurio_id: str
    country: str
    year: int
    theme_slug: str


def _slug_score(a: str, b: str) -> float:
    """Score symétrique en couverture de tokens + ratio caractère.

    BCE titres sont verbeux ("550th-anniversary-of-the-death-of-donatello")
    alors que les slugs cohorte sont compacts ("donatello"). On prend
    la couverture max sur les deux directions pour ne pas pénaliser
    la dissymétrie inhérente.
    """
    if not a or not b:
        return 0.0
    src_tokens = {t for t in a.split("-") if t}
    cand_tokens = {t for t in b.split("-") if t}
    inter = src_tokens & cand_tokens
    cov_a = (len(inter) / len(src_tokens)) if src_tokens else 0.0
    cov_b = (len(inter) / len(cand_tokens)) if cand_tokens else 0.0
    coverage = max(cov_a, cov_b)
    ratio = SequenceMatcher(None, a, b).ratio()
    return max(coverage, ratio * 0.7)


@dataclass
class BceAdapter:
    source_id: str = SOURCE_ID
    conn: sqlite3.Connection | None = None
    sleep: float = RATE_LIMIT_SEC
    dry_run: bool = False
    # Score/gap pour le fuzzy slug match — alignés avec eval.matching.match.
    score_floor: float = 0.25
    gap_ratio: float = 1.4

    # ── SourceAdapter contract ───────────────────────────────────────────

    def discover(
        self,
        query: SourceQuery,
        *,
        record_search: RecordSearchFn | None = None,
        record_discarded: RecordDiscardedFn | None = None,
    ) -> Iterable[DiscoveredItem]:
        # Import lazy : bs4/lxml ne sont pas chargés tant que personne
        # n'instancie le pipeline BCE.
        from referential.scrape_bce_images import parse_bce_page

        years = self._years_for_query(query)
        ref_index = self._load_referential()

        target_ids: set[str] | None = None
        if query.target_eurio_id:
            target_ids = {query.target_eurio_id}
        elif query.target_eurio_ids:
            target_ids = set(query.target_eurio_ids)

        for year in years:
            url = BCE_YEAR_URL_TPL.format(year=year)
            t0 = time.monotonic()
            try:
                html, http_status, from_cache = self._fetch_year(year)
            except httpx.HTTPError as exc:
                if record_search is not None:
                    record_search(DiscoverySearchRecord(
                        run_id="", source=self.source_id,
                        endpoint=url, query_q=str(year),
                        status="failed", http_status=None, error=str(exc),
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    ))
                logger.warning("[bce] %s failed: %s", url, exc)
                continue

            if html is None:
                # 404 — année pas encore publiée.
                if record_search is not None:
                    record_search(DiscoverySearchRecord(
                        run_id="", source=self.source_id,
                        endpoint=url, query_q=str(year),
                        status="empty", http_status=http_status,
                        n_summaries=0, n_after_groups=0,
                        n_raw_results=0, n_kept_results=0,
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    ))
                continue

            entries = parse_bce_page(html, year)
            n_summaries = len(entries)
            kept: list[DiscoveredItem] = []

            for e in entries:
                country = e["country"]
                if query.country and query.country != country:
                    continue
                theme_slug = e["theme_slug"]
                eurio_id = self._match_entry(ref_index, country, year, theme_slug)
                if eurio_id is None:
                    if record_discarded is not None:
                        record_discarded(DiscardedListingRecord(
                            source_ref=f"bce/{year}/{country}/{theme_slug}",
                            reason="no_eurio_match",
                            title=e["feature"],
                            raw_payload={
                                "image_url": e["image_url"],
                                "feature": e["feature"],
                                "country": country, "year": year,
                            },
                        ))
                    continue
                if target_ids is not None and eurio_id not in target_ids:
                    continue
                kept.append(DiscoveredItem(
                    source_ref=f"bce/{year}/{eurio_id}",
                    source_url=e["image_url"],
                    target_eurio_id=eurio_id,
                    listing_title=e["feature"],
                    listing_country=country,
                    listing_year=year,
                    raw_payload={
                        "year": year,
                        "country": country,
                        "feature": e["feature"],
                        "description": e.get("description"),
                        "issuing_volume": e.get("issuing_volume"),
                        "issuing_date": e.get("issuing_date"),
                        "image_url": e["image_url"],
                        "bce_page_url": url,
                        "theme_slug": theme_slug,
                    },
                ))

            if record_search is not None:
                record_search(DiscoverySearchRecord(
                    run_id="", source=self.source_id,
                    endpoint=url, query_q=str(year),
                    query_filters={
                        "year": year,
                        "from_cache": from_cache,
                        "country": query.country,
                        "target_eurio_ids": (
                            sorted(target_ids) if target_ids else None
                        ),
                    },
                    status="success" if kept else "empty",
                    http_status=http_status,
                    n_summaries=n_summaries,
                    n_after_groups=n_summaries,
                    n_raw_results=n_summaries,
                    n_kept_results=len(kept),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                ))

            for item in kept:
                yield item

    def download_raw(self, item: DiscoveredItem, dest: Path) -> RawDownloadResult:
        url = item.source_url
        if not url:
            raise ValueError(f"BCE item {item.source_ref} has no source_url")
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.content
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return RawDownloadResult(
            storage_path=dest,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            endpoint_url=url,
            http_status=resp.status_code,
        )

    # ── internals ────────────────────────────────────────────────────────

    def _years_for_query(self, query: SourceQuery) -> list[int]:
        if query.year is not None:
            return [query.year]
        return list(range(FIRST_BCE_YEAR, date.today().year))

    def _fetch_year(self, year: int) -> tuple[str | None, int | None, bool]:
        """``(html, http_status, from_cache)``. ``html=None`` on 404.

        Idempotence inter-jour : si un snapshot daté d'aujourd'hui existe
        déjà, on le réutilise sans appel réseau (utile quand le pipeline
        développe ``target_eurio_ids`` en N sub-queries qui fetcheraient
        sinon la même URL N fois).
        """
        cache = _SNAPSHOTS_DIR / f"bce_comm_{year}_{date.today().isoformat()}.html"
        if cache.is_file():
            return cache.read_text(encoding="utf-8"), 200, True

        resp = httpx.get(
            BCE_YEAR_URL_TPL.format(year=year),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=30,
        )
        if resp.status_code == 404:
            return None, 404, False
        resp.raise_for_status()
        time.sleep(self.sleep)
        _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(resp.text, encoding="utf-8")
        return resp.text, resp.status_code, False

    def _load_referential(self) -> dict[tuple[str, int], list[_RefCoin]]:
        if self.conn is None:
            raise RuntimeError(
                "BceAdapter.conn is required (eurio.db sqlite3 connection)."
            )
        idx: dict[tuple[str, int], list[_RefCoin]] = {}
        rows = self.conn.execute(
            "SELECT eurio_id, country, year FROM coins "
            "WHERE face_value = 2.0 AND is_commemorative = 1"
        ).fetchall()
        for r in rows:
            eid = r["eurio_id"]
            # eurio_id = "{country}-{year}-{denom}-{slug}"
            parts = eid.split("-", 3)
            slug = parts[3] if len(parts) == 4 else ""
            idx.setdefault((r["country"], r["year"]), []).append(_RefCoin(
                eurio_id=eid,
                country=r["country"],
                year=r["year"],
                theme_slug=slug,
            ))
        return idx

    def _match_entry(
        self,
        ref_index: dict[tuple[str, int], list[_RefCoin]],
        country: str,
        year: int,
        theme_slug: str,
    ) -> str | None:
        cands = ref_index.get((country, year), [])
        if not cands:
            return None
        scored = sorted(
            ((_slug_score(theme_slug, c.theme_slug), c) for c in cands),
            key=lambda x: x[0],
            reverse=True,
        )
        best_score, best = scored[0]
        runner_score = scored[1][0] if len(scored) > 1 else 0.0
        has_gap = runner_score == 0 or best_score >= runner_score * self.gap_ratio
        if best_score >= self.score_floor and has_gap:
            return best.eurio_id
        return None
