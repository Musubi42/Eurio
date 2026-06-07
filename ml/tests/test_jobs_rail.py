"""Tests du rail `jobs/` générique (refacto-ml ADR D1).

Couvre : cycle de vie (start→pid→progress→finish), désérialisation `params`,
lecture (`job_get`/`job_latest`), reaper boot (PID mort vs vivant vs garde runtime),
et lancement réel d'un subprocess détaché qui clôt son propre job.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

import jobs
from jobs import db, reaper, runner
from state import Store


@pytest.fixture
def conn(tmp_path):
    store = Store(tmp_path / "jobs.db")
    return store._connection()  # noqa: SLF001


def test_lifecycle_start_pid_progress_finish(conn):
    jid = db.job_start(conn, kind="training", n_total=10,
                       params={"run_id": "r1", "cohort_id": "co1"})
    row = db.job_get(conn, jid)
    assert row is not None
    assert row["kind"] == "training"
    assert row["status"] == "running"
    assert row["n_total"] == 10
    assert row["params"] == {"run_id": "r1", "cohort_id": "co1"}  # désérialisé

    db.job_set_pid(conn, jid, 4242)
    db.job_progress(conn, jid, n_done=4)
    assert db.job_get(conn, jid)["n_done"] == 4

    db.job_finish(conn, jid, status="done", n_done=10, note="ok")
    done = db.job_get(conn, jid)
    assert done["status"] == "done"
    assert done["n_done"] == 10
    assert done["note"] == "ok"
    assert done["finished_at"] is not None


def test_finish_rejects_bad_status(conn):
    jid = db.job_start(conn, kind="scrape")
    with pytest.raises(ValueError):
        db.job_finish(conn, jid, status="running")  # pas un statut terminal


def test_params_none_stays_none(conn):
    jid = db.job_start(conn, kind="augmentation")
    assert db.job_get(conn, jid)["params"] is None


def test_job_latest_picks_most_recent(conn):
    db.job_start(conn, kind="training")
    time.sleep(0.01)
    jid2 = db.job_start(conn, kind="training")
    db.job_start(conn, kind="scrape")  # autre kind, ignoré
    latest = db.job_latest(conn, "training")
    assert latest["id"] == jid2
    assert db.job_latest(conn, "inexistant") is None


def test_reaper_kills_dead_pid_only(conn):
    # Job vivant (notre propre PID) → préservé.
    alive = db.job_start(conn, kind="training")
    db.job_set_pid(conn, alive, os.getpid())
    # Job mort (PID introuvable) → reapé.
    dead = db.job_start(conn, kind="training")
    db.job_set_pid(conn, dead, 2_000_000_000)  # PID quasi-certainement absent
    # Job sans PID → traité comme mort.
    nopid = db.job_start(conn, kind="scrape")

    n = reaper.reap_orphans(conn)
    assert n == 2
    assert db.job_get(conn, alive)["status"] == "running"
    assert db.job_get(conn, dead)["status"] == "failed"
    assert db.job_get(conn, nopid)["status"] == "failed"
    assert "orphan" in db.job_get(conn, dead)["error"]


def test_reaper_runtime_guard_reaps_even_if_alive(conn):
    jid = db.job_start(conn, kind="training")
    db.job_set_pid(conn, jid, os.getpid())  # vivant…
    # …mais on force started_at dans le passé → dépasse la garde runtime.
    conn.execute("UPDATE jobs SET started_at=datetime('now','-120 minutes') WHERE id=?", (jid,))
    n = reaper.reap_orphans(conn, max_runtime_min=60)
    assert n == 1
    assert db.job_get(conn, jid)["status"] == "failed"
    assert "suspect" in db.job_get(conn, jid)["error"]


def test_job_by_param_kind_filter(conn):
    """Un même iteration_id peut être porté par 2 kinds (chaîne 'iteration' +
    bake 'augmentation'). Le filtre kind les départage."""
    chain = db.job_start(conn, kind="iteration", params={"iteration_id": "it1"})
    bake = db.job_start(conn, kind="augmentation", params={"iteration_id": "it1"})

    assert db.job_by_param(conn, "iteration_id", "it1", kind="iteration")["id"] == chain
    assert db.job_by_param(conn, "iteration_id", "it1", kind="augmentation")["id"] == bake
    # sans kind → le dernier (rowid DESC) = le bake
    assert db.job_by_param(conn, "iteration_id", "it1")["id"] == bake
    assert db.job_by_param(conn, "iteration_id", "nope", kind="iteration") is None


def test_stop_process_group_signals_and_reaps(tmp_path):
    """`stop_process_group` SIGTERM le groupe détaché et détecte la mort sans
    rester bloqué sur un zombie (waitpid-reap)."""
    import subprocess
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        outcome = jobs.stop_process_group(proc.pid, graceful_timeout=5.0)
        assert outcome == "graceful"
        assert jobs.proc_dead(proc.pid)
    finally:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except (ProcessLookupError, ChildProcessError, OSError):
            pass


def test_stop_process_group_idle_on_dead_pid():
    assert jobs.stop_process_group(2_000_000_000) == "idle"


def test_launch_detached_subprocess_finishes_job(conn, tmp_path):
    """Bout-en-bout : `launch` ouvre un job + lance un script enfant détaché qui
    clôt le job via sa propre connexion. Le PID et le log_path sont persistés."""
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    child = tmp_path / "child.py"
    child.write_text(
        "from state import Store\n"
        "from jobs import job_id_from_argv, job_finish\n"
        f"store = Store({str(db_path)!r})\n"
        "jid = job_id_from_argv()\n"
        "print('child running for', jid)\n"
        "job_finish(store._connection(), jid, status='done', n_done=1, note='child-ok')\n"
    )
    res = jobs.launch(
        conn, kind="training",
        cmd_builder=lambda jid: [sys.executable, str(child), "--job-id", jid],
    )
    assert res["pid"] is not None

    # Le subprocess est détaché : on poll le statut (comme l'API en prod).
    deadline = time.time() + 15
    while time.time() < deadline:
        row = db.job_get(conn, res["job_id"])
        if row["status"] != "running":
            break
        time.sleep(0.1)

    row = db.job_get(conn, res["job_id"])
    assert row["status"] == "done", f"log: {open(row['log_path']).read()}"
    assert row["note"] == "child-ok"
    assert row["pid"] is not None
    assert row["log_path"].endswith(f"training-{res['job_id']}.log")
    # Le log fichier a bien capté le stdout du child (découplage serving).
    assert "child running for" in open(res["log_path"]).read()
