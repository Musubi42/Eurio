"""Charger le VRAI ``state/schema.sql`` dans une base de test.

Pourquoi ce helper existe : les fixtures DDL recopiées à la main ont menti
deux fois de suite dans ce chantier. ``dino_class_references`` y était déclarée
à **3 colonnes sur 11** (défaut D1), et ``image_asset_dino_predictions`` y
porte encore deux colonnes permutées (défaut M5). Une fixture est son propre
référentiel : la divergence est invisible aux tests **par construction**.

M1 a été trouvé en rejouant la sonde sur le DDL réel, et il n'était pas
exprimable sur la fixture (elle fabriquait un ``asset_id`` par encodeur, un
monde que le pipeline ne produit pas — les deux encodeurs piochent dans le même
pool de crops validés). D'où la règle : **tout test qui raisonne sur une clé,
un index ou une contrainte se pose sur le DDL réel**, pas sur une copie.

⚠️ ``schema.sql`` n'est pas le schéma du canonique à la colonne près
(FINDINGS §6.4 : ~30 colonnes n'existent que via les ``_ensure_column`` de
``store/connection.py``). Il **est** en revanche la source de vérité pour les
tables et les clés qu'il déclare — dont ``dino_class_references``.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ML_DIR / "state" / "schema.sql"
MIGRATIONS_DIR = ML_DIR / "serving" / "migrations"


def lit_schema_reel() -> str:
    """Le texte de ``ml/state/schema.sql``."""
    return SCHEMA_SQL.read_text(encoding="utf-8")


def base_au_schema_reel(chemin: Path) -> sqlite3.Connection:
    """Base neuve avec le VRAI schéma rejoué, FK activées comme le fait Store.

    ``store/connection.py:131`` pose ``PRAGMA foreign_keys=ON`` — une sonde qui
    ne le pose pas ne verrait pas les violations que la vraie connexion voit.
    """
    conn = sqlite3.connect(str(chemin))
    conn.row_factory = sqlite3.Row
    conn.executescript(lit_schema_reel())
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ddl_table_reelle(nom: str, sql: str | None = None) -> str:
    """Le bloc ``CREATE TABLE … (…);`` de ``nom``, tel qu'écrit dans schema.sql.

    Extrait par comptage de parenthèses (et non par regex gloutonne) : les
    ``CHECK (…)`` et ``DEFAULT (datetime('now'))`` internes en contiennent.
    Sert aux tests qui doivent fabriquer une variante du DDL réel — par
    exemple la forme ANTÉRIEURE à une migration — sans retaper les colonnes.
    """
    texte = sql if sql is not None else lit_schema_reel()
    motif = re.compile(
        rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{re.escape(nom)}\s*\(",
        re.IGNORECASE,
    )
    m = motif.search(texte)
    if m is None:
        raise AssertionError(f"table {nom} absente de {SCHEMA_SQL}")
    profondeur = 0
    for i in range(m.end() - 1, len(texte)):
        if texte[i] == "(":
            profondeur += 1
        elif texte[i] == ")":
            profondeur -= 1
            if profondeur == 0:
                fin = texte.index(";", i) + 1
                return texte[m.start():fin]
    raise AssertionError(f"parenthèse non refermée pour {nom} dans {SCHEMA_SQL}")


def normalise_ddl(sql: str) -> str:
    """Commentaires et blancs écrasés : c'est la STRUCTURE qu'on compare.

    Même normalisation que ``tests/test_schema_mirror.py`` — deux DDL qui ne
    diffèrent que par la mise en page sont le même DDL.
    """
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", " ", sql)).strip().lower()


def applique_migration(conn: sqlite3.Connection, nom_fichier: str) -> None:
    """Rejoue une migration comme le fait ``serving/db_migrate.run_migrations``.

    Même enveloppe transactionnelle (``BEGIN`` … ``COMMIT`` autour du script) :
    une migration qui ne passerait que hors transaction serait un faux vert.
    """
    sql = (MIGRATIONS_DIR / nom_fichier).read_text(encoding="utf-8")
    conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
