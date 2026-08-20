"""Sweep one-shot : sème ``empty_upstream`` pour les commémos récentes que la
BCE n'a pas (encore) publiées.

Pour distinguer « pas encore publié » (⏳) de « jamais tenté » (⬜) sur la fiche,
il faut une tentative réseau qui revient vide. Ce sweep itère par **année**
(≈3-4 pages, pas par coin → respecte le rate-limit BCE) : pour chaque commémo
2€ récente sans verdict BCE, si la page-année est 404 ou si le coin est absent
des blocs de la page, on pose ``empty_upstream``. Les coins effectivement
présents sur BCE sont laissés au backfill/refresh (qui posera ``ok``).

Idempotent, manuel (jamais programmé). Usage :
    go-task ml:sweep-bce-empty [-- --min-year 2024 --dry-run --db PATH]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.scrape_bce_i18n import (  # noqa: E402
    HarvestStats, RATE_LIMIT_SEC, _fetch_lang_page, parse_bce_page,
)
from sources.bce.adapter import BceAdapter  # noqa: E402
from state.source_status import upsert_source_status  # noqa: E402
from store import Store, resolve_db_path  # noqa: E402

logger = logging.getLogger("sweep_bce_empty")
# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la
# machine lit (`EURIO_DB_PATH` — la réplique sous Direction A, le canonique
# sur le VPS), jamais un chemin codé en dur. Mesuré le 2026-08-19 :
# `state/eurio.db` porte 6205 `image_assets` (5466 prédictions `2eur_all`)
# contre 12454 / 12454 dans `state/eurio.replica.db` — la banque `2eur_all`
# avait été bâtie dessus pendant des semaines.
# Repli hors devShell : `state/eurio.replica.db`. La règle et son arbitrage
# (2026-08-19) sont dans la docstring de `store.resolve_db_path`.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")


def sweep(store: Store, *, min_year: int, sleep: float, dry: bool) -> dict:
    conn = store._connection()  # noqa: SLF001
    adapter = BceAdapter(conn=conn)
    ref_index = adapter._load_referential()  # noqa: SLF001

    # Commémos 2€ récentes SANS verdict BCE (ni ok/empty_upstream/error).
    candidates = conn.execute(
        """
        SELECT eurio_id, country, year FROM coins c
        WHERE c.is_commemorative = 1 AND c.face_value = 2.0 AND c.year >= ?
          AND c.canonical_eurio_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM coin_source_status s
            WHERE s.eurio_id = c.eurio_id AND s.source = 'bce_official'
              AND s.state IN ('ok', 'empty_upstream', 'error'))
        """,
        (min_year,),
    ).fetchall()

    by_year: dict[int, list[str]] = defaultdict(list)
    countries: dict[str, str] = {}
    for r in candidates:
        by_year[r["year"]].append(r["eurio_id"])
        countries[r["eurio_id"]] = r["country"]

    stats = {"candidates": len(candidates), "years": 0,
             "empty_upstream": 0, "on_bce_skipped": 0, "pages_404": 0}

    for year, ids in sorted(by_year.items()):
        hs = HarvestStats(years=[year])
        en = _fetch_lang_page(year, "en", sleep=sleep, stats=hs)
        matched: set[str] = set()
        if en is None:
            stats["pages_404"] += 1
            logger.info("[sweep] %s : page EN 404 → %d coins empty_upstream", year, len(ids))
        else:
            coins = parse_bce_page(en, year)
            assignments = adapter.match_group(
                ref_index, [(c["country"], year, c["theme_slug"]) for c in coins]
            )
            matched = {e for e in assignments if e}
        for eid in ids:
            if eid in matched:
                stats["on_bce_skipped"] += 1  # présent sur BCE → backfill/refresh
                continue
            if not dry:
                upsert_source_status(
                    conn, eurio_id=eid, source="bce_official",
                    state="empty_upstream", axes={},
                )
            stats["empty_upstream"] += 1
        stats["years"] += 1

    if not dry:
        conn.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--min-year", type=int, default=2024)
    parser.add_argument("--sleep", type=float, default=RATE_LIMIT_SEC)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(message)s")
    store = Store(Path(args.db))
    stats = sweep(store, min_year=args.min_year, sleep=args.sleep, dry=args.dry_run)
    print(f"sweep bce empty_upstream{' (dry-run)' if args.dry_run else ''} :")
    for k, v in stats.items():
        print(f"  {k:16s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
