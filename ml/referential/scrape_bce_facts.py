"""Harvest des facts BCE lang-invariants : tirage + date d'émission.

Le tirage (issuing_volume) et la date (issuing_date) sont identiques dans les
24 langues → on les parse depuis la page **EN** uniquement. Écrits dans
``coin_observations`` (provenance-first, n'écrase **pas** ``coins.mintage``
Numista — les deux coexistent, traçables) :

- ``observation_type='mintage_official'`` payload ``{value, raw_text}``
- ``observation_type='issuing_date'``     payload ``{year, month, day, raw_text}``

Le matching eurio_id réutilise ``BceAdapter.match_group`` (assignation 1-to-1,
même logique que le pipeline images + le harvester i18n).

Cross-check : compare le tirage BCE au ``coins.mintage`` (Numista) et rapporte
les divergences (aucune n'est écrasée — revue éditoriale).

Usage::

    go-task ml:scrape-bce-facts                 # toutes années
    .venv/bin/python -m referential.scrape_bce_facts --year 2007 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from referential.bce_facts import parse_issuing_date, parse_issuing_volume
from referential.eurio_referential import SOURCES_DIR
from referential.scrape_bce_images import bce_lang_url, parse_bce_page
from sources._base.registry_map import to_registry_source
from sources.bce.adapter import BceAdapter
from state.store import Store

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = ML_DIR / "state" / "eurio.db"
USER_AGENT = "Eurio/0.1 bce-facts-scraper (https://github.com/Musubi42/Eurio)"
FIRST_BCE_YEAR = 2004
BCE_SOURCE = to_registry_source("bce")  # → 'bce_official'


@dataclass
class FactStats:
    years: list[int] = field(default_factory=list)
    coins_matched: int = 0
    mintage_written: int = 0
    date_written: int = 0
    # Cross-check tirage BCE vs somme Numista (tous types d'issue).
    mintage_both_present: int = 0
    mintage_exact: int = 0
    mintage_within_5pct: int = 0
    divergences: list[dict] = field(default_factory=list)  # > 5 %


def _fetch_en(year: int) -> str | None:
    """HTML EN (cache jour partagé avec le harvester i18n). None sur 404."""
    cache = SOURCES_DIR / f"bce_comm_{year}_en_{date.today().isoformat()}.html"
    if cache.is_file():
        return cache.read_text(encoding="utf-8")
    resp = httpx.get(
        bce_lang_url(year, "en"),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


def _coerce_int(value_json: str) -> int | None:
    """Extrait un entier d'un value_json mint_release (int brut ou {'value': n})."""
    try:
        val = json.loads(value_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(val, dict):
        val = val.get("value", val.get("mintage"))
    return int(val) if isinstance(val, (int, float)) else None


def _upsert_observation(
    conn: sqlite3.Connection,
    *,
    eurio_id: str,
    observation_type: str,
    payload: dict,
    source_ref: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO coin_observations
          (eurio_id, source, observation_type, payload_json, source_ref)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (eurio_id, source, observation_type) DO UPDATE SET
          payload_json = excluded.payload_json,
          source_ref   = excluded.source_ref,
          recorded_at  = datetime('now')
        """,
        (eurio_id, BCE_SOURCE, observation_type, json.dumps(payload, ensure_ascii=False), source_ref),
    )


def harvest(
    store: Store, *, years: list[int], write: bool = True
) -> FactStats:
    conn = store._connection()  # noqa: SLF001
    adapter = BceAdapter(conn=conn)
    ref_index = adapter._load_referential()  # noqa: SLF001
    stats = FactStats(years=years)
    # Tirage Numista pour le cross-check = **somme de tous les types d'issue**
    # (CIRC + BU + COIN_CARD + PROOF…) par eurio_id. Le BCE issuing_volume est
    # un total par type, qui correspond à cette somme quand Numista est complet
    # (cf. docs : MT/HR concordent exactement). `coins.mintage` est vide, le
    # tirage Numista vit dans mint_release_observations (per-issue).
    numista_mintage: dict[str, int] = {}
    for r in conn.execute(
        """
        SELECT mr.parent_type_id AS eurio_id, o.value_json AS v
        FROM mint_release_observations o
        JOIN coin_mint_releases mr ON mr.id = o.mint_release_id
        WHERE o.fact_type = 'mintage'
        """
    ):
        val = _coerce_int(r["v"])
        if val is not None:
            numista_mintage[r["eurio_id"]] = numista_mintage.get(r["eurio_id"], 0) + val

    for year in years:
        html = _fetch_en(year)
        if html is None:
            logger.info("[bce-facts] %s : page EN absente (404)", year)
            continue
        coins = parse_bce_page(html, year)
        assignments = adapter.match_group(
            ref_index, [(c["country"], year, c["theme_slug"]) for c in coins]
        )
        for coin, eurio_id in zip(coins, assignments):
            if eurio_id is None:
                continue
            stats.coins_matched += 1
            source_ref = f"{coin['country']}-{year}-{coin['theme_slug']}"

            if coin.get("issuing_volume"):
                vol = parse_issuing_volume(coin["issuing_volume"])
                if write:
                    _upsert_observation(
                        conn, eurio_id=eurio_id, observation_type="mintage_official",
                        payload=vol, source_ref=source_ref,
                    )
                stats.mintage_written += 1
                _crosscheck_mintage(stats, eurio_id, vol, numista_mintage, year, coin)

            if coin.get("issuing_date"):
                dat = parse_issuing_date(coin["issuing_date"])
                if write:
                    _upsert_observation(
                        conn, eurio_id=eurio_id, observation_type="issuing_date",
                        payload=dat, source_ref=source_ref,
                    )
                stats.date_written += 1

    if write:
        conn.commit()
    return stats


def _crosscheck_mintage(
    stats: FactStats, eurio_id: str, vol: dict, numista: dict, year: int, coin: dict
) -> None:
    bce_val = vol.get("value")
    num_val = numista.get(eurio_id)
    if bce_val is None or not num_val:
        return
    stats.mintage_both_present += 1
    ratio = bce_val / num_val
    if bce_val == num_val:
        stats.mintage_exact += 1
        stats.mintage_within_5pct += 1
    elif 0.95 <= ratio <= 1.05:
        stats.mintage_within_5pct += 1
    else:
        stats.divergences.append({
            "eurio_id": eurio_id,
            "bce": bce_val,
            "numista": num_val,
            "ratio": round(ratio, 3),
            "feature": coin["feature"][:50],
        })


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    years = [args.year] if args.year is not None else list(range(FIRST_BCE_YEAR, date.today().year))
    store = Store(args.db)
    stats = harvest(store, years=years, write=not args.dry_run)

    print("\n" + "=" * 60)
    print(f"Années             : {years[0]}–{years[-1]} ({len(years)})")
    print(f"Coins matchés      : {stats.coins_matched}")
    print(f"Tirages écrits     : {stats.mintage_written}{'  (DRY-RUN)' if args.dry_run else ''}")
    print(f"Dates écrites      : {stats.date_written}")
    print(f"Cross-check tirage : {stats.mintage_exact} exacts, "
          f"{stats.mintage_within_5pct}/{stats.mintage_both_present} à ±5 % vs Numista "
          f"(somme tous types) — {len(stats.divergences)} divergences >5 %")
    if stats.divergences:
        print("  Top divergences (ratio BCE/Numista, stockées séparément — pas réconciliées) :")
        for d in sorted(stats.divergences, key=lambda x: abs((x["ratio"] or 1) - 1), reverse=True)[:12]:
            print(f"   {d['eurio_id'][:48]:50} BCE={d['bce']:>11} Numista={d['numista']:>11} ×{d['ratio']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
