"""Seed `mints` avec les ateliers monétaires canoniques de l'eurozone.

Sous-chunk P.7c.1 du chantier coin-richness. La table `mints` est référencée
par ``coin_mint_releases.mint_id`` (FK ON DELETE RESTRICT). Sans seed, les
inserts mint_releases avec un mint_letter connu (DE A/D/F/G/J, IT R, ES M…)
ne peuvent pas lier proprement.

Couverture initiale : pays de la cohorte 19 + DE multi-ateliers + ateliers
producteurs fréquents pour micro-pays (Pessac, Roma, Madrid, Mint of
Finland). Les pays sans atelier propre (LU, MT, CY, AD, MC, SM, VA dont la
production est sous-traitée) sont représentés par leur producteur effectif
quand on le connaît avec certitude (recherche historique 2026-05-26).

Convention slug PK : ``{iso-country-lowercase}-{city-slug}[-{mark}]``
  - mark présent quand l'atelier a une lettre frappe canonique
    (cas DE A/D/F/G/J, IT R, ES M, FR pessac sans lettre mais slug local)
  - mark absent quand l'atelier n'a qu'une seule production nationale

Idempotent : ``INSERT OR IGNORE`` sur la PK. ``--update`` pour upsert.

Usage::

    .venv/bin/python -m scripts.seed_mints
    .venv/bin/python -m scripts.seed_mints --update
    .venv/bin/python -m scripts.seed_mints --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402


# (id, country, mark, city, display_name, founded_year, notes)
SEED: list[tuple[str, str, str | None, str, str, int | None, str | None]] = [
    # ─── Allemagne — 5 ateliers fédéraux canoniques (A/D/F/G/J) ─────────────
    ("de-berlin-a",   "DE", "A", "Berlin",     "Staatliche Münze Berlin",                    1280, None),
    ("de-munich-d",   "DE", "D", "Munich",     "Bayerisches Hauptmünzamt",                   1158, None),
    ("de-stuttgart-f","DE", "F", "Stuttgart",  "Staatliche Münze Stuttgart",                 1374, None),
    ("de-karlsruhe-g","DE", "G", "Karlsruhe",  "Staatliche Münzen Baden-Württemberg",        1827, None),
    ("de-hamburg-j",  "DE", "J", "Hamburg",    "Hamburgische Münze",                         1875, None),

    # ─── France — Pessac (pas de lettre, 1 atelier) ─────────────────────────
    ("fr-pessac",     "FR", None, "Pessac",    "Monnaie de Paris (atelier de Pessac)",       1973, "Frappe les euros depuis 1999 ; siège Paris reste pour pièces commémoratives haut-de-gamme."),

    # ─── Italie ─────────────────────────────────────────────────────────────
    ("it-roma-r",     "IT", "R", "Roma",       "Istituto Poligrafico e Zecca dello Stato",   1928, None),

    # ─── Espagne ───────────────────────────────────────────────────────────
    ("es-madrid-m",   "ES", "M", "Madrid",     "Fábrica Nacional de Moneda y Timbre — Real Casa de la Moneda", 1893, None),

    # ─── Autriche ──────────────────────────────────────────────────────────
    ("at-wien",       "AT", None, "Wien",      "Münze Österreich",                           1397, None),

    # ─── Belgique ──────────────────────────────────────────────────────────
    ("be-brussels",   "BE", None, "Brussels",  "Royal Belgian Mint",                         1832, "Cessation de la frappe en 2017 ; production sous-traitée depuis (Pays-Bas, Finlande)."),

    # ─── Pays-Bas ──────────────────────────────────────────────────────────
    ("nl-utrecht",    "NL", None, "Utrecht",   "Koninklijke Nederlandse Munt",               1567, "Symbole : caducée de Mercure."),

    # ─── Finlande — Mint of Finland (Vantaa) ────────────────────────────────
    ("fi-vantaa",     "FI", None, "Vantaa",    "Suomen Rahapaja (Mint of Finland)",          1864, "Produit aussi pour EE, IE et autres petits émetteurs euro à différentes années."),

    # ─── Irlande ───────────────────────────────────────────────────────────
    ("ie-sandyford", "IE", None, "Sandyford",  "Currency Centre — Central Bank of Ireland",  1978, None),

    # ─── Portugal ──────────────────────────────────────────────────────────
    ("pt-lisbon",     "PT", None, "Lisbon",    "Imprensa Nacional-Casa da Moeda",            1768, None),

    # ─── Grèce ─────────────────────────────────────────────────────────────
    ("gr-athens",     "GR", None, "Athens",    "Bank of Greece Printing Works and Mint",     1941, None),

    # ─── Slovaquie ─────────────────────────────────────────────────────────
    ("sk-kremnica",   "SK", None, "Kremnica",  "Mincovňa Kremnica",                          1328, "Plus ancien atelier d'Europe encore en activité."),

    # ─── Slovénie ──────────────────────────────────────────────────────────
    ("si-ljubljana",  "SI", None, "Ljubljana", "Banka Slovenije (sous-traitance variable)",  None, "Frappe sous-traitée selon les années (FI Vantaa, NL Utrecht)."),

    # ─── Estonie ───────────────────────────────────────────────────────────
    ("ee-tallinn",    "EE", None, "Tallinn",   "Eesti Pank (sous-traitance variable)",       None, "Production sous-traitée (FI Vantaa principalement)."),

    # ─── Lettonie ──────────────────────────────────────────────────────────
    ("lv-riga",       "LV", None, "Riga",      "Latvijas Banka (sous-traitance variable)",   None, "Production sous-traitée."),

    # ─── Lituanie ──────────────────────────────────────────────────────────
    ("lt-vilnius",    "LT", None, "Vilnius",   "Lietuvos monetų kalykla",                    1990, None),

    # ─── Luxembourg ────────────────────────────────────────────────────────
    ("lu-contracted", "LU", None, "—",         "Luxembourg — production sous-traitée",       None, "FR Pessac, NL Utrecht ou autres selon années."),

    # ─── Malte ─────────────────────────────────────────────────────────────
    ("mt-contracted", "MT", None, "—",         "Malta — production sous-traitée",            None, "FR Pessac, IT Roma, FI Vantaa selon années."),

    # ─── Chypre ────────────────────────────────────────────────────────────
    ("cy-contracted", "CY", None, "—",         "Cyprus — production sous-traitée",           None, "GR Athens, FI Vantaa selon années."),

    # ─── Croatie (rejoint la zone euro 2023) ───────────────────────────────
    ("hr-zagreb",     "HR", None, "Zagreb",    "Hrvatski novčarski zavod",                   1996, None),

    # ─── Bulgarie (rejoint la zone euro 2026-01-01) ────────────────────────
    ("bg-sofia",      "BG", None, "Sofia",     "Българска народна банка — Mint of Bulgaria", 1952, "Pays adhérent à l'euro le 2026-01-01."),

    # ─── Micro-pays — production sous-traitée historiquement ──────────────
    ("ad-contracted", "AD", None, "—",         "Andorra — production sous-traitée",          None, "Frappe historique FR Pessac + ES Madrid."),
    ("mc-contracted", "MC", None, "—",         "Monaco — production sous-traitée",           None, "Frappe FR Pessac."),
    ("sm-roma",       "SM", None, "Roma",      "Repubblica di San Marino — sous-traité IT",  None, "Frappe IT Roma (R)."),
    ("va-roma",       "VA", None, "Roma",      "Stato della Città del Vaticano — sous-traité IT", None, "Frappe IT Roma (R)."),
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
        help="UPSERT (override existing rows). Sinon INSERT OR IGNORE.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only : liste les rows existantes vs SEED, exit non-zero si delta.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ DB not found: {db_path}", file=sys.stderr)
        return 1

    # Bootstrap idempotent — ensures `mints` exists.
    store = Store(db_path)
    conn = store._connection()
    try:
        existing = {
            row[0] for row in conn.execute("SELECT id FROM mints")
        }
        seed_ids = {row[0] for row in SEED}

        missing = seed_ids - existing
        extra = existing - seed_ids

        if args.check:
            print(f"  Seed canonique : {len(seed_ids)} entries")
            print(f"  En DB          : {len(existing)} entries")
            if missing:
                print(f"  Manquantes ({len(missing)}) : {sorted(missing)}")
            if extra:
                print(f"  En DB mais hors seed ({len(extra)}) : {sorted(extra)}")
            return 1 if (missing or extra) else 0

        action = "UPSERT" if args.update else "INSERT OR IGNORE"
        if args.update:
            sql = """
                INSERT INTO mints (id, country, mark, city, display_name, founded_year, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                  country=excluded.country,
                  mark=excluded.mark,
                  city=excluded.city,
                  display_name=excluded.display_name,
                  founded_year=excluded.founded_year,
                  notes=excluded.notes
            """
        else:
            sql = """
                INSERT OR IGNORE INTO mints
                  (id, country, mark, city, display_name, founded_year, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """

        with conn:
            conn.executemany(sql, SEED)

        post = {row[0] for row in conn.execute("SELECT id FROM mints")}
        inserted = post - existing
        print(f"✅ {action}  inserted={len(inserted)}  total={len(post)}")
        if missing - inserted:
            print(f"   ⚠️  still missing: {sorted(missing - inserted)}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
