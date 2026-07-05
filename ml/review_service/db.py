"""Connexion review.db (SQLite WAL) — même esprit que ml/store/connection.py.

Single-writer / multi-reader via WAL + busy_timeout. Le volume d'écritures
review est minuscule (un clic toutes les ~10-30 s par reviewer) → SQLite tient
largement N reviewers concurrents. cf. 01-architecture.md §"Concurrence SQLite".
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Local-dev default ; sur le VPS, pointer via REVIEW_DB_PATH (cf. 09-vps-deploy).
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "state" / "review.db"


def now_iso() -> str:
    """UTC ISO-8601 suffixe Z (tri lexicographique cohérent, cf. _now_iso review)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class ReviewDB:
    """Wrapper minimal autour de review.db (connexions par thread + write lock)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = os.environ.get("REVIEW_DB_PATH", str(_DEFAULT_DB_PATH))
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._local = threading.local()
        self._bootstrap()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit ; transactions explicites via writing()
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")  # writer/writer : attendre, pas planter
            self._local.conn = conn
        return conn

    def _bootstrap(self) -> None:
        schema = _SCHEMA_PATH.read_text()
        with self._write_lock:
            self.connection().executescript(schema)

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        """Transaction atomique (BEGIN IMMEDIATE → COMMIT/ROLLBACK)."""
        with self._write_lock:
            conn = self.connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                # ROLLBACK défensif : si le call-site a déjà rollback (ou n'a pas de
                # transaction active), ne pas masquer l'exception d'origine par une
                # OperationalError "no transaction is active".
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise
