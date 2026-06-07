"""FastAPI integration tests for /lab/* (Bloc 4).

IterationRunner chain is stubbed — we don't spawn subprocesses in tests.
Instead we verify:
- CRUD + validation + 404/409
- Launch wiring (runner.create_and_launch invoked with right args)
- Trajectory + sensitivity wiring
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


class _StubRunner:
    """Stands in for IterationRunner.

    Captures `create_iteration` calls and persists the row via the real
    Store (so subsequent GETs return it). Does not spawn threads. Tests
    that exercise `launch_training` set `self.busy` directly to simulate
    a runner-already-busy scenario.
    """

    def __init__(self, store):
        self.store = store
        self.busy = False
        self.launched: list[dict] = []
        self.training_launched: list[str] = []

    def is_busy(self) -> bool:
        return self.busy

    def create_iteration(self, **kwargs):
        from store import ExperimentIterationRow
        import uuid

        iid = uuid.uuid4().hex[:12]
        row = ExperimentIterationRow(
            id=iid,
            cohort_id=kwargs["cohort_id"],
            parent_iteration_id=kwargs.get("parent_iteration_id"),
            name=kwargs["name"],
            hypothesis=kwargs.get("hypothesis"),
            recipe_id=kwargs.get("recipe_id"),
            variant_count=kwargs.get("variant_count", 100),
            training_config=kwargs.get("training_config", {}),
            status="pending",
            verdict="pending",
        )
        self.store.create_iteration(row)
        self.launched.append({**kwargs, "iteration_id": iid})
        return row

    def launch_training(self, iteration_id: str):
        if self.busy:
            raise RuntimeError("busy")
        self.training_launched.append(iteration_id)
        return self.store.get_iteration(iteration_id)

    def _snapshot_inputs(self, iteration) -> dict:
        return {
            "recipe": None,
            "variant_count": iteration.variant_count,
            "training_config": iteration.training_config,
        }


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from store import Store
    import api.lab_routes as lr

    store = Store(tmp_path / "t.db")
    stub = _StubRunner(store)
    lr.bind(store, stub)

    app = FastAPI()
    app.include_router(lr.router)
    with TestClient(app) as c:
        yield c, store, stub


def _post_cohort(client, name="green-v1", eurio_ids=None, zone="green"):
    c, *_ = client
    return c.post(
        "/lab/cohorts",
        json={
            "name": name,
            "eurio_ids": eurio_ids or ["fr-2007", "de-2005"],
            "zone": zone,
            "description": "test cohort",
        },
    )


# ─── Cohort CRUD ────────────────────────────────────────────────────────────


def test_create_cohort_validates_name(client):
    c, *_ = client
    resp = c.post("/lab/cohorts", json={"name": "Bad Name", "eurio_ids": ["a"]})
    assert resp.status_code == 400


def test_create_cohort_rejects_empty_ids(client):
    c, *_ = client
    resp = c.post("/lab/cohorts", json={"name": "good-name", "eurio_ids": []})
    assert resp.status_code == 400


def test_create_cohort_dedups_eurio_ids(client):
    resp = _post_cohort(client, eurio_ids=["fr-2007", "fr-2007", "de-2005"])
    assert resp.status_code == 200
    data = resp.json()
    assert sorted(data["eurio_ids"]) == ["de-2005", "fr-2007"]


def test_create_cohort_duplicate_name_409(client):
    _post_cohort(client)
    resp = _post_cohort(client)
    assert resp.status_code == 409


def test_get_cohort_by_name(client):
    _post_cohort(client, name="green-v1")
    c, *_ = client
    resp = c.get("/lab/cohorts/green-v1")
    assert resp.status_code == 200
    assert resp.json()["name"] == "green-v1"


def test_list_cohorts_filters_zone(client):
    _post_cohort(client, name="g1", zone="green")
    _post_cohort(client, name="r1", zone="red")
    c, *_ = client
    resp = c.get("/lab/cohorts?zone=red")
    assert resp.status_code == 200
    assert [item["name"] for item in resp.json()] == ["r1"]


def test_update_cohort_forbids_name_clash(client):
    _post_cohort(client, name="green-v1")
    _post_cohort(client, name="green-v2")
    c, *_ = client
    cohort = c.get("/lab/cohorts/green-v2").json()
    resp = c.put(f"/lab/cohorts/{cohort['id']}", json={"name": "green-v1"})
    assert resp.status_code == 409


def test_delete_cohort(client):
    _post_cohort(client, name="ephemeral")
    c, *_ = client
    cohort = c.get("/lab/cohorts/ephemeral").json()
    resp = c.delete(f"/lab/cohorts/{cohort['id']}")
    assert resp.status_code == 200
    assert c.get(f"/lab/cohorts/{cohort['id']}").status_code == 404


# ─── Iteration launch ──────────────────────────────────────────────────────


def test_create_iteration_calls_runner(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={
            "name": "baseline",
            "hypothesis": "just wanted a starting point",
            "variant_count": 150,
            "training_config": {"epochs": 40},
        },
    )
    assert resp.status_code == 200
    assert len(stub.launched) == 1
    assert stub.launched[0]["variant_count"] == 150
    assert stub.launched[0]["cohort_id"] == cohort["id"]


def test_create_iteration_rejects_empty_name(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "   "},
    )
    assert resp.status_code == 400


def test_create_iteration_rejects_absurd_variant_count(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "huge", "variant_count": 10000},
    )
    assert resp.status_code == 400


def test_create_iteration_succeeds_when_busy_and_launch_rejects(client):
    """Two-phase flow: creation is always allowed (even when a runner is busy),
    only `launch-training` rejects with 409. Users want the new draft to appear
    immediately so they can pre-bake augmentations while the previous iteration
    is still finishing."""
    _post_cohort(client, name="c1")
    c, store, stub = client
    stub.busy = True
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "late"},
    )
    assert resp.status_code == 200, resp.text
    iid = resp.json()["id"]

    launch = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations/{iid}/launch-training",
    )
    # Stub raises RuntimeError("busy") — route maps that to 409.
    assert launch.status_code == 409


def test_runner_status_endpoint(client):
    c, store, stub = client
    assert c.get("/lab/runner/status").json() == {"busy": False}
    stub.busy = True
    assert c.get("/lab/runner/status").json() == {"busy": True}


# ─── Iteration CRUD + drill-down ───────────────────────────────────────────


def test_update_iteration_accepts_notes_and_verdict_override(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    iteration = c.get(
        f"/lab/cohorts/{cohort['id']}/iterations"
    ).json()[0]
    resp = c.put(
        f"/lab/cohorts/{cohort['id']}/iterations/{iteration['id']}",
        json={"notes": "résultat inattendu", "verdict_override": "better"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "résultat inattendu"
    assert resp.json()["verdict_override"] == "better"


def test_update_iteration_rejects_invalid_verdict(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    iteration = c.get(
        f"/lab/cohorts/{cohort['id']}/iterations"
    ).json()[0]
    resp = c.put(
        f"/lab/cohorts/{cohort['id']}/iterations/{iteration['id']}",
        json={"verdict_override": "amazing"},
    )
    assert resp.status_code == 400


def test_delete_iteration_forbidden_while_running(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    iteration = c.get(
        f"/lab/cohorts/{cohort['id']}/iterations"
    ).json()[0]
    store.update_iteration(iteration["id"], status="training")
    resp = c.delete(
        f"/lab/cohorts/{cohort['id']}/iterations/{iteration['id']}"
    )
    assert resp.status_code == 409


# ─── Trajectory + sensitivity ──────────────────────────────────────────────


def test_trajectory_returns_compact_list(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    traj = c.get(f"/lab/cohorts/{cohort['id']}/trajectory")
    assert traj.status_code == 200
    data = traj.json()
    assert len(data) == 1
    assert data[0]["name"] == "baseline"
    assert "r_at_1" in data[0]


def test_sensitivity_runs_on_empty_cohort(client):
    _post_cohort(client, name="c1")
    c, *_ = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.get(f"/lab/cohorts/{cohort['id']}/sensitivity")
    assert resp.status_code == 200
    assert resp.json() == []


# ─── Live tests (Sprint 4) ──────────────────────────────────────────────────


import json
from pathlib import Path

import api.lab_routes as _lr_mod
from store import (
    BenchmarkRunRow,
    ExperimentCohortRow,
    ExperimentIterationRow,
)


@pytest.fixture()
def live_test_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Same wiring as ``client`` but with a redirected LIVE_TEST_LOGS_DIR.

    The default ``ml/state/live_test_logs/`` lives under the repo. We point it
    at a tmp dir for hermetic runs.
    """
    from store import Store
    import api.lab_routes as lr

    store = Store(tmp_path / "t.db")
    stub = _StubRunner(store)
    lr.bind(store, stub)
    logs_dir = tmp_path / "live_test_logs"
    logs_dir.mkdir()
    monkeypatch.setattr(lr, "LIVE_TEST_LOGS_DIR", logs_dir)

    app = FastAPI()
    app.include_router(lr.router)
    with TestClient(app) as c:
        yield c, store, logs_dir


def _seed_cohort_with_completed_iteration(
    store, *, eurio_ids=None, r_at_1=0.92,
):
    eurio_ids = eurio_ids or ["fr-2007", "de-2005"]
    store.create_cohort(ExperimentCohortRow(
        id="c1", name="cohort-x", eurio_ids=eurio_ids, status="frozen",
    ))
    store.create_benchmark_run(BenchmarkRunRow(
        id="b1", model_path="", model_name="m",
        report_path="", status="completed", r_at_1=r_at_1,
    ))
    store.create_iteration(ExperimentIterationRow(
        id="iter1", cohort_id="c1", name="it1",
        status="completed", benchmark_run_id="b1",
    ))


def _line(idx: int, *, eid="fr-2007", cond="bright",
          top1="fr-2007", sim=0.95, correct=True, error=None) -> str:
    return json.dumps({
        "schema_version": 1,
        "test_idx": idx,
        "iteration_id": "iter1",
        "expected_eurio_id": eid,
        "condition": cond,
        "predicted_top3": [{"eurio_id": top1, "similarity": sim}] if top1 else [],
        "predicted_top1": top1,
        "similarity_top1": sim if top1 else None,
        "is_correct": correct,
        "error": error,
        "ts": "2026-04-30T14:00:00Z",
    })


def test_live_tests_sync_404_when_log_missing(live_test_client):
    c, store, _ = live_test_client
    _seed_cohort_with_completed_iteration(store)
    resp = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp.status_code == 404
    assert "JSONL absent" in resp.json()["detail"]


def test_live_tests_sync_404_when_iteration_missing(live_test_client):
    c, *_ = live_test_client
    resp = c.post("/lab/cohorts/_/iterations/missing/live-tests/sync", json={})
    assert resp.status_code == 404


def test_live_tests_sync_parses_and_dedups(live_test_client):
    c, store, logs = live_test_client
    _seed_cohort_with_completed_iteration(store)
    (logs / "iter1.jsonl").write_text("\n".join([
        _line(1),
        _line(2, cond="dim", top1="de-2005", sim=0.42, correct=False),
        _line(3, eid="de-2005", cond="tilt", top1=None, sim=0.0,
              correct=False, error="normalize failed"),
        "",
        "not-json",
        json.dumps({"schema_version": 99}),
    ]) + "\n")

    resp = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 3
    assert body["skipped_dupe"] == 0
    assert len(body["parse_errors"]) == 2
    assert body["summary"]["total"] == 3
    assert body["summary"]["correct"] == 1
    assert body["summary"]["recall_at_1"] == pytest.approx(1 / 3)
    assert body["summary"]["studio_r_at_1"] == pytest.approx(0.92)
    assert body["summary"]["delta"] == pytest.approx(1 / 3 - 0.92)

    # Resync = idempotent.
    resp2 = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp2.json()["inserted"] == 0
    assert resp2.json()["skipped_dupe"] == 3


def test_live_tests_get_returns_matrix(live_test_client):
    c, store, logs = live_test_client
    _seed_cohort_with_completed_iteration(store)
    (logs / "iter1.jsonl").write_text("\n".join([
        _line(1),
        _line(2, cond="dim", top1="de-2005", correct=False),
    ]) + "\n")
    c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})

    resp = c.get("/lab/cohorts/c1/iterations/iter1/live-tests")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cohort_name"] == "cohort-x"
    assert body["conditions"] == ["bright", "dim", "tilt"]
    assert "fr-2007" in body["matrix"]
    assert set(body["matrix"]["fr-2007"]) == {"bright", "dim"}
    assert body["summary"]["total"] == 2


def test_live_tests_get_404_on_wrong_cohort(live_test_client):
    c, store, _ = live_test_client
    _seed_cohort_with_completed_iteration(store)
    resp = c.get("/lab/cohorts/missing/iterations/iter1/live-tests")
    assert resp.status_code == 404


def test_live_tests_sync_rejects_iteration_id_mismatch(live_test_client):
    c, store, logs = live_test_client
    _seed_cohort_with_completed_iteration(store)
    bad = json.dumps({
        "schema_version": 1, "test_idx": 1, "iteration_id": "WRONG",
        "expected_eurio_id": "fr-2007", "condition": "bright",
        "predicted_top3": [], "predicted_top1": None,
        "similarity_top1": None, "is_correct": False,
        "ts": "2026-04-30T14:00:00Z",
    })
    (logs / "iter1.jsonl").write_text(bad + "\n")
    resp = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp.status_code == 200
    assert resp.json()["inserted"] == 0
    assert any("iteration_id" in e for e in resp.json()["parse_errors"])
