"""JO (EUR-Lex) source adapter — découverte + download_raw.

Découverte = énumération CELLAR SPARQL des avis « New national side of euro
coins » publiés par la DG ECFIN au JO série C, puis parsing de chaque notice.

Recette d'énumération (validée spike 2026-05-30, cf. memory
``project_eurlex_source``) :
- ``work_created_by_agent = corporate-body/ECFIN`` (DG affaires monétaires)
- ``official-journal-act_part_of_collection_document = document-collection/OJ-C``
- CELEX au format ``^C/\\d{4}/\\d+$`` → exclut le bruit ECFIN (communications
  accords monétaires, guidance budgétaire, en sector ``5….XC…``).
Les CELEX sont des literals **typés** → on filtre via ``FILTER(STR(?c) …)``.

On ne retient ensuite que les notices de pièce **commémorative 2 €** (header
« commemorative 2-euro coin » + champ « Subject of commemoration »), ce qui
écarte les refontes de faces régulières (notices « sides » plurielles).

L'image (côté national) est embarquée base64 dans la notice — ``download_raw``
la décode depuis le HTML caché par ``discover``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
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
from sources._base.slug_match import RefCoin as _RefCoin
from sources._base.slug_match import SlugGroupMatcher
from sources.jo.parser import extract_coin_image, parse_jo_notice

logger = logging.getLogger(__name__)

SOURCE_ID = "jo"

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
ECFIN_AGENT = (
    "http://publications.europa.eu/resource/authority/corporate-body/ECFIN"
)
OJ_C_COLLECTION = (
    "http://publications.europa.eu/resource/authority/document-collection/OJ-C"
)
NOTICE_HTML_TPL = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:{oj_id}"

USER_AGENT = "Eurio/0.1 jo-eurlex-scraper (https://github.com/Musubi42/Eurio)"
RATE_LIMIT_SEC = 1.0
FIRST_JO_YEAR = 2004

# CELEX d'une notice pièce : sector C, année 4 chiffres, numéro. Exclut le
# bruit ECFIN (52026XC…, 52024XC…).
_COIN_CELEX_RE = re.compile(r"^C/\d{4}/\d+$")

_SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "datasets" / "sources"

# Overrides manuels (country, year, jo_slug) → eurio_id, sur le modèle BCE,
# pour les sujets JO dont le vocabulaire diverge trop du slug Numista. Vide
# au démarrage ; à peupler au fil des divergences constatées.
MANUAL_JO_OVERRIDES: dict[tuple[str, int, str], str] = {}


def _build_country_lookup() -> dict[str, str]:
    """nom (lowercase) → ISO2, dérivé de ``COUNTRY_NAMES`` (ISO2 → noms)."""
    from sources.text_signals.dictionaries import COUNTRY_NAMES

    lookup: dict[str, str] = {}
    for iso2, names in COUNTRY_NAMES.items():
        for n in names:
            lookup[n.lower()] = iso2
    return lookup


@dataclass
class _ParsedNotice:
    celex: str
    notice_url: str
    iso2: str
    year: int
    subject: str
    slug: str
    payload: dict


@dataclass
class JoAdapter:
    source_id: str = SOURCE_ID
    conn: sqlite3.Connection | None = None
    sleep: float = RATE_LIMIT_SEC
    since_year: int = FIRST_JO_YEAR
    score_floor: float = 0.25
    gap_ratio: float = 1.4
    _country_lookup: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self._country_lookup:
            self._country_lookup = _build_country_lookup()

    # ── SourceAdapter contract ───────────────────────────────────────────

    def discover(
        self,
        query: SourceQuery,
        *,
        record_search: RecordSearchFn | None = None,
        record_discarded: RecordDiscardedFn | None = None,
    ) -> Iterable[DiscoveredItem]:
        from referential.eurio_referential import slugify

        ref_index = self._load_referential()
        target_ids: set[str] | None = None
        if query.target_eurio_id:
            target_ids = {query.target_eurio_id}
        elif query.target_eurio_ids:
            target_ids = set(query.target_eurio_ids)

        # 1. Énumération SPARQL des CELEX de notices pièce.
        celex_rows = self._sparql_notices()

        # 2. Fetch + parse chaque notice → ne garde que les commémo 2 €.
        parsed: list[_ParsedNotice] = []
        for row in celex_rows:
            celex = row["celex"]
            title = row.get("title") or ""
            if not _COIN_CELEX_RE.match(celex):
                continue
            if title.lower().startswith("corrigendum"):
                continue

            try:
                html = self._fetch_notice(celex)
            except httpx.HTTPError as exc:
                logger.warning("[jo] fetch %s failed: %s", celex, exc)
                continue
            if html is None:
                continue

            notice = parse_jo_notice(html)
            notice_url = NOTICE_HTML_TPL.format(oj_id=self._oj_id(celex))
            if not notice.is_commemorative_2euro:
                continue

            iso2 = self._country_lookup.get((notice.country_name or "").lower())
            year = notice.issue_year or self._celex_year(celex)
            if not iso2 or not year or not notice.subject:
                if record_discarded is not None:
                    record_discarded(DiscardedListingRecord(
                        source_ref=f"jo/{celex}",
                        reason="unparseable_country_year_subject",
                        title=notice.subject or title,
                        raw_payload={"celex": celex, "country": notice.country_name},
                    ))
                continue
            if query.country and query.country != iso2:
                continue

            parsed.append(_ParsedNotice(
                celex=celex,
                notice_url=notice_url,
                iso2=iso2,
                year=year,
                subject=notice.subject,
                slug=slugify(notice.subject),
                payload={
                    "celex": celex,
                    "country": iso2,
                    "year": year,
                    "subject": notice.subject,
                    "description": notice.description,
                    "issuing_volume": notice.issuing_volume,
                    "date_of_issue": notice.date_of_issue_raw,
                    "notice_url": notice_url,
                },
            ))

        # 3. Assignation 1-to-1 par (country, year) — comme BCE.
        matcher = SlugGroupMatcher(
            overrides=MANUAL_JO_OVERRIDES,
            score_floor=self.score_floor,
            gap_ratio=self.gap_ratio,
        )
        groups: dict[tuple[str, int], list[_ParsedNotice]] = {}
        for n in parsed:
            groups.setdefault((n.iso2, n.year), []).append(n)

        for (iso2, year), notices in groups.items():
            assignments = matcher.match_group(
                ref_index, [(n.iso2, n.year, n.slug) for n in notices]
            )
            for n, eurio_id in zip(notices, assignments):
                if eurio_id is None:
                    if record_discarded is not None:
                        record_discarded(DiscardedListingRecord(
                            source_ref=f"jo/{n.celex}",
                            reason="no_eurio_match",
                            title=n.subject,
                            raw_payload=n.payload,
                        ))
                    continue
                if target_ids is not None and eurio_id not in target_ids:
                    continue
                yield DiscoveredItem(
                    source_ref=f"jo/{eurio_id}",
                    source_url=n.notice_url,
                    target_eurio_id=eurio_id,
                    listing_title=n.subject,
                    listing_country=iso2,
                    listing_year=year,
                    raw_payload=n.payload,
                )

    def download_raw(self, item: DiscoveredItem, dest: Path) -> RawDownloadResult:
        """Décode l'image base64 du côté national depuis la notice (cachée)."""
        celex = (item.raw_payload or {}).get("celex")
        if not celex:
            raise ValueError(f"JO item {item.source_ref} has no celex in payload")
        html = self._fetch_notice(celex)
        if html is None:
            raise ValueError(f"JO notice {celex} unavailable")
        data = extract_coin_image(html)
        if data is None:
            raise ValueError(f"JO notice {celex} has no embedded coin image")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return RawDownloadResult(
            storage_path=dest,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            endpoint_url=item.source_url,
            http_status=200,
        )

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _celex_year(celex: str) -> int | None:
        m = re.match(r"^C/(\d{4})/", celex)
        return int(m.group(1)) if m else None

    @staticmethod
    def _oj_id(celex: str) -> str:
        """``C/2024/03964`` → ``C_202403964`` (uri OJ pour l'URL HTML)."""
        parts = celex.split("/")
        return f"C_{parts[1]}{parts[2]}"

    def _sparql_notices(self) -> list[dict]:
        """Liste ``{celex, title, date}`` des notices ECFIN en OJ-C."""
        sparql = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?title ?date WHERE {{
  ?work cdm:work_created_by_agent <{ECFIN_AGENT}> .
  ?work cdm:official-journal-act_part_of_collection_document <{OJ_C_COLLECTION}> .
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_date_document ?date .
  OPTIONAL {{ ?work cdm:work_title ?title . }}
  FILTER(?date >= "{self.since_year}-01-01"^^xsd:date)
}}
ORDER BY DESC(?date)
LIMIT 2000
"""
        resp = httpx.get(
            SPARQL_ENDPOINT,
            params={"query": sparql, "format": "application/sparql-results+json"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
            timeout=90,
        )
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
        seen: dict[str, dict] = {}
        for b in bindings:
            celex = b["celex"]["value"]
            row = seen.setdefault(celex, {"celex": celex, "title": "", "date": None})
            if b.get("title", {}).get("value"):
                row["title"] = b["title"]["value"]
            if b.get("date", {}).get("value"):
                row["date"] = b["date"]["value"]
        logger.info("[jo] SPARQL → %d distinct CELEX", len(seen))
        return list(seen.values())

    def _fetch_notice(self, celex: str) -> str | None:
        """HTML de la notice, caché à la journée. ``None`` sur 404."""
        safe = celex.replace("/", "_")
        cache = _SNAPSHOTS_DIR / f"jo_{safe}_{date.today().isoformat()}.html"
        if cache.is_file():
            return cache.read_text(encoding="utf-8")
        url = NOTICE_HTML_TPL.format(oj_id=self._oj_id(celex))
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=40,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        time.sleep(self.sleep)
        _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(resp.text, encoding="utf-8")
        return resp.text

    def _load_referential(self) -> dict[tuple[str, int], list[_RefCoin]]:
        if self.conn is None:
            raise RuntimeError("JoAdapter.conn is required (eurio.db connection).")
        idx: dict[tuple[str, int], list[_RefCoin]] = {}
        rows = self.conn.execute(
            "SELECT eurio_id, country, year FROM coins "
            "WHERE face_value = 2.0 AND is_commemorative = 1"
        ).fetchall()
        for r in rows:
            eid = r["eurio_id"]
            parts = eid.split("-", 3)
            slug = parts[3] if len(parts) == 4 else ""
            idx.setdefault((r["country"], r["year"]), []).append(_RefCoin(
                eurio_id=eid, country=r["country"], year=r["year"], theme_slug=slug,
            ))
        return idx
