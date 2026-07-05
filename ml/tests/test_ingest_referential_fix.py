"""C4b — `POST /ingest/referential-fix` : mutation référentielle canonique (shape B).

Le client calcule le diff (2 rows coins + re-parents coin_canonical_images) sur la
réplique ; le serveur re-vérifie le preflight et applique en une tx. Vérifie
l'application, le re-parent/upsert canonical, le 409 sur preflight divergent, et
la garde one-shot (re-apply = conflit, pas de double).
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from store import Store

EXISTING = "be-2014-2eur-x"
NEW = "be-2014-2eur-new"


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes=set(scopes), auth_method="api_token",
    )


def _client(store, scopes=("ingest:write",)):
    from serving import ingest_routes

    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal(scopes)
    return TestClient(app)


def _seed(conn, *, existing_nid=100):
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative, numista_id) "
        "VALUES (?, 'BE', 2014, 2.0, 0, ?)",
        (EXISTING, existing_nid),
    )
    conn.execute(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, url, local_path) "
        "VALUES (?, 'bce_comm', 'obverse', 'http://x', 'old/path.webp')",
        (EXISTING,),
    )


def _diff():
    return {
        "case_id": "c1",
        "preflight": {
            "existing_eurio_id": EXISTING, "current_numista_id": 100,
            "new_row_eurio_id": NEW, "new_row_numista_id": 200,
            "swap_new_numista_id": 150,
        },
        "coins_insert": {
            "eurio_id": NEW, "country": "BE", "country_name": "Belgium", "year": 2015,
            "face_value": 2.0, "theme": "Expo", "numista_id": 200,
            "raw_payload_json": "{}", "ref_native_id": "200",
            "design_description": "d", "updated_at": "2026-07-05",
        },
        "coins_update": {
            "eurio_id": EXISTING, "numista_id": 150, "ref_native_id": "150",
            "raw_payload_json": "{}", "updated_at": "2026-07-05",
        },
        "canonical_images": [
            {"op": "reparent", "from_eurio_id": EXISTING, "to_eurio_id": NEW,
             "source": "bce_comm", "role": "obverse",
             "local_path": f"ml/canonical_images/{NEW}/obverse_bce.webp"},
            {"op": "upsert", "eurio_id": EXISTING, "source": "numista_api",
             "role": "obverse", "local_path": f"ml/canonical_images/{EXISTING}/obverse_numista.webp"},
        ],
    }


def test_apply_inserts_swaps_and_reparents(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _seed(conn)
    r = _client(store).post("/ingest/referential-fix", json=_diff())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] and body["coins_inserted"] == 1 and body["coins_updated"] == 1
    assert body["canonical_rows"] == 2

    new = conn.execute(
        "SELECT numista_id, is_commemorative, ref_source, currency, status FROM coins WHERE eurio_id=?",
        (NEW,),
    ).fetchone()
    assert new["numista_id"] == 200 and new["is_commemorative"] == 1
    assert new["ref_source"] == "numista" and new["currency"] == "EUR"
    assert new["status"] == "referenced"
    assert conn.execute("SELECT numista_id FROM coins WHERE eurio_id=?", (EXISTING,)).fetchone()[0] == 150

    # canonical : bce_comm re-parenté existing→new ; numista_api ajouté sur existing
    assert conn.execute(
        "SELECT local_path FROM coin_canonical_images WHERE eurio_id=? AND source='bce_comm' AND role='obverse'",
        (NEW,),
    ).fetchone()[0] == f"ml/canonical_images/{NEW}/obverse_bce.webp"
    assert conn.execute(
        "SELECT COUNT(*) FROM coin_canonical_images WHERE eurio_id=? AND source='bce_comm'", (EXISTING,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM coin_canonical_images WHERE eurio_id=? AND source='numista_api'", (EXISTING,)
    ).fetchone()[0] == 1


def test_preflight_divergence_409(tmp_path):
    store = Store(tmp_path / "t.db")
    _seed(store._connection(), existing_nid=999)  # numista_id ≠ attendu (100)  # noqa: SLF001
    r = _client(store).post("/ingest/referential-fix", json=_diff())
    assert r.status_code == 409, r.text
    # aucune row insérée (rollback)
    assert store._connection().execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM coins WHERE eurio_id=?", (NEW,)
    ).fetchone()[0] == 0


def test_reapply_is_conflict_guarded(tmp_path):
    store = Store(tmp_path / "t.db")
    _seed(store._connection())  # noqa: SLF001
    client = _client(store)
    assert client.post("/ingest/referential-fix", json=_diff()).status_code == 200
    # re-POST : la new row existe déjà → preflight 409 (one-shot, pas de double)
    assert client.post("/ingest/referential-fix", json=_diff()).status_code == 409


def test_missing_scope_403(tmp_path):
    store = Store(tmp_path / "t.db")
    _seed(store._connection())  # noqa: SLF001
    client = _client(store, scopes=("ingest:run",))  # pas ingest:write
    assert client.post("/ingest/referential-fix", json=_diff()).status_code == 403


def test_push_referential_fix_noop_without_sync(monkeypatch):
    import client.ingest as ci

    monkeypatch.delenv("EURIO_API_URL", raising=False)
    assert ci.push_referential_fix(_diff()) is None
