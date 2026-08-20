"""Backfill listing_text_signals from existing source_images.

Itère sur tous les ``source_images`` qui n'ont pas encore d'entrée dans
``listing_text_signals`` pour la version d'extracteur courante (v1) et
extrait les signaux depuis ``listing_title``.

Idempotent : skip les rows déjà présentes (même ``extractor_version``).
``--force`` recompute en place.

Usage:
    .venv/bin/python -m scripts.backfill_text_signals
    .venv/bin/python -m scripts.backfill_text_signals --limit 100
    .venv/bin/python -m scripts.backfill_text_signals --force
    .venv/bin/python -m scripts.backfill_text_signals --source ebay
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sources._base.steps.text_signal import (  # noqa: E402
    EXTRACTOR_VERSION,
    run_text_signal_extract,
)
from store import Store, resolve_db_path  # noqa: E402

# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la
# machine lit (`EURIO_DB_PATH` — la réplique sous Direction A, le canonique
# sur le VPS), jamais un chemin codé en dur. Mesuré le 2026-08-19 :
# `state/eurio.db` porte 6205 `image_assets` (5466 prédictions `2eur_all`)
# contre 12454 / 12454 dans `state/eurio.replica.db` — la banque `2eur_all`
# avait été bâtie dessus pendant des semaines.
# Repli hors devShell : `state/eurio.replica.db`. La règle et son arbitrage
# (2026-08-19) sont dans la docstring de `store.resolve_db_path`.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=None,
        help="Filter on a single source_id (default: all sources).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if a row already exists for the same extractor_version.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N source_images (smoke / dry runs).",
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help=f"Fichier SQLite à écrire (défaut : {DB_PATH}, résolu par "
             "store.resolve_db_path — EURIO_DB_PATH, sinon le repli "
             "ml/state/eurio.replica.db).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    logging.getLogger("sources._base.steps.text_signal").setLevel(logging.INFO)

    store = Store(Path(args.db))
    conn = store._connection()  # noqa: SLF001

    sql = "SELECT id, source_ref FROM source_images WHERE 1=1"
    params: list = []
    if args.source:
        sql += " AND source = ?"
        params.append(args.source)
    if not args.force:
        sql += (
            " AND id NOT IN (SELECT source_image_id FROM listing_text_signals "
            "WHERE extractor_version = ?)"
        )
        params.append(EXTRACTOR_VERSION)
    sql += " ORDER BY fetched_at ASC"
    if args.limit is not None:
        sql += f" LIMIT {int(args.limit)}"

    rows = conn.execute(sql, params).fetchall()
    source_image_ids = {r["source_ref"]: r["id"] for r in rows}

    print(f"Selected {len(source_image_ids)} source_images for backfill "
          f"(extractor_version={EXTRACTOR_VERSION}, force={args.force})")

    if not source_image_ids:
        return 0

    t0 = time.perf_counter()
    result = run_text_signal_extract(
        conn=conn,
        run=None,
        source_image_ids=source_image_ids,
        force=args.force,
        store=store,
    )
    dt = time.perf_counter() - t0

    print()
    print(f"Extracted:           {result.n_extracted}")
    print(f"Skipped (existing):  {result.n_skipped_existing}")
    print(f"Skipped (empty):     {result.n_skipped_empty_title}")
    print(f"Errors:              {result.n_errors}")
    print(f"Total time:          {dt:.2f}s")
    if result.n_extracted:
        print(f"Per-image average:   {dt / result.n_extracted * 1000:.2f}ms")

    # Distribution audit
    print("\nCoverage distribution:")
    for r in conn.execute(
        "SELECT coverage, COUNT(*) AS n FROM listing_text_signals "
        "WHERE extractor_version = ? GROUP BY coverage ORDER BY n DESC",
        (EXTRACTOR_VERSION,),
    ).fetchall():
        print(f"  {r['coverage']:8s}  {r['n']}")

    print("\nis_lot distribution:")
    for r in conn.execute(
        "SELECT is_lot, COUNT(*) AS n FROM listing_text_signals "
        "WHERE extractor_version = ? GROUP BY is_lot ORDER BY n DESC",
        (EXTRACTOR_VERSION,),
    ).fetchall():
        print(f"  is_lot={r['is_lot']}  {r['n']}")

    print("\nvs_target_verdict distribution:")
    for r in conn.execute(
        "SELECT COALESCE(vs_target_verdict, '∅') AS v, COUNT(*) AS n "
        "  FROM listing_text_signals "
        " WHERE extractor_version = ? "
        " GROUP BY vs_target_verdict ORDER BY n DESC",
        (EXTRACTOR_VERSION,),
    ).fetchall():
        print(f"  {r['v']:11s}  {r['n']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
