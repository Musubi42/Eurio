"""Helpers partagés sur un coin : image de base (avers) + titre FR par défaut.

Factorisés ici (R0, anti-duplication) pour être réutilisés par
``bench_routes`` (contexte de jugement) et l'endpoint hover-card de la matrice
de couverture (``coins_routes``).
"""

from __future__ import annotations

import sqlite3


def canonical_obverse_url(conn: sqlite3.Connection, eurio_id: str) -> str | None:
    """URL servable de l'avers via ``coin_canonical_images``.

    Préfère l'URL Numista externe (chargeable directement par l'admin), puis
    BCE. Fallback : endpoint local ``/referential/canonical/{id}/obverse`` qui
    sert le WebP quand l'externe manque."""
    row = conn.execute(
        """
        SELECT source, url, local_path FROM coin_canonical_images
         WHERE eurio_id = ? AND role = 'obverse'
         ORDER BY CASE source
                    WHEN 'numista_api'  THEN 1
                    WHEN 'bce_official' THEN 2
                    ELSE 9 END
         LIMIT 1
        """,
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    if row["url"]:
        return row["url"]
    if row["local_path"]:
        return f"/referential/canonical/{eurio_id}/obverse?source={row['source']}"
    return None


def fr_title(conn: sqlite3.Connection, eurio_id: str) -> str | None:
    """Titre FR par défaut d'un coin (même résolution que la fiche CoinDetails).

    Chaîne : topic verbeux Numista FR → titre court i18n FR → titre BCE FR."""
    row = conn.execute(
        "SELECT topic FROM coin_topics "
        "WHERE eurio_id = ? AND source = 'numista_api' AND lang = 'fr' LIMIT 1",
        (eurio_id,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    row = conn.execute(
        "SELECT title FROM coin_names_i18n WHERE eurio_id = ? AND lang = 'fr' LIMIT 1",
        (eurio_id,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    row = conn.execute(
        "SELECT title FROM coin_descriptions_i18n "
        "WHERE eurio_id = ? AND lang = 'fr' LIMIT 1",
        (eurio_id,),
    ).fetchone()
    return row[0] if row and row[0] else None
