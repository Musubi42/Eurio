"""Données de seed canoniques de ``source_registry`` — source unique de vérité.

Importé À LA FOIS par le CLI (``scripts/seed_source_registry.py``) et par le
bootstrap du Store (``store/connection.py``), pour qu'une DB fraîche soit
utilisable **sans rite de seed manuel**. La FK ``coin_source_refs.source →
source_registry(id)`` (schema.sql, ``ON DELETE RESTRICT``) est enforced dès le
premier run touchant ``price_aggregate`` : sans ce seed au bootstrap, toute DB
neuve (nouvelle machine, restore désastre, CI) crashe en ``IntegrityError``
opaque. Le seed est idempotent (``INSERT OR IGNORE`` sur la PK ``id``).

Ne dépend de rien d'autre que d'une connexion sqlite3 (pas d'import ``Store``)
pour rester importable depuis ``connection.py`` sans cycle.
"""

from __future__ import annotations

import sqlite3

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

_INSERT_IGNORE = (
    "INSERT OR IGNORE INTO source_registry (id, display_name, kind, base_url, notes) "
    "VALUES (?, ?, ?, ?, ?)"
)


def seed_source_registry(conn: sqlite3.Connection) -> int:
    """Insère les sources canoniques manquantes (idempotent). Retourne le
    nombre de rows ajoutées. Ne touche jamais une row existante (``INSERT OR
    IGNORE``) — sûr à appeler à chaque bootstrap."""
    before = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0]
    conn.executemany(_INSERT_IGNORE, SEED)
    after = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0]
    return after - before
