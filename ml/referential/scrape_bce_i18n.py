"""Harvest des titres + descriptions officiels BCE dans les 24 langues UE.

La BCE publie chaque pièce commémorative dans les 24 langues officielles de
l'Union (``comm_{year}.{lang}.html``), titre (Feature) et description traduits
par la BCE elle-même. Ce script les récolte et peuple
``coin_descriptions_i18n`` (1 row par ``eurio_id`` × source ``bce_official`` ×
``lang``).

Méthode (cf. parser ``referential.scrape_bce_images``) :

1. **EN = langue d'ancrage.** On parse la page EN, on identifie les champs par
   leur label anglais (fiable) et on matche chaque coin à un ``eurio_id`` via le
   matcher de ``BceAdapter`` (même logique que le pipeline images → cohérence).
   Chaque coin porte ``_block_index`` (position document, stable inter-langues)
   et ``_field_order`` (ordre des champs détectés).
2. **23 autres langues = mapping par position.** On parse chaque page non-EN en
   valeurs positionnelles par ``block_index`` puis on les mappe au
   ``_field_order`` détecté en EN pour le même bloc. Garde-fou : si le nombre de
   valeurs diffère du nombre de champs EN, on saute ce coin pour cette langue et
   on le journalise (pas de fallback silencieux — doctrine trust model).

Les facts lang-invariants (tirage, date d'émission) ne sont **pas** écrits ici
(axes dédiés). Cette table = texte localisé seul.

Idempotent : UPSERT par clé, snapshots HTML cachés par (année, langue, jour)
sous ``ml/datasets/sources/bce_comm_{year}_{lang}_{date}.html``.

Usage::

    go-task ml:scrape-bce-i18n                 # toutes années, 24 langues
    .venv/bin/python -m referential.scrape_bce_i18n --year 2007
    .venv/bin/python -m referential.scrape_bce_i18n --langs fr,de,it --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from referential.eurio_referential import SOURCES_DIR
from referential.scrape_bce_images import (
    BCE_EU_LANGS,
    bce_lang_url,
    parse_bce_lang_blocks,
    parse_bce_page,
)
from sources._base.registry_map import to_registry_source
from sources.bce.adapter import BceAdapter
from state.store import Store

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = ML_DIR / "state" / "eurio.db"
USER_AGENT = "Eurio/0.1 bce-i18n-scraper (https://github.com/Musubi42/Eurio)"
RATE_LIMIT_SEC = 1.1
FIRST_BCE_YEAR = 2004
BCE_SOURCE = to_registry_source("bce")  # → 'bce_official'


@dataclass
class HarvestStats:
    years: list[int] = field(default_factory=list)
    en_coins_matched: int = 0
    en_coins_unmatched: int = 0
    rows_written: int = 0
    rows_by_lang: Counter = field(default_factory=Counter)
    pages_fetched: int = 0
    pages_cached: int = 0
    pages_404: int = 0
    # (langue, année) sautées car nombre de blocs ≠ page EN (ex. bg 2022 = 23
    # blocs vs 30) → l'alignement par block_index n'est plus fiable.
    lang_years_block_mismatch: int = 0
    # Coins où le titre est écrit mais la description omise (page non-EN plus
    # courte que l'EN → position de la description ambiguë).
    descriptions_dropped: int = 0
    skipped_no_title: int = 0


def _fetch_lang_page(
    year: int, lang: str, *, sleep: float, stats: HarvestStats
) -> str | None:
    """HTML de ``comm_{year}.{lang}.html`` (None sur 404). Cache jour sur disque."""
    cache = SOURCES_DIR / f"bce_comm_{year}_{lang}_{date.today().isoformat()}.html"
    if cache.is_file():
        stats.pages_cached += 1
        return cache.read_text(encoding="utf-8")

    resp = httpx.get(
        bce_lang_url(year, lang),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    if resp.status_code == 404:
        stats.pages_404 += 1
        return None
    resp.raise_for_status()
    time.sleep(sleep)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text, encoding="utf-8")
    stats.pages_fetched += 1
    return resp.text


def _upsert_description(
    conn: sqlite3.Connection,
    *,
    eurio_id: str,
    lang: str,
    title: str,
    description: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO coin_descriptions_i18n
          (eurio_id, source, lang, title, description, method, confidence)
        VALUES (?, ?, ?, ?, ?, 'scrape', 'canon')
        ON CONFLICT (eurio_id, source, lang) DO UPDATE SET
          title       = excluded.title,
          description = excluded.description,
          method      = excluded.method,
          confidence  = excluded.confidence,
          fetched_at  = datetime('now')
        """,
        (eurio_id, BCE_SOURCE, lang, title, description),
    )


def _lang_values_for_coin(
    coin: dict, blocks: dict[int, list[str]]
) -> tuple[str | None, str | None] | None:
    """``(title, description)`` d'un coin EN appliqué à une page non-EN.

    On n'aligne que le **préfixe stable** ``[feature, description]`` :

    - ``feature`` est toujours en première position (les coins matchés ont
      forcément un titre détecté en EN) → ``title = vals[0]`` est sûr.
    - ``description`` (2e champ en EN) n'est mappée que si la page non-EN a **au
      moins autant de valeurs** que de champs EN. Si la langue en a moins, c'est
      qu'un champ du milieu manque côté non-EN (ex. HR 2013 Boccaccio sans
      description : ``vals[1]`` y est le volume) → on écrit le titre seul plutôt
      qu'une fausse description.

    Les champs de queue (volume/date) peuvent diverger en présence d'une langue
    à l'autre (la page BCE EN omet parfois la date des pièces récentes) sans
    bloquer : ils sont hors périmètre de cette table.

    Retourne ``None`` si le bloc est absent ou le titre vide (coin journalisé
    par l'appelant).
    """
    field_order: list[str] = coin["_field_order"]
    vals = blocks.get(coin["_block_index"])
    if not vals:
        return None
    title = vals[0]
    if not title:
        return None
    description: str | None = None
    if (
        len(field_order) > 1
        and field_order[1] == "description"
        and len(vals) >= len(field_order)
    ):
        description = vals[1]
    return title, description


def harvest_year(
    conn: sqlite3.Connection,
    adapter: BceAdapter,
    ref_index,
    year: int,
    langs: list[str],
    *,
    sleep: float,
    write: bool,
    stats: HarvestStats,
) -> None:
    en_html = _fetch_lang_page(year, "en", sleep=sleep, stats=stats)
    if en_html is None:
        logger.info("[bce-i18n] %s : page EN absente (404) — année non publiée", year)
        return

    en_block_count = len(parse_bce_lang_blocks(en_html))
    en_coins = parse_bce_page(en_html, year)
    # Assignation one-to-one par (country, year) — même matcher que le pipeline
    # images, garantit qu'un eurio_id n'est pas réclamé par 2 blocs BCE.
    assignments = adapter.match_group(
        ref_index, [(c["country"], year, c["theme_slug"]) for c in en_coins]
    )
    matched: list[dict] = []
    for coin, eurio_id in zip(en_coins, assignments):
        if eurio_id is None:
            stats.en_coins_unmatched += 1
            continue
        coin["eurio_id"] = eurio_id
        matched.append(coin)
    stats.en_coins_matched += len(matched)
    logger.info(
        "[bce-i18n] %s : %d coins EN, %d matchés",
        year, len(en_coins), len(matched),
    )
    if not matched:
        return

    for lang in langs:
        if lang == "en":
            lang_blocks = None
        else:
            lang_html = _fetch_lang_page(year, lang, sleep=sleep, stats=stats)
            if lang_html is None:
                logger.warning("[bce-i18n] %s/%s : 404 — langue sautée", year, lang)
                continue
            lang_blocks = parse_bce_lang_blocks(lang_html)
            # Garde-fou niveau page : si le nombre de blocs-pièces diffère de
            # l'EN, l'alignement par block_index n'est plus fiable → on saute
            # toute la langue-année (pas de fallback silencieux).
            if len(lang_blocks) != en_block_count:
                stats.lang_years_block_mismatch += 1
                logger.warning(
                    "[bce-i18n] %s/%s : %d blocs ≠ %d (EN) — langue-année sautée",
                    year, lang, len(lang_blocks), en_block_count,
                )
                continue

        for coin in matched:
            if lang == "en":
                title, description = coin["feature"], coin.get("description")
            else:
                res = _lang_values_for_coin(coin, lang_blocks)
                if res is None:
                    stats.skipped_no_title += 1
                    logger.warning(
                        "[bce-i18n] %s/%s : bloc %s introuvable/vide pour %s — sauté",
                        year, lang, coin["_block_index"], coin["eurio_id"],
                    )
                    continue
                title, description = res
                if description is None and "description" in coin["_field_order"]:
                    stats.descriptions_dropped += 1
            if not title:
                stats.skipped_no_title += 1
                continue
            if write:
                _upsert_description(
                    conn,
                    eurio_id=coin["eurio_id"],
                    lang=lang,
                    title=title,
                    description=description,
                )
            stats.rows_written += 1
            stats.rows_by_lang[lang] += 1


def harvest(
    store: Store,
    *,
    years: list[int],
    langs: list[str],
    sleep: float = RATE_LIMIT_SEC,
    write: bool = True,
) -> HarvestStats:
    conn = store._connection()  # noqa: SLF001
    adapter = BceAdapter(conn=conn)
    ref_index = adapter._load_referential()  # noqa: SLF001
    stats = HarvestStats(years=years)
    for year in years:
        harvest_year(
            conn, adapter, ref_index, year, langs,
            sleep=sleep, write=write, stats=stats,
        )
    if write:
        conn.commit()
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--year", type=int, default=None, help="Une seule année (def: 2004→année-1)")
    ap.add_argument(
        "--langs", type=str, default=None,
        help="Liste CSV de langues (def: les 24 langues UE)",
    )
    ap.add_argument("--sleep", type=float, default=RATE_LIMIT_SEC)
    ap.add_argument("--dry-run", action="store_true", help="Ne pas écrire en DB")
    args = ap.parse_args()

    if args.year is not None:
        years = [args.year]
    else:
        years = list(range(FIRST_BCE_YEAR, date.today().year))

    if args.langs:
        langs = [s.strip() for s in args.langs.split(",") if s.strip()]
        unknown = [lg for lg in langs if lg not in BCE_EU_LANGS]
        if unknown:
            ap.error(f"langues inconnues: {unknown} (valides: {', '.join(BCE_EU_LANGS)})")
    else:
        langs = list(BCE_EU_LANGS)

    store = Store(args.db)
    stats = harvest(
        store, years=years, langs=langs,
        sleep=args.sleep, write=not args.dry_run,
    )

    print("\n" + "=" * 60)
    print(f"Années             : {years[0]}–{years[-1]} ({len(years)})")
    print(f"Langues            : {len(langs)} ({', '.join(langs)})")
    print(f"Coins EN matchés   : {stats.en_coins_matched} (non matchés: {stats.en_coins_unmatched})")
    print(f"Pages fetch/cache  : {stats.pages_fetched} / {stats.pages_cached} (404: {stats.pages_404})")
    print(f"Rows écrites       : {stats.rows_written}{'  (DRY-RUN)' if args.dry_run else ''}")
    print(f"Lang-années sautées (blocs ≠ EN) : {stats.lang_years_block_mismatch}")
    print(f"Descriptions omises (page + courte) : {stats.descriptions_dropped} | sans titre: {stats.skipped_no_title}")
    print("Rows par langue    :")
    for lg in langs:
        print(f"   {lg}: {stats.rows_by_lang.get(lg, 0)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
