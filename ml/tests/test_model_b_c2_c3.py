"""Tests Modèle B C2 (auth bearer legacy) + C3 (SDK client + route ingest).

- C2 : ``require_token`` no-op si auth off ; 401 sans/avec mauvais token ; 200 avec
  token valide ; 401 après révocation. (module serving.auth legacy, non utilisé par
  ingest_routes depuis A1.)
- C3 : ``POST /ingest/run`` applique un run-batch (idempotent) + ``GET`` statut ;
  ``push_run`` exporte et POST ; en-têtes HTTP (bearer) ; ``pull_replica`` (R2 :
  tirée du VPS via un transport HTTP injecté).
  Les routes /ingest sont protégées par require_scope("ingest:run") (PAT owner/admin).
  En test, on court-circuite via dependency_overrides sur require_principal.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from store import Store

RUN = "run_c3"


def _seed_min_run(conn, run_id=RUN) -> None:
    conn.execute(
        "INSERT INTO source_runs (id, source, kind) VALUES (?, 'ebay', 'run')", (run_id,)
    )
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, run_id) "
        "VALUES (?, 'ebay', ?, ?)",
        (f"si_{run_id}", f"ebay_{run_id}", run_id),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, run_id, crop_index, storage_path) "
        "VALUES (?, ?, ?, 0, ?)",
        (f"a_{run_id}", f"si_{run_id}", run_id, f"ebay/a_{run_id}.png"),
    )
    conn.execute(
        "INSERT INTO image_state_events (asset_id, to_state, actor, run_id) "
        "VALUES (?, 'queued', 'pipeline', ?)",
        (f"a_{run_id}", run_id),
    )


# ─── C2 : auth bearer ─────────────────────────────────────────────────────────


@pytest.fixture()
def auth_client(tmp_path):
    from serving import auth

    store = Store(tmp_path / "auth.db")
    auth.bind(store)
    app = FastAPI(dependencies=[Depends(auth.require_token)])

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    return store, auth, TestClient(app)


def test_auth_off_is_open(auth_client, monkeypatch):
    _, _, client = auth_client
    monkeypatch.delenv("EURIO_API_AUTH_REQUIRED", raising=False)
    assert client.get("/ping").status_code == 200


def test_auth_on_requires_valid_token(auth_client, monkeypatch):
    store, auth, client = auth_client
    monkeypatch.setenv("EURIO_API_AUTH_REQUIRED", "1")
    # sans token
    assert client.get("/ping").status_code == 401
    # mauvais token
    assert client.get("/ping", headers={"Authorization": "Bearer nope"}).status_code == 401
    # token valide
    token = auth.add_token(store._connection(), "pc")  # noqa: SLF001
    ok = client.get("/ping", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    # via X-Token aussi
    assert client.get("/ping", headers={"X-Token": token}).status_code == 200
    # après révocation → 401
    auth.revoke_token(store._connection(), "pc")  # noqa: SLF001
    assert client.get("/ping", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ─── C3 : route ingest + push_run ────────────────────────────────────────────


def _owner_principal() -> Principal:
    """Principal de substitution avec scope ingest:run (owner) — test only."""
    return Principal(
        user_id="test-owner",
        email="owner@test.local",
        roles=["owner"],
        scopes={"ingest:run"},
        auth_method="api_token",
    )


@pytest.fixture()
def ingest_client(tmp_path):
    from serving import ingest_routes

    dst = Store(tmp_path / "dst.db")
    ingest_routes.bind(dst)
    app = FastAPI()
    # Court-circuite require_principal (et donc require_scope) : pas de DB d'auth
    # nécessaire, le Principal renvoyé possède le scope ingest:run.
    app.dependency_overrides[require_principal] = _owner_principal
    app.include_router(ingest_routes.router)
    return dst, TestClient(app)


def test_ingest_route_applies_and_status(ingest_client, tmp_path):
    from client.runbatch import export_run

    dst, client = ingest_client
    src = Store(tmp_path / "src.db")
    _seed_min_run(src._connection())  # noqa: SLF001
    batch = export_run(src._connection(), RUN)  # noqa: SLF001

    r = client.post("/ingest/run", json=batch)
    assert r.status_code == 200, r.text
    assert r.json()["already_applied"] is False

    # idempotent via la route
    assert client.post("/ingest/run", json=batch).json()["already_applied"] is True

    st = client.get(f"/ingest/run/{RUN}").json()
    assert st["applied"] is True
    assert dst._connection().execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM image_assets"
    ).fetchone()[0] == 1


def test_push_run_exports_and_posts(tmp_path):
    from client.runbatch import push_run

    src = Store(tmp_path / "src.db")
    _seed_min_run(src._connection())  # noqa: SLF001
    captured: dict = {}

    def poster(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}

    push_run(src._connection(), RUN, poster=poster)  # noqa: SLF001
    assert captured["path"] == "/ingest/run"
    assert captured["payload"]["run_id"] == RUN
    assert len(captured["payload"]["tables"]["image_assets"]) == 1


def test_http_headers_bearer(monkeypatch):
    from client import http

    monkeypatch.setenv("EURIO_API_TOKEN", "secret123")
    assert http._headers()["Authorization"] == "Bearer secret123"
    monkeypatch.delenv("EURIO_API_TOKEN")
    assert "Authorization" not in http._headers()


# ─── R2 : réplique read-only tirée du VPS (fake transport HTTP) ───────────────


class _FakeTransport:
    """Transport injectable : sert ``data`` + son sha (comme GET /db/replica[/sha])."""

    def __init__(self, data: bytes):
        self.data = data
        self._sha = hashlib.sha256(data).hexdigest()

    def sha(self):
        return self._sha

    def download(self, dest):  # retourne le sha d'en-tête (cohérent)
        Path(dest).write_bytes(self.data)
        return self._sha


def test_pull_replica_verifies_sha(tmp_path):
    from client.replica import pull_replica

    dest = pull_replica(tmp_path / "replica.db", transport=_FakeTransport(b"sqlite-bytes"))
    assert dest.read_bytes() == b"sqlite-bytes"


def test_pull_replica_rejects_corrupt(tmp_path):
    from client.replica import pull_replica

    class _Corrupt(_FakeTransport):
        def download(self, dest):  # noqa: D401
            Path(dest).write_bytes(b"DIFFERENT")  # sha ne matchera pas
            return None

    with pytest.raises(RuntimeError, match="Intégrité"):
        pull_replica(tmp_path / "replica.db", transport=_Corrupt(b"original"))
