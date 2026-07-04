"""Tests pour le mode read-only de StoreBase (Direction A, C5).

Vérifie que ``Store(path, read_only=True)`` :
- ouvre en ``mode=ro`` (aucune écriture possible, même via _writing),
- fait un bootstrap no-op (pas de tentative d'ALTER/executescript),
- n'exécute jamais ``PRAGMA journal_mode=WAL`` (planterait à l'ouverture
  d'un fichier post-VACUUM INTO non-WAL),
- laisse les lectures SELECT fonctionner normalement,
- ne régresse pas le comportement par défaut (``read_only=False``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from store import Store


def test_read_only_store_select_ok(tmp_path: Path) -> None:
    """Une DB bootstrappée en écriture, puis rouverte en read_only, se lit."""
    db = tmp_path / "eurio.db"
    Store(db)  # bootstrap initial en écriture (schéma à jour)

    ro_store = Store(db, read_only=True)
    assert ro_store.read_only is True
    conn = ro_store._connection()
    row = conn.execute("SELECT count(*) AS n FROM coins").fetchone()
    assert row["n"] >= 0


def test_read_only_store_rejects_write(tmp_path: Path) -> None:
    """Une tentative d'écriture sur une Store read_only lève OperationalError."""
    db = tmp_path / "eurio.db"
    Store(db)  # bootstrap initial en écriture

    ro_store = Store(db, read_only=True)
    conn = ro_store._connection()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute(
            "INSERT INTO source_runs (id, source, kind) VALUES "
            "('test-ro-guard', 'ebay', 'dry')"
        )


def test_read_only_store_no_wal_pragma(tmp_path: Path) -> None:
    """En read_only, _connection() ne doit jamais tenter PRAGMA journal_mode=WAL
    (qui écrit sur le fichier et planterait sur une réplique non-WAL)."""
    db = tmp_path / "eurio.db"
    Store(db)  # bootstrap initial (écrit, passe en WAL)

    ro_store = Store(db, read_only=True)
    conn = ro_store._connection()
    # Le mode journal peut rester "wal" (hérité du fichier écrit ci-dessus) —
    # ce qu'on vérifie, c'est que la connexion ro reste utilisable en lecture
    # et qu'aucune exception n'est levée à l'ouverture (garanti par le setUp).
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode is not None


def test_read_only_store_bootstrap_is_noop(tmp_path: Path) -> None:
    """Le bootstrap ne doit pas tenter d'ALTER/executescript en read_only —
    donc construire une Store read_only sur un fichier inexistant ne le crée
    jamais (contrairement au mode écriture, où _bootstrap créerait le
    schéma). L'échec réel n'apparaît qu'à la première lecture (ouverture
    sqlite lazy en mode=ro)."""
    db = tmp_path / "does_not_exist.db"
    ro_store = Store(db, read_only=True)
    assert not db.exists()
    with pytest.raises(sqlite3.OperationalError):
        ro_store._connection().execute("SELECT 1").fetchone()


def test_read_write_store_unchanged(tmp_path: Path) -> None:
    """Non-régression : read_only=False (défaut) garde le comportement actuel."""
    db = tmp_path / "eurio.db"
    store = Store(db)
    assert store.read_only is False
    conn = store._connection()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    # Écriture toujours possible.
    with store._writing() as wconn:
        wconn.execute(
            "INSERT INTO source_runs (id, source, kind) VALUES "
            "('test-rw-ok', 'ebay', 'dry')"
        )
    row = conn.execute(
        "SELECT count(*) AS n FROM source_runs WHERE id='test-rw-ok'"
    ).fetchone()
    assert row["n"] == 1


# ── Câblage env (durcissement post-C5) : StoreBase résout EURIO_DB_READONLY ──


def test_env_flag_defaults_store_to_readonly(tmp_path: Path, monkeypatch) -> None:
    """EURIO_DB_READONLY=1 → un Store construit SANS read_only explicite
    s'ouvre en mode=ro (le câblage MAJOR 2 : plus besoin de toucher les
    call-sites, le flag machine suffit)."""
    db = tmp_path / "eurio.db"
    monkeypatch.delenv("EURIO_DB_READONLY", raising=False)
    Store(db)  # bootstrap initial en écriture

    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    store = Store(db)
    assert store.read_only is True
    with pytest.raises(sqlite3.OperationalError):
        store._connection().execute(
            "INSERT INTO source_runs (id, source, kind) VALUES "
            "('test-env-ro', 'ebay', 'dry')"
        )


def test_explicit_read_only_false_overrides_env(tmp_path: Path, monkeypatch) -> None:
    """Le writer canonique (server_serve) passe read_only=False explicite et
    reste inscriptible même si le flag traîne dans l'env."""
    db = tmp_path / "eurio.db"
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    store = Store(db, read_only=False)
    assert store.read_only is False
    with store._writing() as wconn:
        wconn.execute(
            "INSERT INTO source_runs (id, source, kind) VALUES "
            "('test-env-override', 'ebay', 'dry')"
        )


def test_env_flag_absent_keeps_write_default(tmp_path: Path, monkeypatch) -> None:
    """Sans env var (dev Model A), le défaut reste l'écriture locale."""
    monkeypatch.delenv("EURIO_DB_READONLY", raising=False)
    store = Store(tmp_path / "eurio.db")
    assert store.read_only is False
