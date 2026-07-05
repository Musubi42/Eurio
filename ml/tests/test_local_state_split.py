"""C6 — split local-state : resolver DB locale inscriptible + staging scratch.

Vérifie que ``resolve_local_state_db`` ne pointe jamais la réplique, et que
``staging_store`` ouvre un scratch INSCRIPTIBLE distinct du cache autopull même
sous ``EURIO_DB_READONLY=1`` (prérequis du flip : stager-avant-push ne doit pas
throw ni courir avec le thread de pull).
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import resolve_local_state_db, staging_store


def test_local_state_db_never_replica(monkeypatch):
    monkeypatch.delenv("EURIO_LOCAL_STATE_DB", raising=False)
    p = resolve_local_state_db()
    assert p.name == "eurio.local.db"
    assert p.name != "eurio.replica.db"


def test_local_state_db_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("EURIO_LOCAL_STATE_DB", str(tmp_path / "custom.db"))
    assert resolve_local_state_db() == tmp_path / "custom.db"


def test_staging_store_is_writable_scratch_under_readonly(monkeypatch, tmp_path):
    # Simule le flip : réplique ro pointée par l'env. Le scratch de staging doit
    # rester INSCRIPTIBLE (read_only=False explicite) et distinct de la réplique.
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    monkeypatch.setenv("EURIO_DB_PATH", str(tmp_path / "eurio.replica.db"))

    # pull_replica est mocké : copie une DB sqlite valide vers le scratch demandé.
    import sqlite3

    import client.replica as replica

    seed = tmp_path / "seed.db"
    sqlite3.connect(str(seed)).close()  # fichier sqlite valide (vide)

    def _fake_pull(dest=None, **kw):
        import shutil
        shutil.copy2(seed, dest)
        return dest

    monkeypatch.setattr(replica, "pull_replica", _fake_pull)

    store = staging_store(prefix="test-staging-")
    assert store.db_path.name == "eurio_scratch.db"
    assert "eurio.replica.db" not in str(store.db_path)
    # inscriptible malgré EURIO_DB_READONLY=1 (read_only=False explicite)
    conn = store._connection()  # noqa: SLF001
    conn.execute("CREATE TABLE _probe (x)")
    conn.execute("INSERT INTO _probe VALUES (1)")
    assert conn.execute("SELECT COUNT(*) FROM _probe").fetchone()[0] == 1
