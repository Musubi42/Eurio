"""Migration runner SQLite — idempotent, ordonné lexicographiquement.

Cf. DESIGN.md §4 (auth-redesign C2). Appelé par le startup hook FastAPI dans
``server_serve.py``. Pattern minimal :

* Table ``_schema_migrations(filename TEXT PRIMARY KEY, applied_at INTEGER)``
* Pour chaque ``migrations/*.sql`` dans l'ordre lex :
  * skip si déjà appliqué (présent dans ``_schema_migrations``) ;
  * sinon ``executescript()`` dans une transaction, puis insert dans la table.
* Pas de rollback automatique en cas d'échec partiel — c'est SQLite, on log et
  on crash. L'opérateur reprend la main en lisant les logs.

On ne supporte pas les "down migrations" : si une migration foire en prod, on
écrit une nouvelle migration corrective. C'est la philosophie standard.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

_LOG = logging.getLogger("eurio-api.db_migrate")
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def run_migrations(db_path: Path | str) -> list[str]:
    """Applique les migrations pendantes. Retourne la liste des fichiers appliqués."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _schema_migrations ("
            "filename TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)"
        )
        conn.commit()
        applied = {
            r["filename"]
            for r in conn.execute("SELECT filename FROM _schema_migrations")
        }
        pending = sorted(
            f for f in _MIGRATIONS_DIR.glob("*.sql") if f.name not in applied
        )
        ran: list[str] = []
        for f in pending:
            sql = f.read_text(encoding="utf-8")
            _LOG.info("db_migrate: applying %s (%d bytes)", f.name, len(sql))
            try:
                conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
            except Exception:
                _LOG.exception("db_migrate: FAILED on %s — abort", f.name)
                conn.rollback()
                raise
            conn.execute(
                "INSERT INTO _schema_migrations(filename, applied_at) VALUES (?, ?)",
                (f.name, int(time.time() * 1000)),
            )
            conn.commit()
            ran.append(f.name)
        if not ran:
            _LOG.info("db_migrate: no pending migration (%d already applied)", len(applied))
        return ran
    finally:
        conn.close()
