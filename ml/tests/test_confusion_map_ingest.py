"""F02/C2 — écriture de la cartographie de confusion dans eurio.db.

Couvre : la fonction SQL-pure ``apply_ingest_confusion_map`` (UPSERT idempotent,
validation), l'endpoint ``POST /ingest/confusion-map`` (scope ``ingest:write``),
et le gating client ``push_confusion_map`` (Model A → no-op).

La table ``coin_confusion_map`` vit dans la migration ``0002_orphan_supabase_tables``
(appliquée par ``db_migrate`` sur le canonique), pas dans ``schema.sql`` bootstrappé
par ``Store`` — on la crée donc explicitement dans les fixtures, comme en prod.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from store import Store
from store.confusion import apply_ingest_confusion_map

_CONFUSION_DDL = (ML_DIR / "serving" / "migrations" / "0002_orphan_supabase_tables.sql").read_text()


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes=set(scopes), auth_method="api_token",
    )


def _seed_coin(conn, eurio_id):
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value) "
        "VALUES (?, 'FR', 2002, 2.0)",
        (eurio_id,),
    )


def _prepare(conn, ids):
    conn.executescript(_CONFUSION_DDL)
    for eid in ids:
        _seed_coin(conn, eid)


def _row(eurio_id, nearest, sim, zone):
    return {
        "eurio_id": eurio_id,
        "nearest_eurio_id": nearest,
        "nearest_similarity": sim,
        "top_k_neighbors": [{"eurio_id": nearest, "similarity": sim}],
        "zone": zone,
    }


# ─── Store function (unit) ────────────────────────────────────────────────────


def test_apply_upserts_and_is_idempotent(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _prepare(conn, ["a", "b"])

    rows = [_row("a", "b", 0.91, "red"), _row("b", "a", 0.91, "red")]
    conn.execute("BEGIN")
    res = apply_ingest_confusion_map(conn, "dinov2-vits14", rows)
    conn.execute("COMMIT")
    assert res == {"upserted": 2}

    # Re-run avec une similarité modifiée → merge (pas de doublon).
    conn.execute("BEGIN")
    apply_ingest_confusion_map(conn, "dinov2-vits14", [_row("a", "b", 0.42, "orange")])
    conn.execute("COMMIT")

    n = conn.execute("SELECT COUNT(*) FROM coin_confusion_map").fetchone()[0]
    assert n == 2  # UNIQUE(eurio_id, encoder_version) → a n'est pas dupliqué
    a = conn.execute(
        "SELECT nearest_similarity, zone FROM coin_confusion_map WHERE eurio_id='a'"
    ).fetchone()
    assert a["zone"] == "orange" and a["nearest_similarity"] == 0.42


def test_apply_rejects_bad_zone(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _prepare(conn, ["a", "b"])
    conn.execute("BEGIN")
    with pytest.raises(ValueError):
        apply_ingest_confusion_map(conn, "v", [_row("a", "b", 0.5, "purple")])
    conn.execute("ROLLBACK")


# ─── Endpoint ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def env(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _prepare(conn, ["a", "b"])
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:write"})
    return conn, TestClient(app)


def test_endpoint_writes(env):
    conn, client = env
    body = {
        "encoder_version": "dinov2-vits14",
        "rows": [_row("a", "b", 0.88, "red"), _row("b", "a", 0.88, "red")],
    }
    r = client.post("/ingest/confusion-map", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"upserted": 2}
    top = conn.execute(
        "SELECT top_k_neighbors, zone FROM coin_confusion_map WHERE eurio_id='a'"
    ).fetchone()
    assert top["zone"] == "red"
    assert "b" in top["top_k_neighbors"]  # stocké en TEXT JSON


def test_endpoint_requires_scope(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    _prepare(store._connection(), ["a", "b"])  # noqa: SLF001
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:run"})
    client = TestClient(app)
    r = client.post(
        "/ingest/confusion-map",
        json={"encoder_version": "v", "rows": [_row("a", "b", 0.5, "green")]},
    )
    assert r.status_code == 403


# ─── Client gating (Model A) ──────────────────────────────────────────────────


def test_push_noop_when_sync_disabled(monkeypatch):
    from client import ingest as client_ingest

    monkeypatch.delenv("EURIO_API_URL", raising=False)
    assert client_ingest.push_confusion_map("v", [_row("a", "b", 0.5, "green")]) is None
