"""Backfill ``coin_source_status`` (état ``ok``) dérivé de la donnée existante.

AUCUN réseau : on lit les tables déjà peuplées et on pose ``state='ok'`` +
``detail_json.axes`` par (coin × source) pour tout coin ayant au moins un axe
porteur. Les coins sans donnée restent absents (= ``never``). On ne touche PAS
les rows portant un verdict réseau (``empty_upstream``/``error``) posé par un
refresh — un verdict réseau prime sur une dérivation locale (sauf ``--force``).

Idempotent. Usage :
    go-task ml:backfill-source-status [-- --db PATH --force --verbose]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from state.source_status import get_network_verdicted_ids, upsert_source_status  # noqa: E402
from store import Store, resolve_db_path  # noqa: E402
from scripts._vps_only_guard import guard_vps_only  # noqa: E402

logger = logging.getLogger("backfill_source_status")

# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la
# machine lit (`EURIO_DB_PATH` — la réplique sous Direction A, le canonique
# sur le VPS), jamais un chemin codé en dur. Mesuré le 2026-08-19 :
# `state/eurio.db` porte 6205 `image_assets` (5466 prédictions `2eur_all`)
# contre 12454 / 12454 dans `state/eurio.replica.db` — la banque `2eur_all`
# avait été bâtie dessus pendant des semaines.
# Repli hors devShell : `state/eurio.replica.db`. La règle et son arbitrage
# (2026-08-19) sont dans la docstring de `store.resolve_db_path`.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")

# registry id → fonction de dérivation. Chaque fonction renvoie
# {eurio_id: {axe: valeur}} pour les coins ayant ≥1 axe porteur.
AxesByCoin = dict[str, dict[str, Any]]


def _flag(conn, sql: str, params: tuple = ()) -> set[str]:
    return {r[0] for r in conn.execute(sql, params).fetchall()}


def derive_bce(conn) -> AxesByCoin:
    out: AxesByCoin = defaultdict(dict)
    for eid, n in conn.execute(
        "SELECT eurio_id, COUNT(*) FROM coin_descriptions_i18n "
        "WHERE source='bce_official' GROUP BY eurio_id"
    ):
        out[eid]["description"] = True
        out[eid]["n_langs"] = n
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_observations "
                           "WHERE source='bce_official' AND observation_type='mintage_official'"):
        out[eid]["mintage"] = True
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_observations "
                           "WHERE source='bce_official' AND observation_type='issuing_date'"):
        out[eid]["issuing_date"] = True
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_canonical_images "
                           "WHERE source='bce_official'"):
        out[eid]["images"] = True
    return out


def derive_numista(conn) -> AxesByCoin:
    out: AxesByCoin = defaultdict(dict)
    for eid in _flag(conn, "SELECT eurio_id FROM coins WHERE numista_id IS NOT NULL"):
        out[eid]["identity"] = True
    for eid in _flag(conn, "SELECT target_id FROM coin_source_refs "
                           "WHERE source='numista_api' AND target_kind='coin'"):
        out[eid]["identity"] = True
    for eid in _flag(conn, "SELECT DISTINCT parent_type_id FROM coin_mint_releases"):
        out[eid]["mint_releases"] = True
    for eid in _flag(conn, "SELECT DISTINCT r.parent_type_id FROM mint_release_prices p "
                           "JOIN coin_mint_releases r ON r.id = p.mint_release_id "
                           "WHERE p.source='numista_api'"):
        out[eid]["prices"] = True
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_names_i18n WHERE source='numista_api'"):
        out[eid]["i18n"] = True
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_observations WHERE source='numista_api'"):
        out[eid]["observations"] = True
    return out


def derive_ebay(conn) -> AxesByCoin:
    out: AxesByCoin = defaultdict(dict)
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_market_quotes WHERE source='ebay_browse'"):
        out[eid]["quotes"] = True
    for eid in _flag(conn, "SELECT DISTINCT target_eurio_id FROM source_images "
                           "WHERE source='ebay' AND target_eurio_id IS NOT NULL"):
        out[eid]["listings"] = True
    return out


def derive_lmdlp(conn) -> AxesByCoin:
    out: AxesByCoin = defaultdict(dict)
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_market_quotes WHERE source='lmdlp'"):
        out[eid]["quotes"] = True
    for eid in _flag(conn, "SELECT target_id FROM coin_source_refs "
                           "WHERE source='lmdlp' AND target_kind='coin'"):
        out[eid]["refs"] = True
    return out


def derive_wikipedia(conn) -> AxesByCoin:
    out: AxesByCoin = defaultdict(dict)
    for eid in _flag(conn, "SELECT DISTINCT eurio_id FROM coin_cross_refs "
                           "WHERE ref_type LIKE '%wikipedia%'"):
        out[eid]["url"] = True
    for eid in _flag(conn, "SELECT target_id FROM coin_source_refs "
                           "WHERE source='wikipedia' AND target_kind='coin'"):
        out[eid]["url"] = True
    return out


DERIVERS = {
    "bce_official": derive_bce,
    "numista_api": derive_numista,
    "ebay_browse": derive_ebay,
    "lmdlp": derive_lmdlp,
    "wikipedia": derive_wikipedia,
}


def run_backfill(store: Store, *, force: bool = False, limit: int | None = None) -> dict[str, int]:
    conn = store._connection()  # noqa: SLF001
    # Garde-fou FK : certaines sources (source_images eBay) référencent des
    # target_eurio_id orphelins (coins renommés/supprimés). On n'upsert que des
    # eurio_id présents dans `coins`.
    valid_coins = {r[0] for r in conn.execute("SELECT eurio_id FROM coins")}
    stats: dict[str, int] = {}
    for source, derive in DERIVERS.items():
        derived = derive(conn)
        protected = set() if force else get_network_verdicted_ids(conn, source)
        n = 0
        skipped_orphan = 0
        for eid, axes in derived.items():
            if eid in protected:
                continue
            if eid not in valid_coins:
                skipped_orphan += 1
                continue
            upsert_source_status(
                conn, eurio_id=eid, source=source, state="ok",
                axes=axes, checked=False,
            )
            n += 1
            if limit and n >= limit:
                break
        stats[source] = n
        logger.info("[%s] %d coins → ok (protégés: %d, orphelins ignorés: %d)",
                    source, n, len(protected), skipped_orphan)
    conn.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--force", action="store_true",
                        help="Écrase aussi les verdicts réseau (empty_upstream/error).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Throttle : max N coins par source (smoke test).")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--i-know-this-is-canonical", action="store_true", dest="allow_non_vps",
        help="Autorise hors VPS (--db pointe une copie canonique). Sinon refuse "
             "sur une machine cliente Direction A (backfill non transporté par /ingest).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(message)s")
    # UPDATE brut de coin_source_status (dérivé local, last_run_id NULL → NE
    # voyage PAS via le run-batch C4c) : réservé au canonique.
    guard_vps_only("backfill_coin_source_status", allow=args.allow_non_vps)
    # `--db` doit primer : `resolve_db_path(args.db)` ignorait la valeur
    # passée dès que `EURIO_DB_PATH` était posé (le devShell le pose
    # toujours) — le drapeau était un leurre, alors même que le message
    # de `guard_vps_only` invite à s'en servir pour désigner une copie
    # canonique. Le défaut, lui, est déjà résolu (cf. DB_PATH).
    store = Store(Path(args.db))
    stats = run_backfill(store, force=args.force, limit=args.limit)
    total = sum(stats.values())
    print(f"backfill coin_source_status : {total} rows ok")
    for source, n in stats.items():
        print(f"  {source:14s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
