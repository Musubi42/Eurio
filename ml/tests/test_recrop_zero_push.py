"""C4b — recrop-zero (mode --coin) devient poussable au canonique VPS.

Deux surfaces couvertes:
1. `serving.lab_routes.recrop_zero_coin` ajoute `--push` à la commande
   subprocess quand `client.http.sync_enabled()` est vrai (EURIO_API_URL
   configuré), et l'omet sinon (Modèle A local inchangé).
2. `scripts.recrop_cohort_census._run_single_coin_job(push=True)` bascule
   l'écriture des crops sur une réplique pull-ée puis pousse le run au
   canonique via `push_run`, tout en gardant le bookkeeping `cohort_jobs`
   (progress/finish) sur la connexion locale.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from store import Store
    import serving.lab_routes as lr

    store = Store(tmp_path / "t.db")
    lr.bind(store, runner=None)
    monkeypatch.setattr(lr, "_require_classes_ready", lambda cohort: None)

    app = FastAPI()
    app.include_router(lr.router)
    with TestClient(app) as c:
        yield c, store


def _post_cohort(client_tuple, name="c1", eurio_ids=("2eur_be_2007",)):
    c, _store = client_tuple
    resp = c.post("/lab/cohorts", json={
        "name": name, "zone": "green", "eurio_ids": list(eurio_ids),
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_recrop_zero_cmd_appends_push_when_sync_enabled(client, monkeypatch):
    """EURIO_API_URL présent → le subprocess reçoit --push."""
    import serving.lab_routes as lr

    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    cohort = _post_cohort(client)
    c, _store = client

    captured_cmd = {}

    class _FakeProc:
        pid = 4242

    def _fake_popen(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(lr.subprocess, "Popen", _fake_popen)

    resp = c.post(f"/lab/cohorts/{cohort['id']}/coins/2eur_be_2007/recrop-zero")
    assert resp.status_code == 202, resp.text
    assert "--push" in captured_cmd["cmd"]


def test_recrop_zero_cmd_omits_push_when_sync_disabled(client, monkeypatch):
    """Pas d'EURIO_API_URL → Modèle A local, --push absent (comportement inchangé)."""
    import serving.lab_routes as lr

    monkeypatch.delenv("EURIO_API_URL", raising=False)
    cohort = _post_cohort(client, name="c2")
    c, _store = client

    captured_cmd = {}

    class _FakeProc:
        pid = 4243

    def _fake_popen(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(lr.subprocess, "Popen", _fake_popen)

    resp = c.post(f"/lab/cohorts/{cohort['id']}/coins/2eur_be_2007/recrop-zero")
    assert resp.status_code == 202, resp.text
    assert "--push" not in captured_cmd["cmd"]


def test_single_coin_job_push_uses_replica_and_push_run(tmp_path, monkeypatch):
    """`_run_single_coin_job(push=True)` : écrit sur la réplique pull-ée puis
    appelle push_run — le bookkeeping cohort_jobs reste sur la connexion locale."""
    import sqlite3
    import scripts.recrop_cohort_census as mod

    local_db = tmp_path / "local.db"
    replica_db = tmp_path / "replica.db"

    from store import Store
    Store(local_db)  # bootstrap schema
    Store(replica_db)  # bootstrap schema

    monkeypatch.setattr(mod, "DB_PATH", local_db)

    conn = sqlite3.connect(local_db)
    job_id = "job-1"
    conn.execute(
        "INSERT INTO cohort_jobs (id, kind, cohort_id, eurio_id, target_eurio_id, "
        "run_id, status, n_total, started_at) VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
        (job_id, "recrop_zero", "cohort-1", "2eur_be_2007", "2eur_be_2007",
         "run-1", "running", 0),
    )
    conn.commit()
    conn.close()

    seen_conns = []

    def _fake_recrop_zero_for_coin(conn, coin, *, run_id, commit, progress_cb=None, limit=0):
        seen_conns.append(conn)
        if progress_cb:
            progress_cb(1)
        return {"scanned": 1, "recovered": 1, "crops": 1, "auto_phash": 0}

    pushed = {}

    def _fake_push_run(conn, run_id):
        pushed["run_id"] = run_id
        pushed["conn"] = conn
        return {"already_applied": False, "counts": {"image_assets": 1}}

    monkeypatch.setattr(mod, "sqlite3", sqlite3)
    monkeypatch.setattr("client.replica.pull_replica", lambda *a, **k: replica_db)
    monkeypatch.setattr("client.runbatch.push_run", _fake_push_run)

    from store.connection import _register_phash_udfs

    rc = mod._run_single_coin_job(
        coin="2eur_be_2007", job_id=job_id, run_id="run-1", tau=0.55,
        recrop_zero_for_coin=_fake_recrop_zero_for_coin,
        register_udfs=_register_phash_udfs,
        push=True,
    )
    assert rc == 0
    assert pushed["run_id"] == "run-1"
    # La connexion de travail (recrop) n'est PAS la connexion locale (job bookkeeping) :
    # c'est bien la réplique qui reçoit l'écriture, pas le eurio.db Mac.
    assert len(seen_conns) == 1

    conn2 = sqlite3.connect(local_db)
    row = conn2.execute(
        "SELECT status, n_produced FROM cohort_jobs WHERE id=?", (job_id,)
    ).fetchone()
    conn2.close()
    assert row[0] == "done"
    assert row[1] == 1
