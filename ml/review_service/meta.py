"""Accès à la table clé/valeur `meta` de review.db.

Sert aujourd'hui à mémoriser `last_publish_at` / `last_reconcile_at`, tamponnés
par les endpoints admin et lus par le bloc « flux » de la page régie.
cf. docs/work-in-progress/collaborative-review/10-admin-dashboard.md
"""

from __future__ import annotations

import sqlite3

from review_service.db import ReviewDB

LAST_PUBLISH_AT = "last_publish_at"
LAST_RECONCILE_AT = "last_reconcile_at"


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """UPSERT — à appeler depuis une transaction `writing()` existante."""
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(db: ReviewDB, key: str) -> str | None:
    row = db.connection().execute(
        "SELECT value FROM meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row is not None else None
