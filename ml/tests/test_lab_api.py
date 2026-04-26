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

    Captures `create_and_launch` calls and persists the iteration via the
    real Store (so subsequent GETs return it). Does not spawn threads.
    """

    def __init__(self, store):
        self.store = store
        self.busy = False
        self.launched: list[dict] = []

    def is_busy(self) -> bool:
        return self.busy

    def create_and_launch(self, **kwargs):
        from state import ExperimentIterationRow
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

    def _snapshot_inputs(self, iteration) -> dict:
        return {
            "recipe": None,
            "variant_count": iteration.variant_count,
            "training_config": iteration.training_config,
        }


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from state import Store
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


def test_create_iteration_rejects_when_busy(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    stub.busy = True
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "late"},
    )
    assert resp.status_code == 409


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
