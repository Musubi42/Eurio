"""Tests pour les migrations B1 du chantier ebay-multi-marketplace.

Couvre :
- Bootstrap sur DB neuve → colonnes `marketplace` présentes sur
  source_images / discovery_searches / discarded_listings, table
  `coin_names_i18n` créée, index partiels présents.
- Bootstrap sur DB existante (double-instanciation Store) → idempotent,
  aucune erreur "duplicate column", données préexistantes intactes.
- Insertion d'une row source_images avec marketplace NULL → OK
  (backward-compat avec runs pré-bascule).
- Insertion avec marketplace renseigné → OK, lecture cohérente.

Cf. docs/sources-refacto/ebay-multi-marketplace/rollout.md chunk B1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from state.store import Store


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA index_list({table})")}


def test_fresh_bootstrap_has_marketplace_columns(tmp_path: Path) -> None:
    store = Store(tmp_path / "fresh.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row

    assert "marketplace" in _columns(conn, "source_images")
    assert "marketplace_found_json" in _columns(conn, "source_images")
    assert "marketplace" in _columns(conn, "discovery_searches")
    assert "marketplace" in _columns(conn, "discarded_listings")


def test_fresh_bootstrap_has_marketplace_indexes(tmp_path: Path) -> None:
    store = Store(tmp_path / "fresh.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row

    assert "idx_source_images_marketplace" in _indexes(conn, "source_images")
    assert "idx_discovery_searches_marketplace" in _indexes(conn, "discovery_searches")
    assert "idx_discarded_listings_marketplace" in _indexes(conn, "discarded_listings")


def test_fresh_bootstrap_has_coin_names_i18n(tmp_path: Path) -> None:
    store = Store(tmp_path / "fresh.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row

    cols = _columns(conn, "coin_names_i18n")
    assert cols == {"eurio_id", "lang", "title", "source", "fetched_at"}
    assert "idx_coin_names_i18n_lang" in _indexes(conn, "coin_names_i18n")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO coin_names_i18n (eurio_id, lang, title) VALUES (?, ?, ?)",
            ("fake-coin", "xx", "Titre"),  # lang hors CHECK
        )


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    """Double instanciation Store sur la même DB ne lève pas d'erreur."""
    db = tmp_path / "twice.db"
    Store(db)
    Store(db)  # doit être no-op, pas de "duplicate column"


def test_existing_data_survives_rebootstrap(tmp_path: Path) -> None:
    """Une row source_images insérée avant rebootstrap reste lisible après."""
    db = tmp_path / "preserve.db"
    Store(db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        INSERT INTO source_images (id, source, source_ref, storage_path)
        VALUES (?, ?, ?, ?)
        """,
        ("img-1", "ebay", "ebay_123_img0", "/tmp/fake.jpg"),
    )
    conn.commit()
    conn.close()

    Store(db)  # rebootstrap

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, source_ref, marketplace, marketplace_found_json "
        "FROM source_images WHERE id = ?",
        ("img-1",),
    ).fetchone()
    assert row is not None
    assert row["source_ref"] == "ebay_123_img0"
    assert row["marketplace"] is None
    assert row["marketplace_found_json"] is None


def test_insert_with_marketplace_roundtrips(tmp_path: Path) -> None:
    db = tmp_path / "insert.db"
    Store(db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, storage_path,
          marketplace, marketplace_found_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "img-2",
            "ebay",
            "ebay_456_img0",
            "/tmp/fake2.jpg",
            "EBAY_DE",
            '["EBAY_DE","EBAY_GB"]',
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT marketplace, marketplace_found_json FROM source_images WHERE id = ?",
        ("img-2",),
    ).fetchone()
    assert row["marketplace"] == "EBAY_DE"
    assert row["marketplace_found_json"] == '["EBAY_DE","EBAY_GB"]'
