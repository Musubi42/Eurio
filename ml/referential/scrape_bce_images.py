"""Enrich the referential with official BCE coin images — Phase 2C.5b.1.

Wikipedia's commemorative page only carries country flags, not coin images.
The BCE per-year pages `comm_{year}.en.html` are the canonical official
source: each coin has a high-quality JPG with a descriptive filename,
plus an authoritative English Feature / Description / Issuing volume block.

This script walks every published year (2004 → current_year - 1, since the
BCE lags Wikipedia by a few months on new years), parses each page, and
matches the BCE entries against the canonical referential via the shared
multi-stage matcher. Images are appended to `entry["identity"]["images"]`
in the additive 4-layer schema, deduped by absolute URL.

This is the *primary* coin image source. There is no Wikipedia fallback
because Wikipedia genuinely has no coin images on the commemorative page.

Outputs:
- `ml/datasets/sources/bce_comm_{year}_{date}.html` — immutable snapshots
- `ml/datasets/eurio_referential.json` — enriched with images
- `ml/datasets/matching_log.jsonl` — append-only decisions
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from referential.eurio_referential import (
    SOURCES_DIR,
    country_to_iso2,
    load_referential,
    save_referential,
    slugify,
)
from training.eval.matching import index_referential, match as match_identity
from state.sources_runs import record_run

BCE_BASE = "https://www.ecb.europa.eu/euro/coins/comm/html/"
BCE_YEAR_URL = BCE_BASE + "comm_{year}.en.html"
USER_AGENT = "Eurio/0.1 bce-images-scraper (https://github.com/Musubi42/Eurio)"
SOURCE_TAG = "bce_comm"

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
MATCHING_LOG_PATH = DATASETS_DIR / "matching_log.jsonl"

# Country names used by the BCE pages — mostly English, with a couple of
# variants we need to map to ISO2.
BCE_COUNTRY_OVERRIDES: dict[str, str] = {
    "Vatican City State": "VA",
    "Vatican": "VA",
    "Slovak Republic": "SK",
    "Cyprus": "CY",
}


# ---------- BCE fetch ----------


def fetch_year(year: int, sleep: float = 0.4) -> str | None:
    """Fetch a BCE comm_{year}.en.html. Returns None on 404 (year not yet published)."""
    url = BCE_YEAR_URL.format(year=year)
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=30,
        )
    except httpx.HTTPError as exc:
        print(f"  [{year}] FAIL: {exc}")
        return None
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    time.sleep(sleep)
    return resp.text


def write_snapshot(year: int, html: str) -> Path:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"bce_comm_{year}_{date.today().isoformat()}.html"
    path.write_text(html)
    return path


# ---------- BCE parser ----------

# Les 24 langues officielles de l'UE — la BCE publie comm_{year}.{lang}.html
# dans chacune. EN reste la langue d'ancrage (matching eurio_id via theme_slug).
BCE_EU_LANGS: tuple[str, ...] = (
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "ga", "hr",
    "hu", "it", "lt", "lv", "mt", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
)

# Les 4 champs BCE, toujours dans cet ordre sur la page (validé sur 24 langues).
_BCE_FIELDS: tuple[str, ...] = ("feature", "description", "issuing_volume", "issuing_date")

# Caractères de séparation label/valeur à retirer en tête de valeur, une fois
# le label <strong> enlevé : ':' (EN/FR/…), '.' (lv « Apraksts. »), nbsp, espaces.
_LABEL_SEP_CHARS = " :. \t"


def bce_lang_url(year: int, lang: str) -> str:
    return BCE_BASE + f"comm_{year}.{lang}.html"


def _strip_leading_strong(p: Any) -> str:
    """Texte d'un <p> privé de son label <strong> en tête.

    Chaque champ BCE est ``<p><strong>Label:</strong> valeur</p>``. Le label
    est dans un ``<strong>`` (language-agnostic — fonctionne quel que soit le
    séparateur : ':' EN, '.' letton, ou aucun en maltais « Volum tal-ħruġ »).
    On retire le texte du strong en tête puis les séparateurs résiduels.
    """
    full = p.get_text(" ", strip=True)
    strong = p.find("strong")
    if strong is not None:
        label = strong.get_text(" ", strip=True)
        if full.startswith(label):
            full = full[len(label):]
    # Séparateurs résiduels (':' hors strong, espaces, nbsp) en TÊTE seulement —
    # ne pas rogner la ponctuation de fin (point final d'une phrase = légitime).
    return full.lstrip(_LABEL_SEP_CHARS).strip()


def _p_starts_with_strong(p: Any) -> bool:
    """True si le <p> commence par un <strong> (= nouveau champ labellisé).

    Un <p> de continuation (description sur plusieurs paragraphes) n'a pas de
    <strong> en tête et doit être rattaché au champ précédent.
    """
    for child in p.children:
        name = getattr(child, "name", None)
        if name is None:  # NavigableString
            if str(child).strip():
                return False  # texte avant le strong → pas un label
            continue
        return name == "strong"
    return False


# Labels EN du bloc BCE → nom de champ. Sert UNIQUEMENT sur la page EN
# d'ancrage : on identifie chaque champ par son label anglais (fiable), ce
# qui résiste aux anomalies de structure (ex. 2e coin LU 2023 sans `Feature`).
# Les 23 autres langues réutilisent ce mapping par POSITION (cf. harvester).
_EN_FIELD_LABELS: dict[str, str] = {
    "feature": "feature",
    "description": "description",
    "issuing volume": "issuing_volume",
    "issuing date": "issuing_date",
}


def _classify_en_label(label: str) -> str | None:
    norm = label.strip().strip(_LABEL_SEP_CHARS).strip().lower()
    for prefix, field in _EN_FIELD_LABELS.items():
        if norm.startswith(prefix):
            return field
    return None


def _block_image_url(h3: Any) -> str | None:
    prev_img = h3.find_previous("img")
    if not prev_img:
        return None
    src = prev_img.get("src") or ""
    if not src or not src.lower().endswith((".jpg", ".jpeg", ".png")):
        return None
    if src.startswith("/"):
        return "https://www.ecb.europa.eu" + src
    if src.startswith("http"):
        return src
    return BCE_BASE + src


def _iter_blocks(soup: BeautifulSoup):
    """Yield ``(block_index, h3, image_url)`` pour chaque bloc-pièce, en ordre
    document.

    Le filtre (h3 non vide + image-pièce qui précède) est **language-invariant**
    → le ``block_index`` désigne le même coin dans les 24 langues, ce qui permet
    d'aligner les valeurs non-EN sur le mapping de champs détecté en EN.
    """
    idx = 0
    for h3 in soup.find_all("h3"):
        if not h3.get_text(" ", strip=True):
            continue
        image_url = _block_image_url(h3)
        if image_url is None:
            continue
        yield idx, h3, image_url
        idx += 1


def _block_fields(h3: Any) -> list[tuple[str, str]]:
    """Champs d'un bloc en ``[(label, value), …]`` dans l'ordre du document.

    Chaque champ démarre par un <p> à <strong> en tête (``label`` = texte du
    strong) ; les <p> sans <strong> prolongent la valeur courante (descriptions
    multi-paragraphes, ex. France 2017 ruban rose).
    """
    groups: list[list[str]] = []
    for sib in h3.find_all_next():
        if sib.name == "h3":
            break
        if sib.name != "p":
            continue
        txt = sib.get_text(" ", strip=True)
        if not txt:
            continue
        if _p_starts_with_strong(sib):
            strong = sib.find("strong")
            label = strong.get_text(" ", strip=True) if strong else ""
            groups.append([label, _strip_leading_strong(sib)])
        elif groups:
            groups[-1].append(txt)
    return [(g[0], " ".join(g[1:]).strip()) for g in groups]


def parse_bce_page(html: str, year: int) -> list[dict]:
    """Coins de la page BCE **EN** : champs identifiés par label anglais.

    Chaque coin porte en plus ``_block_index`` (position document, stable
    inter-langues) et ``_field_order`` (ordre des champs détectés) pour que le
    harvester i18n puisse mapper les valeurs des 23 autres langues par position.
    """
    soup = BeautifulSoup(html, "lxml")
    coins: list[dict] = []
    for idx, h3, image_url in _iter_blocks(soup):
        country_raw = h3.get_text(" ", strip=True)
        iso2 = BCE_COUNTRY_OVERRIDES.get(country_raw) or country_to_iso2(country_raw)
        if not iso2:
            continue
        fields: dict[str, str] = {}
        field_order: list[str] = []
        for label, value in _block_fields(h3):
            f = _classify_en_label(label)
            if f and f not in fields:
                fields[f] = value
                field_order.append(f)
        feature = fields.get("feature") or ""
        if not feature:
            continue
        coins.append(
            {
                "country": iso2,
                "country_raw": country_raw,
                "year": year,
                "feature": feature,
                "description": fields.get("description"),
                "issuing_volume": fields.get("issuing_volume"),
                "issuing_date": fields.get("issuing_date"),
                "image_url": image_url,
                "theme_slug": slugify(feature),
                "_block_index": idx,
                "_field_order": field_order,
            }
        )
    return coins


def parse_bce_lang_blocks(html: str) -> dict[int, list[str]]:
    """``{block_index: [valeurs positionnelles]}`` pour une page non-EN.

    On n'identifie pas les champs (labels localisés) : on récupère juste les
    valeurs dans l'ordre. Le harvester les mappe via le ``_field_order`` détecté
    sur la page EN au même ``block_index``.
    """
    soup = BeautifulSoup(html, "lxml")
    out: dict[int, list[str]] = {}
    for idx, h3, _image_url in _iter_blocks(soup):
        out[idx] = [value for _label, value in _block_fields(h3)]
    return out


# ---------- enrichment ----------


def enrich_entry_with_image(
    entry: dict,
    coin: dict,
) -> bool:
    """Store BCE image URL + metadata in observations["bce_comm"].

    Returns True if the entry was updated (False if already present and unchanged).
    """
    obs = entry.setdefault("observations", {})
    existing = obs.get("bce_comm", {})
    if existing.get("image_url") == coin["image_url"]:
        return False
    obs["bce_comm"] = {
        "image_url": coin["image_url"],
        "feature": coin.get("feature"),
        "description": coin.get("description"),
        "issuing_volume": coin.get("issuing_volume"),
        "issuing_date": coin.get("issuing_date"),
        "fetched_at": date.today().isoformat(),
    }
    cross_refs = entry.setdefault("cross_refs", {})
    cross_refs["bce_comm_url"] = BCE_YEAR_URL.format(year=coin["year"])
    if coin.get("description") and not entry["identity"].get("design_description"):
        entry["identity"]["design_description"] = coin["description"]
    sources = entry["provenance"].setdefault("sources_used", [])
    if SOURCE_TAG not in sources:
        sources.append(SOURCE_TAG)
    entry["provenance"]["last_updated"] = date.today().isoformat()
    return True


def append_matching_log(records: list[dict]) -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    sampled_at = datetime.now(timezone.utc).isoformat()
    with MATCHING_LOG_PATH.open("a") as f:
        for r in records:
            f.write(
                json.dumps(
                    {"source": SOURCE_TAG, "sampled_at": sampled_at, **r},
                    ensure_ascii=False,
                )
                + "\n"
            )


# ---------- main ----------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Scrape only the given year (default: 2004 → current year)",
    )
    args = parser.parse_args()

    referential = load_referential()
    print(f"Loaded referential: {len(referential)} entries")
    idx = index_referential(referential)

    current_year = date.today().year
    if args.year is not None:
        years = [args.year]
        print(f"Fetching BCE comm page for {args.year}\n")
    else:
        years = list(range(2004, current_year + 1))
        print(f"Fetching BCE comm pages for {years[0]}-{years[-1]}\n")

    log_records: list[dict] = []
    stage_counts: dict[str, int] = defaultdict(int)
    total_added = 0
    coins_by_year: dict[int, int] = {}

    for year in years:
        html = fetch_year(year)
        if html is None:
            print(f"[{year}] not published yet (404)")
            continue
        write_snapshot(year, html)
        coins = parse_bce_page(html, year)
        coins_by_year[year] = len(coins)
        print(f"[{year}] {len(coins)} BCE coins parsed")

        for coin in coins:
            decision = match_identity(idx, coin["country"], coin["year"], coin["theme_slug"])
            stage_counts[decision["stage"]] += 1
            log_records.append(
                {
                    "country": coin["country"],
                    "year": coin["year"],
                    "theme_slug": coin["theme_slug"],
                    "stage": decision["stage"],
                    "eurio_id": decision.get("eurio_id"),
                    "image_url": coin["image_url"],
                }
            )
            eurio_id = decision.get("eurio_id")
            if not eurio_id:
                continue
            entry = referential.get(eurio_id)
            if entry is None:
                continue
            if enrich_entry_with_image(entry, coin):
                total_added += 1

    save_referential(referential)
    append_matching_log(log_records)

    print("\n" + "=" * 60)
    print(f"BCE coins parsed total: {sum(coins_by_year.values())}")
    print(f"Match stages: {dict(stage_counts)}")
    print(f"Images added to referential: {total_added}")
    print(f"Years covered: {sorted(coins_by_year)}")
    print("=" * 60)

    record_run("bce", "scrape", calls=0, added_coins=total_added)


if __name__ == "__main__":
    main()
