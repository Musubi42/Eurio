"""Dépendances FastAPI partagées par les routers `layered`.

Pattern : un seul `db_connection()` au lieu d'ouvrir une connexion sqlite3
dans chaque route. Yield + close en finally — propre vis-à-vis des erreurs.

Cf. docs/work-in-progress/data-layer-unification/ARCHITECTURE.md §3.1.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


def db_connection() -> Iterator[sqlite3.Connection]:
    """Dépendance FastAPI : sqlite3.Row + foreign_keys ON, fermée en finally.

    ``check_same_thread=False`` est OBLIGATOIRE ici, et ce n'est pas un
    relâchement : FastAPI exécute une dépendance génératrice SYNCHRONE dans un
    worker du threadpool (``contextmanager_in_threadpool``) puis la route dans un
    AUTRE worker (``run_in_threadpool``). La connexion est donc créée dans un
    thread et utilisée dans un second — ce que sqlite3 refuse par défaut.

    La sécurité n'en souffre pas : cette connexion est ouverte POUR UNE REQUÊTE et
    fermée en ``finally``. Les deux threads ne s'en servent jamais en même temps,
    ils se la passent.

    Sans ce drapeau, la panne est INTERMITTENTE et MUETTE : anyio réutilise
    souvent le même worker quand le serveur est au repos (donc ça « marche » en
    test séquentiel), et casse dès que deux requêtes se croisent — ce que fait le
    navigateur à chaque chargement de la review. Le front reste alors sur
    « chargement de la suite… » sans une ligne en console, et le 500 ne vit que
    dans les logs serveur. Observé le 2026-08-23 (review-collaborative-v2, lot 1b).
    """
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
