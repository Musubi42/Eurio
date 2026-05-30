"""Tests pour les migrations du chantier ebay-multi-marketplace.

Couvre :
- B1 — bootstrap DB neuve → colonnes `marketplace`, table
  `coin_names_i18n`, index partiels.
- C1 — bootstrap → colonnes du pipeline prix (`listing_origin_date`,
  `sold_qty` sur source_images ; `listing_kind`, `condition_normalized`
  + confidences sur listing_text_signals), CHECK sur `listing_kind`.
- Bootstrap sur DB existante (double-instanciation Store) → idempotent,
  aucune erreur "duplicate column", données préexistantes intactes.
- Insertion d'une row source_images avec marketplace NULL → OK
  (backward-compat avec runs pré-bascule).
- Insertion avec marketplace renseigné → OK, lecture cohérente.

Cf. docs/sources-refacto/ebay-multi-marketplace/.
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
    # `confidence` + `model` ajoutées au chunk I1 (scrape Numista + LLM).
    # `method` ajoutée au chunk P.3b (split source/method, doctrine provenance).
    assert cols == {
        "eurio_id", "lang", "title", "source", "method", "fetched_at",
        "confidence", "model",
    }
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


# ── C1 — pipeline prix : taxonomie listing + état ───────────────────────────

_PRICING_SOURCE_IMAGE_COLS = {"listing_origin_date", "sold_qty"}
_PRICING_TEXT_SIGNAL_COLS = {
    "listing_kind", "listing_kind_confidence",
    "condition_normalized", "condition_confidence",
}


def test_fresh_bootstrap_has_pricing_columns(tmp_path: Path) -> None:
    store = Store(tmp_path / "fresh.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row

    assert _PRICING_SOURCE_IMAGE_COLS <= _columns(conn, "source_images")
    assert _PRICING_TEXT_SIGNAL_COLS <= _columns(conn, "listing_text_signals")


def test_pricing_columns_added_on_existing_db(tmp_path: Path) -> None:
    """DB antérieure au chunk C1 → colonnes ajoutées, row préexistante intacte."""
    db = tmp_path / "preserve.db"
    Store(db)

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, storage_path) "
        "VALUES (?, ?, ?, ?)",
        ("img-c1", "ebay", "ebay_999_img0", "/tmp/fake.jpg"),
    )
    conn.commit()
    conn.close()

    Store(db)  # rebootstrap → migration C1

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    assert _PRICING_SOURCE_IMAGE_COLS <= _columns(conn, "source_images")
    assert _PRICING_TEXT_SIGNAL_COLS <= _columns(conn, "listing_text_signals")
    row = conn.execute(
        "SELECT source_ref, listing_origin_date, sold_qty "
        "FROM source_images WHERE id = ?",
        ("img-c1",),
    ).fetchone()
    assert row["source_ref"] == "ebay_999_img0"
    assert row["listing_origin_date"] is None  # NULL sur les rows pré-C1
    assert row["sold_qty"] is None


def test_listing_kind_check_constraint(tmp_path: Path) -> None:
    """`listing_kind` n'accepte que single/lot/coffret/graded_slab (ou NULL)."""
    store = Store(tmp_path / "check.db")
    conn = sqlite3.connect(store.db_path)

    def _insert(sid: str, kind: str | None) -> None:
        conn.execute(
            "INSERT INTO listing_text_signals "
            "(source_image_id, coverage, listing_kind) VALUES (?, 'empty', ?)",
            (sid, kind),
        )

    for i, kind in enumerate(("single", "lot", "coffret", "graded_slab", None)):
        _insert(f"ok-{i}", kind)  # valeurs valides + NULL → OK
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        _insert("bad", "boxed")  # hors CHECK


# ── coin_source_status — disponibilité par source ───────────────────────────

REAL_DB = Path(__file__).resolve().parents[1] / "state" / "eurio.db"

_SOURCE_STATUS_COLS = {
    "eurio_id", "source", "state", "detail_json",
    "last_run_id", "last_checked_at", "updated_at",
}


def test_fresh_bootstrap_has_coin_source_status(tmp_path: Path) -> None:
    store = Store(tmp_path / "fresh.db")
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    assert _columns(conn, "coin_source_status") == _SOURCE_STATUS_COLS
    assert "idx_coin_source_status_source_state" in _indexes(conn, "coin_source_status")


def test_coin_source_status_state_check_constraint(tmp_path: Path) -> None:
    """`state` n'accepte que never/ok/empty_upstream/error."""
    store = Store(tmp_path / "chk.db")
    conn = sqlite3.connect(store.db_path)
    for st in ("never", "ok", "empty_upstream", "error"):
        conn.execute(
            "INSERT INTO coin_source_status (eurio_id, source, state) VALUES (?, ?, ?)",
            (f"c-{st}", "numista_api", st),  # FK off par défaut sur conn brute
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO coin_source_status (eurio_id, source, state) VALUES (?, ?, ?)",
            ("c-bad", "numista_api", "bogus"),
        )


def test_coin_source_status_fks_enforced(tmp_path: Path) -> None:
    """Avec foreign_keys=ON : source hors registry et coin inexistant rejetés."""
    store = Store(tmp_path / "fk.db")
    conn = sqlite3.connect(store.db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, currency, is_commemorative) "
        "VALUES ('c1', 'eu', 2025, 2.0, 'EUR', 1)"
    )
    conn.execute(
        "INSERT INTO source_registry (id, display_name, kind) "
        "VALUES ('numista_api', 'Numista', 'reference')"
    )
    conn.commit()
    # valide
    conn.execute("INSERT INTO coin_source_status (eurio_id, source, state) "
                 "VALUES ('c1', 'numista_api', 'ok')")
    # source hors registry
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO coin_source_status (eurio_id, source, state) "
                     "VALUES ('c1', 'bogus_source', 'ok')")
    # coin inexistant
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO coin_source_status (eurio_id, source, state) "
                     "VALUES ('nope', 'numista_api', 'ok')")


def test_coin_source_status_survives_rebootstrap(tmp_path: Path) -> None:
    """Un verdict réseau (empty_upstream) survit au rebootstrap idempotent."""
    db = tmp_path / "preserve_css.db"
    Store(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO coin_source_status (eurio_id, source, state, detail_json) "
        "VALUES ('c1', 'bce_official', 'empty_upstream', '{}')"
    )
    conn.commit()
    conn.close()
    Store(db)  # rebootstrap
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT state FROM coin_source_status WHERE eurio_id='c1'"
    ).fetchone()
    assert row["state"] == "empty_upstream"


def test_coin_source_status_migration_on_populated_db(tmp_path: Path) -> None:
    """Migration sur une copie de l'eurio.db RÉELLE peuplée : la table
    apparaît sans toucher les données existantes (exigence user)."""
    if not REAL_DB.exists():
        pytest.skip(f"eurio.db absent: {REAL_DB}")
    import shutil
    target = tmp_path / "populated.db"
    shutil.copy2(REAL_DB, target)
    conn = sqlite3.connect(target)
    before = conn.execute("SELECT count(*) FROM coins").fetchone()[0]
    conn.close()

    Store(target)  # applique la migration sur DB peuplée

    conn = sqlite3.connect(target)
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE name='coin_source_status'"
    ).fetchone() is not None
    assert conn.execute("SELECT count(*) FROM coins").fetchone()[0] == before
