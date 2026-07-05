"""Tests pour `ml/scripts/wipe_referential.py` (P.6 du chantier coin-richness).

Tournent sur une copie de la DB courante dans tmp_path, donc zéro risque sur
``ml/state/eurio.db``. Couvre :

* dry_run : lecture-seule, exit 0, n'écrit rien.
* apply --yes : exécute le wipe + recreate, vérifie post-conditions :
  - counts à 0 sur les 10 tables wipées
  - 9 nouvelles tables P.3a intactes (source_registry seedé, mints, …)
  - FK source → source_registry présente sur les 6 tables recréées
  - FK enforced en pratique (INSERT source inconnue → IntegrityError)
  - infra terrain préservée (source_runs, image_assets, training_runs, …)
  - backup auto créé à côté de la DB
* DDL recreate préserve WITHOUT ROWID sur coin_canonical_images.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts import wipe_referential  # noqa: E402


REAL_DB = ML_DIR / "state" / "eurio.db"


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    """Copie la DB courante dans tmp_path. Si elle n'existe pas, skip."""
    if not REAL_DB.exists():
        pytest.skip(f"DB courante introuvable: {REAL_DB}")
    target = tmp_path / "eurio.db"
    shutil.copy2(REAL_DB, target)
    return target


def _has_fk_to_source_registry(conn: sqlite3.Connection, table: str) -> bool:
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return any(r[2] == "source_registry" and r[3] == "source" for r in rows)


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_dry_run_exit_zero_no_write(db_copy: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mtime_before = db_copy.stat().st_mtime
    size_before = db_copy.stat().st_size

    rc = wipe_referential.dry_run(db_copy)

    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out
    assert "à wiper" in out
    assert "Rien n'a été écrit" in out

    assert db_copy.stat().st_mtime == mtime_before
    assert db_copy.stat().st_size == size_before


def test_dry_run_missing_db(tmp_path: Path) -> None:
    missing = tmp_path / "nope.db"
    assert wipe_referential.dry_run(missing) == 1


def test_apply_wipes_and_recreates(db_copy: Path) -> None:
    # Pre: au moins une table wipe-scope a des rows (DB courante a 15k+).
    with sqlite3.connect(db_copy) as conn:
        assert _count(conn, "coins") > 0
        assert _count(conn, "coin_observations") > 0
        # source_registry seedé au bootstrap (≥ 10 sources canoniques ; le
        # nombre exact évolue quand on ajoute une source — ne pas hardcoder).
        n_sources = _count(conn, "source_registry")
        assert n_sources >= 10

    rc = wipe_referential.apply(db_copy, skip_confirm=True)
    assert rc == 0

    # Post : 10 tables wipées à 0
    with sqlite3.connect(db_copy) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        for t in wipe_referential.WIPE_TABLES:
            assert _count(conn, t) == 0, f"{t} not empty"

        # source_registry préservé (invariant : inchangé par le wipe)
        assert _count(conn, "source_registry") == n_sources

        # FK source enforced sur les 6 tables recréées
        for t in wipe_referential.RECREATE_TABLES:
            assert _has_fk_to_source_registry(conn, t), f"{t} missing FK source"

        # integrity OK ; FK : les seuls orphelins tolérés sont les enfants de
        # tables WIPÉES (transitoires — redeviennent valides au refetch qui
        # réinsère les mêmes eurio_id). Un orphelin pointant une table PRÉSERVÉE
        # serait une vraie corruption. C'est l'invariant que _post_checks code.
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        wiped = set(wipe_referential.WIPE_TABLES)
        unexpected = [
            v for v in conn.execute("PRAGMA foreign_key_check").fetchall()
            if v[2] not in wiped
        ]
        assert unexpected == [], f"orphelins inattendus (parent non-wipé): {unexpected}"


def test_apply_fk_enforced_post_wipe(db_copy: Path) -> None:
    wipe_referential.apply(db_copy, skip_confirm=True)

    with sqlite3.connect(db_copy) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        # Need a parent coin row (FK eurio_id → coins).
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative) "
            "VALUES ('__test__', 'eu', 1999, 2.0, 1)"
        )

        # Valid source OK.
        conn.execute(
            "INSERT INTO coin_observations (eurio_id, source, observation_type, payload_json) "
            "VALUES ('__test__', 'numista_api', 'test', '{}')"
        )

        # Unknown source → FK violation.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO coin_observations (eurio_id, source, observation_type, payload_json) "
                "VALUES ('__test__', 'atlantis_xyz', 'test', '{}')"
            )
        conn.rollback()


def test_apply_preserves_infra(db_copy: Path) -> None:
    """L'infra terrain (source_runs, image_assets, training_*, eurio_id_migrations,
    et les 9 nouvelles tables P.3a) ne doit pas être touchée par le wipe."""
    preserved_tables = [
        "source_runs",
        "source_images",
        "image_assets",
        "review_queue",
        "eurio_id_migrations",
        "source_registry",
        "mints",
        "coin_variants",
        "coin_mint_releases",
        "coin_source_refs",
        "mint_release_prices",
        "mint_release_observations",
        "coin_credits",
        "coin_edge_variants",
        # Enrichissement FK→coins (ON DELETE CASCADE) — l'ancien wipe les
        # détruisait silencieusement, ils doivent désormais survivre (F05 #1).
        "coin_descriptions_i18n",
        "coin_topics",
        "coin_source_status",
        "wikipedia_nl_coins",
    ]
    with sqlite3.connect(db_copy) as conn:
        before = {t: _count(conn, t) for t in preserved_tables}

    wipe_referential.apply(db_copy, skip_confirm=True)

    with sqlite3.connect(db_copy) as conn:
        after = {t: _count(conn, t) for t in preserved_tables}

    assert before == after, f"infra wipée par erreur: before={before} after={after}"


def test_apply_creates_auto_backup(db_copy: Path) -> None:
    wipe_referential.apply(db_copy, skip_confirm=True)

    backups = list(db_copy.parent.glob("eurio.db.bak-pre-wipe-*"))
    assert len(backups) == 1, f"expected 1 auto-backup, got {len(backups)}"
    assert backups[0].stat().st_size > 0


def test_recreate_preserves_without_rowid(db_copy: Path) -> None:
    wipe_referential.apply(db_copy, skip_confirm=True)
    with sqlite3.connect(db_copy) as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='coin_canonical_images'"
        ).fetchone()[0]
        assert "WITHOUT ROWID" in sql.upper()


def test_apply_refused_confirmation_no_changes(
    db_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "no thanks")

    with sqlite3.connect(db_copy) as conn:
        before = _count(conn, "coins")
    assert before > 0

    rc = wipe_referential.apply(db_copy, skip_confirm=False)
    assert rc == 1

    with sqlite3.connect(db_copy) as conn:
        assert _count(conn, "coins") == before
