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
    """Dépendance FastAPI : sqlite3.Row + foreign_keys ON, fermée en finally."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
