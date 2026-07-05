"""C3 (F02) — zone_resolver lit ``coin_confusion_map`` depuis eurio.db (SQLite),
plus depuis Supabase. Vérifie : lecture réelle, table absente → défaut orange,
DB absente → défaut orange, et absence totale de dépendance Supabase à l'import.
"""

from __future__ import annotations

import sqlite3

import pytest

from training.zone_resolver import fetch_eurio_zones


def _make_confusion_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE coin_confusion_map (
          eurio_id TEXT NOT NULL,
          zone TEXT NOT NULL,
          nearest_similarity REAL
        )
        """
    )
    conn.executemany(
        "INSERT INTO coin_confusion_map (eurio_id, zone) VALUES (?, ?)", rows
    )
    conn.commit()
    conn.close()


def test_reads_zones_from_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "eurio.db"
    _make_confusion_db(
        db,
        [
            ("eu-fr-2euro-2002", "red"),
            ("eu-de-2euro-2002", "green"),
            ("eu-it-2euro-2002", "bogus"),  # zone invalide → ignorée
        ],
    )
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    # Aucune var Supabase dans l'env : ne doit pas warn ni échouer.
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    zones = fetch_eurio_zones()

    assert zones == {"eu-fr-2euro-2002": "red", "eu-de-2euro-2002": "green"}


def test_missing_table_defaults_empty(tmp_path, monkeypatch, capsys):
    db = tmp_path / "eurio.db"
    sqlite3.connect(str(db)).close()  # DB sans la table
    monkeypatch.setenv("EURIO_DB_PATH", str(db))

    zones = fetch_eurio_zones()

    assert zones == {}
    assert "coin_confusion_map absente" in capsys.readouterr().out


def test_missing_db_defaults_empty(tmp_path, monkeypatch, capsys):
    db = tmp_path / "does-not-exist.db"
    monkeypatch.setenv("EURIO_DB_PATH", str(db))

    zones = fetch_eurio_zones()

    assert zones == {}
    assert "introuvable" in capsys.readouterr().out


def test_no_supabase_client_in_module():
    """Le module ne doit plus instancier de client Supabase (F02/C3) — seule une
    mention en docstring (contexte historique) reste tolérée."""
    import training.zone_resolver as zr

    src = __import__("inspect").getsource(zr)
    assert "SupabaseClient" not in src
    assert "serving.supabase_client" not in src
    assert not hasattr(zr, "_make_supabase_client")
