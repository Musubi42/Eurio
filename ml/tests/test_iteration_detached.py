"""Tests du chemin iteration DÉTACHÉ (refacto-ml chunk 2b-2).

Vérifie le wiring rail côté API (sans lancer de vraie chaîne) :
  - `launch_*` délègue à `jobs.launch` (kind='iteration', cmd + params corrects) ;
  - `is_busy` / `_chain_alive` lisent la liveness du job détaché ;
  - `tail_logs` lit le fichier de log du job ;
  - `stop` signale le process-group détaché et marque l'itération failed.
"""

from __future__ import annotations

import subprocess

import pytest

import jobs
from api.iteration_runner import IterationRunner
from api.training_runner import TrainingRunner
from state import Store


@pytest.fixture
def runner(tmp_path):
    store = Store(tmp_path / "it.db")
    return IterationRunner(store, TrainingRunner(store))


def _conn(runner):
    return runner._store._connection()  # noqa: SLF001


def test_launch_chain_wiring(runner, monkeypatch):
    captured: dict = {}

    def fake_launch(conn, *, kind, cmd_builder, params, **kw):
        captured["kind"] = kind
        captured["params"] = params
        captured["cmd"] = list(cmd_builder("JOB9"))
        return {"job_id": "JOB9", "pid": 1, "log_path": "x"}

    monkeypatch.setattr(jobs, "launch", fake_launch)
    runner._launch_chain("it-123", mode="full")

    assert captured["kind"] == "iteration"
    assert captured["params"] == {"iteration_id": "it-123", "mode": "full"}
    cmd = captured["cmd"]
    assert cmd[1].endswith("run_iteration.py")
    assert "--iteration-id" in cmd and "it-123" in cmd
    assert "--mode" in cmd and "full" in cmd
    assert "--job-id" in cmd and "JOB9" in cmd


def test_is_busy_tracks_live_iteration_job(runner):
    conn = _conn(runner)
    assert runner.is_busy() is False  # aucun job
    # job 'iteration' running + PID mort → pas busy
    j = jobs.job_start(conn, kind="iteration", params={"iteration_id": "a"})
    jobs.job_set_pid(conn, j, 2_000_000_000)
    assert runner.is_busy() is False
    # job running + PID vivant → busy
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        j2 = jobs.job_start(conn, kind="iteration", params={"iteration_id": "b"})
        jobs.job_set_pid(conn, j2, proc.pid)
        assert runner.is_busy() is True
        # job terminé → plus busy
        jobs.job_finish(conn, j2, status="done")
        assert runner.is_busy() is False
    finally:
        proc.kill()
        proc.wait()


def test_tail_logs_reads_job_file(runner, tmp_path):
    conn = _conn(runner)
    log = tmp_path / "it.log"
    log.write_text("a\nb\nc\nd\n")
    j = jobs.job_start(conn, kind="iteration", params={"iteration_id": "itX"})
    conn.execute("UPDATE jobs SET log_path=? WHERE id=?", (str(log), j))
    assert runner.tail_logs("itX", n=2) == ["c", "d"]
    assert runner.tail_logs("missing") == []


def test_stop_signals_group_and_marks_failed(runner, tmp_path):
    conn = _conn(runner)
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        j = jobs.job_start(conn, kind="iteration", params={"iteration_id": "itstop"})
        jobs.job_set_pid(conn, j, proc.pid)
        res = runner.stop("itstop")
        assert res["outcome"] == "graceful"
        assert res["marked_failed"] is True
        assert jobs.proc_dead(proc.pid)
    finally:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except (ProcessLookupError, ChildProcessError, OSError):
            pass


def test_stop_idle_when_no_job(runner):
    res = runner.stop("nope")
    assert res == {"outcome": "idle", "marked_failed": False}
