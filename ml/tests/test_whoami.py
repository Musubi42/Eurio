"""Tests de ``GET /whoami`` — origine machine + principal optionnel (R3)."""

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
def client():
    from serving import whoami_routes

    app = FastAPI()
    app.include_router(whoami_routes.router)
    with TestClient(app) as c:
        yield c


def test_whoami_never_401_and_reports_machine(client, monkeypatch):
    monkeypatch.setenv("EURIO_MACHINE_ORIGIN", "pc")
    resp = client.get("/whoami")
    assert resp.status_code == 200  # jamais 401, même sans credentials
    body = resp.json()
    assert body["machine"] == "pc"
    assert body["principal"] is None
    assert "auth_required" in body


def test_machine_origin_maps_hostname(monkeypatch):
    from shared.machine import machine_origin

    monkeypatch.delenv("EURIO_MACHINE_ORIGIN", raising=False)
    monkeypatch.setattr("socket.gethostname", lambda: "Musubi42s-MacBook-Air-Oim.local")
    assert machine_origin() == "mac"
    monkeypatch.setattr("socket.gethostname", lambda: "desktop")
    assert machine_origin() == "pc"
    monkeypatch.setattr("socket.gethostname", lambda: "some-unknown-host")
    assert machine_origin() == "some-unknown-host"  # fallback = hostname brut


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
