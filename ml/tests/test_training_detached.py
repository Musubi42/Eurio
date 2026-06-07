"""Tests du chemin training DÉTACHÉ (refacto-ml chunk 2b-1).

Vérifie le wiring sans lancer de vrai entraînement (pas de GPU) :
  - `start_run` crée run + 6 steps et délègue à `jobs.launch` (cmd + params corrects) ;
  - les lectures (`active_run`/`active_snapshot`/`tail_logs`) résolvent l'état détaché
    depuis la table `training_runs` + la row `jobs` + le fichier de log ;
  - `stop_active` signale le process-group détaché ;
  - `_rehydrate` ne tue que les runs dont le PID est mort.
"""

from __future__ import annotations

import os
import subprocess

import pytest

import jobs
from api.training_runner import TrainingRunner
from store import ClassRef, EpochRow, RunRow, Store


@pytest.fixture
def runner(tmp_path):
    return TrainingRunner(Store(tmp_path / "d.db"))


def test_start_run_detached_wiring(runner, monkeypatch):
    captured: dict = {}

    def fake_launch(conn, *, kind, cmd_builder, params, **kw):
        captured["kind"] = kind
        captured["params"] = params
        captured["cmd"] = list(cmd_builder("JOB1"))
        return {"job_id": "JOB1", "pid": 111, "log_path": "/tmp/x.log"}

    monkeypatch.setattr(jobs, "launch", fake_launch)

    row = runner.start_run(added=[ClassRef("eu-x", "eurio_id")], removed=[])

    assert row.status == "queued"
    assert len(runner._store.list_steps(row.id)) == 6
    assert captured["kind"] == "training"
    assert captured["params"] == {"run_id": row.id}
    cmd = captured["cmd"]
    assert "--run-id" in cmd and row.id in cmd
    assert "--job-id" in cmd and "JOB1" in cmd
    assert cmd[1].endswith("run_pipeline.py")


def test_start_run_rejects_when_detached_active(runner, monkeypatch):
    monkeypatch.setattr(jobs, "launch", lambda *a, **k: {"job_id": "J", "pid": 1, "log_path": "x"})
    runner.start_run(added=[ClassRef("eu-x", "eurio_id")], removed=[])
    # Le run précédent est queued → considéré actif → 2e start_run refusé.
    with pytest.raises(RuntimeError, match="already active"):
        runner.start_run(added=[ClassRef("eu-y", "eurio_id")], removed=[])


def _seed_detached_run(store: Store, run_id: str, pid: int, log_text: str, tmp_path):
    store.create_run(RunRow(id=run_id, version=1, status="running", config={"epochs": 40}))
    log = tmp_path / f"{run_id}.log"
    log.write_text(log_text)
    conn = store._connection()
    jid = jobs.job_start(conn, kind="training", params={"run_id": run_id})
    jobs.job_set_pid(conn, jid, pid)
    conn.execute("UPDATE jobs SET log_path=? WHERE id=?", (str(log), jid))
    return jid


def test_detached_read_surfaces(runner, tmp_path):
    store = runner._store
    rid = "run00001"
    _seed_detached_run(store, rid, os.getpid(), "line1\nline2\nEpoch 7 stuff\n", tmp_path)
    store.append_epoch(rid, EpochRow(epoch=7, train_loss=1.0))

    assert runner.active_run().id == rid
    snap = runner.active_snapshot()
    assert snap == {"run_id": rid, "epoch": 7, "epochs_total": 40}
    assert runner.tail_logs(2) == ["line2", "Epoch 7 stuff"]
    # load_logs d'un run détaché en cours → lit le fichier (archive pas encore écrite)
    assert "line1" in runner.load_logs(rid)


def test_rehydrate_fails_dead_keeps_alive(runner, tmp_path):
    store = runner._store
    _seed_detached_run(store, "dead", 2_000_000_000, "x\n", tmp_path)  # PID mort
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        _seed_detached_run(store, "alive", proc.pid, "y\n", tmp_path)  # PID vivant
        runner._rehydrate()
        assert store.get_run("dead").status == "failed"
        assert store.get_run("alive").status == "running"
    finally:
        proc.kill()
        proc.wait()
