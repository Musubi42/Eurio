"""Reaper PID-aware des source_runs orphelins.

Régression du bug « le scrape eBay n'arrête pas de planter » : ``reset_orphan_runs``
(hook startup FastAPI, déclenché à chaque reload uvicorn ``--reload``) marquait
TOUT run ``status='running'`` comme ``failed`` — tuant un scrape foreground bien
vivant. Désormais il ne reape que les runs dont le ``pid`` est mort (ou NULL=legacy).

Run: `.venv/bin/python -m pytest ml/tests/test_orphan_runs.py -q`
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from serving.sources_routes import reset_orphan_runs  # noqa: E402
from store import Store  # noqa: E402

_DEAD_PID = 2_000_000_000  # quasi-certainement pas un process vivant


def _run(conn, run_id, pid, status="running"):
    conn.execute(
        "INSERT INTO source_runs (id, source, kind, started_at, status, pid) "
        "VALUES (?, 'ebay', 'run', datetime('now'), ?, ?)",
        (run_id, status, pid),
    )


def test_live_run_is_not_reaped(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _run(conn, "live", os.getpid())     # pid vivant (ce process)
    _run(conn, "dead", _DEAD_PID)        # pid mort
    _run(conn, "legacy", None)           # pas de pid (legacy)
    conn.commit()

    n = reset_orphan_runs(store)
    assert n == 2  # dead + legacy reapés, live préservé

    rows = dict(conn.execute("SELECT id, status FROM source_runs").fetchall())
    assert rows["live"] == "running"     # LE fix : run vivant intact
    assert rows["dead"] == "failed"
    assert rows["legacy"] == "failed"


def test_no_running_runs_is_noop(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _run(conn, "done", os.getpid(), status="success")
    conn.commit()
    assert reset_orphan_runs(store) == 0
    assert conn.execute("SELECT status FROM source_runs WHERE id='done'").fetchone()[0] == "success"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
