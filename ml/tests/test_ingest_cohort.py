"""Tests F09 — sync des dimensions lab (cohortes/itérations) vers le canonique.

Couvre :
- ``POST /ingest/cohort`` (upsert roundtrip, idempotence, scopes) ;
- ``DELETE /ingest/cohort/{id}`` (idempotent, 409 si itérations référentes) ;
- ``PUT /iterations/{id}`` → 409 lisible si la cohorte n'a pas voyagé ;
- ``DELETE /iterations/{id}`` (idempotent) ;
- les ancrages best-effort de ``lab_routes`` (create/delete cohort → push,
  une exception du push ne casse pas la requête) ;
- le backfill ``scripts.push_lab_dimensions`` (ordre cohortes→itérations,
  comptage, --dry, exit 1 sur échec).
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


def _make_app(tmp_path: Path, scopes: set[str]):
    from serving import ingest_routes, iteration_sync_routes
    from serving.auth_principal import Principal, require_principal
    from store import Store

    store = Store(tmp_path / "t.db")
    ingest_routes.bind(store)
    iteration_sync_routes.bind(store)

    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.include_router(iteration_sync_routes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="u", email="e@t", roles=["owner"], scopes=set(scopes)
    )
    return app, store


_COHORT = {
    "id": "c1",
    "name": "cohort-1",
    "description": "desc",
    "zone": "green",
    "eurio_ids": ["fr-2007", "de-2005"],
    "status": "draft",
    "frozen_at": None,
    "created_at": "2026-07-01 10:00:00",
    "updated_at": "2026-07-01 10:00:00",
}

_ITERATION = {
    "cohort_id": "c1",
    "name": "iter-mac",
    "status": "completed",
    "variant_count": 100,
    "training_config": {"epochs": 3},
    "created_at": "2026-07-01 10:00:00",
    "created_on": "mac",
}


# ─── POST /ingest/cohort ─────────────────────────────────────────────────────


def test_cohort_upsert_roundtrip_and_idempotence(tmp_path: Path):
    app, store = _make_app(tmp_path, {"ingest:write"})
    with TestClient(app) as c:
        r1 = c.post("/ingest/cohort", json=_COHORT)
        assert r1.status_code == 200, r1.json()
        assert r1.json() == {"id": "c1", "op": "upserted"}

        got = store.get_cohort("c1")
        assert got is not None
        assert got.name == "cohort-1"
        assert got.eurio_ids == ["fr-2007", "de-2005"]
        assert got.created_at == "2026-07-01 10:00:00"  # source préservée

        # 2e POST (état modifié) : toujours 1 row, champs remplacés.
        r2 = c.post(
            "/ingest/cohort",
            json={**_COHORT, "status": "frozen", "frozen_at": "2026-07-02 09:00:00",
                  "eurio_ids": ["fr-2007"]},
        )
        assert r2.status_code == 200
        assert len(store.list_cohorts()) == 1
        got = store.get_cohort("c1")
        assert got.status == "frozen"
        assert got.frozen_at == "2026-07-02 09:00:00"
        assert got.eurio_ids == ["fr-2007"]
        assert got.created_at == "2026-07-01 10:00:00"  # jamais réécrit


def test_cohort_upsert_preserves_created_at_when_source_omits_it(tmp_path: Path):
    app, store = _make_app(tmp_path, {"ingest:write"})
    with TestClient(app) as c:
        assert c.post("/ingest/cohort", json=_COHORT).status_code == 200
        snap = {**_COHORT, "created_at": None, "updated_at": None}
        assert c.post("/ingest/cohort", json=snap).status_code == 200
        got = store.get_cohort("c1")
        assert got.created_at == "2026-07-01 10:00:00"  # existant préservé
        assert got.updated_at is not None  # retombé sur datetime('now')


# ─── DELETE /ingest/cohort/{id} ──────────────────────────────────────────────


def test_cohort_delete_idempotent(tmp_path: Path):
    app, store = _make_app(tmp_path, {"ingest:write"})
    with TestClient(app) as c:
        c.post("/ingest/cohort", json=_COHORT)
        r1 = c.delete("/ingest/cohort/c1")
        assert r1.status_code == 200
        assert r1.json() == {"id": "c1", "op": "deleted"}
        assert store.get_cohort("c1") is None
        # Retry après succès : pas de 404.
        r2 = c.delete("/ingest/cohort/c1")
        assert r2.status_code == 200
        assert r2.json() == {"id": "c1", "op": "absent"}


def test_cohort_delete_with_referencing_iteration_409(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"ingest:write"})
    with TestClient(app) as c:
        c.post("/ingest/cohort", json=_COHORT)
        assert c.put("/iterations/it1", json=_ITERATION).status_code == 200
        r = c.delete("/ingest/cohort/c1")
        assert r.status_code == 409
        assert "it1" in r.json()["detail"]
        # Après suppression de l'itération, le delete passe.
        assert c.delete("/iterations/it1").json()["op"] == "deleted"
        assert c.delete("/ingest/cohort/c1").json()["op"] == "deleted"


def test_cohort_routes_require_ingest_write(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"lab:read"})  # pas de ingest:write
    with TestClient(app) as c:
        assert c.post("/ingest/cohort", json=_COHORT).status_code == 403
        assert c.delete("/ingest/cohort/c1").status_code == 403
        assert c.delete("/iterations/it1").status_code == 403


# ─── Garde FK du PUT /iterations + DELETE /iterations ───────────────────────


def test_put_iteration_without_cohort_409(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"ingest:write"})
    with TestClient(app) as c:
        r = c.put("/iterations/it1", json=_ITERATION)
        assert r.status_code == 409
        assert "pousse la cohorte d'abord" in r.json()["detail"]
        assert "POST /ingest/cohort" in r.json()["detail"]


def test_put_iteration_with_cohort_200(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"ingest:write"})
    with TestClient(app) as c:
        c.post("/ingest/cohort", json=_COHORT)
        r = c.put("/iterations/it1", json=_ITERATION)
        assert r.status_code == 200, r.json()
        assert r.json()["id"] == "it1"


def test_delete_iteration_idempotent(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"ingest:write"})
    with TestClient(app) as c:
        c.post("/ingest/cohort", json=_COHORT)
        c.put("/iterations/it1", json=_ITERATION)
        assert c.delete("/iterations/it1").json() == {"id": "it1", "op": "deleted"}
        assert c.delete("/iterations/it1").json() == {"id": "it1", "op": "absent"}


# ─── Ancrages lab_routes (push best-effort) ──────────────────────────────────


@pytest.fixture()
def lab_client(tmp_path: Path):
    from store import Store
    import serving.lab_routes as lr

    store = Store(tmp_path / "lab.db")
    lr.bind(store, runner=None)

    app = FastAPI()
    app.include_router(lr.router)
    with TestClient(app) as c:
        yield c, store


def test_create_cohort_triggers_canonical_push(lab_client, monkeypatch):
    pushed: list[dict] = []
    monkeypatch.setattr("client.ingest.push_cohort", lambda d: pushed.append(d) or {})
    c, store = lab_client
    r = c.post("/lab/cohorts", json={"name": "green-v1", "eurio_ids": ["fr-2007"]})
    assert r.status_code == 200, r.json()
    assert len(pushed) == 1
    assert pushed[0]["name"] == "green-v1"
    assert pushed[0]["id"] == r.json()["id"]


def test_delete_cohort_triggers_canonical_delete_push(lab_client, monkeypatch):
    deleted: list[str] = []
    monkeypatch.setattr("client.ingest.push_cohort", lambda d: {})
    monkeypatch.setattr(
        "client.ingest.push_cohort_delete", lambda cid: deleted.append(cid) or {}
    )
    c, _ = lab_client
    cid = c.post("/lab/cohorts", json={"name": "tmp-c", "eurio_ids": ["x"]}).json()["id"]
    r = c.delete(f"/lab/cohorts/{cid}")
    assert r.status_code == 200
    assert deleted == [cid]


def test_push_failure_never_fails_the_request(lab_client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("VPS injoignable")

    monkeypatch.setattr("client.ingest.push_cohort", boom)
    monkeypatch.setattr("client.ingest.push_cohort_delete", boom)
    c, _ = lab_client
    r = c.post("/lab/cohorts", json={"name": "green-v2", "eurio_ids": ["x"]})
    assert r.status_code == 200  # le write local reste roi
    assert c.delete(f"/lab/cohorts/{r.json()['id']}").status_code == 200


# ─── Backfill scripts.push_lab_dimensions ────────────────────────────────────


def _seed_local_db(tmp_path: Path) -> Path:
    from store import ExperimentCohortRow, ExperimentIterationRow, Store

    db = tmp_path / "local.db"
    store = Store(db)
    store.create_cohort(ExperimentCohortRow(id="c1", name="c1", eurio_ids=["x"]))
    store.create_cohort(ExperimentCohortRow(id="c2", name="c2", eurio_ids=["y"]))
    store.create_iteration(
        ExperimentIterationRow(id="it1", cohort_id="c1", name="iter", status="pending")
    )
    return db


def test_backfill_pushes_cohorts_then_iterations(tmp_path, monkeypatch):
    db = _seed_local_db(tmp_path)
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.example.dev")
    monkeypatch.setenv("EURIO_DB_PATH", str(db))

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "client.http.post_json",
        lambda path, payload, **kw: calls.append(("POST", path)) or {},
    )
    monkeypatch.setattr(
        "client.http.put_json",
        lambda path, payload, **kw: calls.append(("PUT", path)) or {},
    )

    from scripts.push_lab_dimensions import main

    assert main([]) == 0
    assert [m for m, _ in calls] == ["POST", "POST", "PUT"]  # cohortes D'ABORD
    assert calls[0][1] == "/ingest/cohort"
    assert calls[2][1] == "/iterations/it1"


def test_backfill_counts_failures_and_exits_1(tmp_path, monkeypatch):
    db = _seed_local_db(tmp_path)
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.example.dev")
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    monkeypatch.setattr("client.http.post_json", lambda *a, **k: {})

    def boom(*a, **k):
        raise RuntimeError("500")

    monkeypatch.setattr("client.http.put_json", boom)

    from scripts.push_lab_dimensions import main

    assert main([]) == 1


def test_backfill_dry_makes_no_network_calls(tmp_path, monkeypatch):
    db = _seed_local_db(tmp_path)
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.example.dev")
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    called = []
    monkeypatch.setattr("client.http.post_json", lambda *a, **k: called.append(1) or {})
    monkeypatch.setattr("client.http.put_json", lambda *a, **k: called.append(1) or {})

    from scripts.push_lab_dimensions import main

    assert main(["--dry"]) == 0
    assert called == []


def test_backfill_refuses_without_remote_canonical(tmp_path, monkeypatch):
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    from scripts.push_lab_dimensions import main

    with pytest.raises(SystemExit):
        main([])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
