"""ReviewDB — wrapper SQLite WAL pour ``review.db`` (auth-redesign C4).

Port allégé de ``ml/review_service/db.py``, débarrassé du FK ``reviewers``
(les identités viennent désormais d'Authentik via le ``Principal``, pas d'une
table reviewers locale). Schéma identique sinon (review_items / decisions /
meta) pour permettre une migration data ultérieure (C9 ou retrofit).

Path par défaut : ``/var/lib/eurio/review.db`` (volume de eurio-api). Override
via ``REVIEW_DB_PATH``.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_DEFAULT_DB_PATH = Path("/var/lib/eurio/review.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_items (
  id                TEXT PRIMARY KEY,
  image_asset_id    TEXT NOT NULL UNIQUE,
  storage_path      TEXT,
  source            TEXT,
  listing_title     TEXT,
  candidates_json   TEXT,
  target_eurio_id   TEXT,
  dino_top1_json    TEXT,
  priority          INTEGER NOT NULL DEFAULT 100,
  status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'claimed', 'decided', 'skipped')),
  claimed_by        TEXT,                     -- users.id (Authentik sub hashé), pas FK
  claimed_at        TEXT,
  published_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_items_claimable
  ON review_items(status, priority, published_at);
CREATE INDEX IF NOT EXISTS idx_items_claimed_by
  ON review_items(claimed_by) WHERE claimed_by IS NOT NULL;

CREATE TABLE IF NOT EXISTS decisions (
  id                   TEXT PRIMARY KEY,
  review_item_id       TEXT NOT NULL REFERENCES review_items(id),
  reviewer_user_id     TEXT NOT NULL,             -- users.id, plus de FK reviewers
  action               TEXT NOT NULL CHECK (action IN ('accept', 'reject', 'skip')),
  decided_eurio_id     TEXT,
  decided_face         TEXT,
  decided_variant_kind TEXT,
  quality_reason       TEXT,
  notes                TEXT,
  decided_at           TEXT NOT NULL DEFAULT (datetime('now')),
  reconciled_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_unreconciled
  ON decisions(reconciled_at) WHERE reconciled_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_decisions_reviewer
  ON decisions(reviewer_user_id);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ReviewDB:
    """Wrapper minimal (connexion par thread + write lock)."""

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
                isolation_level=None,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _bootstrap(self) -> None:
        with self._write_lock:
            self.connection().executescript(_SCHEMA)

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
