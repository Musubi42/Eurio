"""Seed `source_registry` with the 10 canonical sources.

Cf. docs/coin-richness/ROADMAP-DB.md §4 (seed + DDL). Idempotent : utilise
`INSERT OR IGNORE` sur la PK `id`. Re-run = no-op si toutes les rows existent
déjà. Pour mettre à jour une row existante (kind, base_url, notes), passer
``--update`` (UPSERT explicite).

Usage::

    .venv/bin/python -m scripts.seed_source_registry           # insert only
    .venv/bin/python -m scripts.seed_source_registry --update  # upsert all
    .venv/bin/python -m scripts.seed_source_registry --check   # report only

Le script lit la DB via ``ml/state/store.py`` afin de bénéficier du
bootstrap idempotent (les nouvelles tables P.3a sont créées si la DB est
fraîche).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from state.store import Store  # noqa: E402


# (id, display_name, kind, base_url, notes)
SEED: list[tuple[str, str, str, str | None, str]] = [
    ("numista_api",   "Numista API v3",           "reference",
     "https://api.numista.com/api/v3",
     "Source primaire référentiel — titre, issuer, year, value, mint releases, prices."),
    ("bce_official",  "BCE — pages officielles",  "official",
     "https://www.ecb.europa.eu/euro/coins/comm/",
     "Date émission, mintage total, image officielle (obverse)."),
    ("eurlex_jo",     "Journal Officiel UE (EUR-Lex)", "official",
     "https://eur-lex.europa.eu",
     "JO série C — avis officiels pièces commémoratives 2€ : image côté national, "
     "date d'émission, URL annonce. Référentiel de couverture (exhaustif par obligation légale)."),
    ("bundesbank",    "Deutsche Bundesbank",      "official",
     None,
     "Mintage DE par atelier (A/D/F/G/J) — PDFs annuels."),
    ("mdp",           "Monnaie de Paris",         "official",
     "https://www.monnaiedeparis.fr",
     "Prix BU/BE neufs, descriptions FR, MdP-spécifique."),
    ("lmdlp",         "La Monnaie de la Pièce",   "community",
     "https://lamonnaiedelapiece.com",
     "Prix boutique 2€ commémoratives par qualité (UNC/BU/BE), via WooCommerce Store API."),
    ("wikipedia",     "Wikipedia",                "community",
     None,
     "Mintage, variants, contexte historique. Source de fallback."),
    ("ebay_browse",   "eBay Browse API",          "community",
     None,
     "Annonces actives — prix marché courant."),
    ("2euros_org",    "2euros.org",               "reference",
     "https://www.2euros.org",
     "Compilation référentielle FR — mintage par atelier × qualité, rareté éditoriale."),
    ("eurio_derived", "Eurio — calcul interne",   "derived",
     None,
     "Facts dérivés en lecture (agreement_count, indice rareté dérivé, ...)."),
    ("manual",        "Curation manuelle",        "manual",
     None,
     "Décisions éditoriales admin Raphaël (tranche A/B, corrections, etc.)."),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(ML_DIR / "state" / "eurio.db"),
        help="Path to eurio.db (default: ml/state/eurio.db)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Upsert all rows (rewrites display_name, kind, base_url, notes).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report current registry state, no writes.",
    )
    args = parser.parse_args()

    store = Store(args.db)
    conn = store._connection()  # noqa: SLF001 — script utilitaire, accès direct OK

    if args.check:
        rows = conn.execute(
            "SELECT id, kind, display_name FROM source_registry ORDER BY id"
        ).fetchall()
        print(f"source_registry : {len(rows)} rows")
        for r in rows:
            print(f"  {r['id']:18s}  {r['kind']:11s}  {r['display_name']}")
        return 0

    if args.update:
        sql = """
        INSERT INTO source_registry (id, display_name, kind, base_url, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            display_name = excluded.display_name,
            kind         = excluded.kind,
            base_url     = excluded.base_url,
            notes        = excluded.notes
        """
    else:
        sql = """
        INSERT OR IGNORE INTO source_registry (id, display_name, kind, base_url, notes)
        VALUES (?, ?, ?, ?, ?)
        """

    n_before = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0]
    with store._writing() as conn:  # noqa: SLF001
        for row in SEED:
            conn.execute(sql, row)
    n_after = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0]
    added = n_after - n_before
    print(f"source_registry : {n_before} → {n_after}  (+{added}, "
          f"{'upsert' if args.update else 'insert-only'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
