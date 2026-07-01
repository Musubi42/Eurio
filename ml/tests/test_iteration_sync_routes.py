"""Tests du router canonique léger des itérations (R3, Model B).

Vérifie l'upsert (push d'une machine de calcul) + la lecture + l'application des
scopes (`lab:read` en lecture, `ingest:write` en upsert). Le principal est injecté
via ``dependency_overrides`` (pas de vrai flux auth ici).
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
    from serving import iteration_sync_routes
    from serving.auth_principal import Principal, require_principal
    from store import ExperimentCohortRow, Store

    store = Store(tmp_path / "t.db")
    store.create_cohort(ExperimentCohortRow(id="c1", name="cohort-1", eurio_ids=["x"]))
    iteration_sync_routes.bind(store)

    app = FastAPI()
    app.include_router(iteration_sync_routes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="u", email="e@t", roles=["owner"], scopes=set(scopes)
    )
    return app, store


_SNAPSHOT = {
    "cohort_id": "c1",
    "name": "iter-mac",
    "status": "completed",
    "recipe_id": None,
    "variant_count": 100,
    "training_config": {"epochs": 3},
    "verdict": "better",
    "created_at": "2026-07-01 10:00:00",
    "created_on": "mac",
    "summary": {"r_at_1": 0.79, "loss": 0.05},
}


def test_upsert_get_list_roundtrip(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"lab:read", "ingest:write"})
    with TestClient(app) as c:
        # PUT (upsert d'un snapshot poussé)
        put = c.put("/iterations/it1", json=_SNAPSHOT)
        assert put.status_code == 200, put.json()
        body = put.json()
        assert body["id"] == "it1"
        assert body["created_on"] == "mac"
        assert body["summary"] == {"r_at_1": 0.79, "loss": 0.05}

        # GET détail — round-trip origine + métriques dénormalisées
        got = c.get("/iterations/it1")
        assert got.status_code == 200
        assert got.json()["created_on"] == "mac"
        assert got.json()["summary"]["r_at_1"] == 0.79
        assert got.json()["created_at"] == "2026-07-01 10:00:00"  # source préservée

        # GET liste filtrée cohorte
        listed = c.get("/iterations?cohort_id=c1")
        assert listed.status_code == 200
        assert [r["id"] for r in listed.json()] == ["it1"]

        # Re-PUT (idempotent, last-writer-wins) : change le statut
        put2 = c.put("/iterations/it1", json={**_SNAPSHOT, "status": "failed"})
        assert put2.status_code == 200
        assert c.get("/iterations/it1").json()["status"] == "failed"
        # toujours une seule row
        assert len(c.get("/iterations?cohort_id=c1").json()) == 1


def test_missing_iteration_404(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"lab:read"})
    with TestClient(app) as c:
        assert c.get("/iterations/nope").status_code == 404


def test_read_requires_lab_read(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"ingest:write"})  # pas de lab:read
    with TestClient(app) as c:
        assert c.get("/iterations?cohort_id=c1").status_code == 403


def test_upsert_requires_ingest_write(tmp_path: Path):
    app, _ = _make_app(tmp_path, {"lab:read"})  # pas de ingest:write
    with TestClient(app) as c:
        assert c.put("/iterations/it1", json=_SNAPSHOT).status_code == 403


def test_role_scopes_include_new_scopes():
    from serving.auth_principal import roles_to_scopes

    owner = roles_to_scopes(["owner"])
    assert "lab:read" in owner and "ingest:write" in owner
    assert "lab:read" in roles_to_scopes(["reviewer"])
    assert "ingest:write" not in roles_to_scopes(["reviewer"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
