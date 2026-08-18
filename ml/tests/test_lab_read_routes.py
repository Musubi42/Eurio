"""C3 — route lean funnel-lecture (`serving/lab_read_routes.py`) bout-en-bout.

Miroir de ``test_funnel_writes.py`` (C2a, les écritures) : vérifie le câblage
réel de l'image lean — dep ``db_connection`` (via ``EURIO_DB_PATH``), scope
``lab:read``, forme de la réponse (état-DB-portable seulement, aucun champ
dérivé GPU/FS), et le 404/403. La logique SQL est testée séparément dans
``test_funnel_read.py`` (miroir de ``test_decisions_parity.py``).

Ajoute aussi le filet anti-contamination lean (blueprint blocker #3) : importer
la chaîne de modules servie sur l'image VPS ne doit tirer NI numpy NI torch NI
cv2 — vérifié dans un sous-process frais (pas de pollution par les autres
modules déjà importés dans la session pytest).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from store import Store
from test_decisions_parity import _seed_asset


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["reviewer"],
        scopes=set(scopes), auth_method="api_token",
    )


def _make_client(db, scopes=("lab:read",)):
    from serving import lab_read_routes

    app = FastAPI()
    app.include_router(lab_read_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal(scopes)
    return TestClient(app)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    return conn, db


def _coin_with_numista(conn, eurio_id, numista_id=100001) -> None:
    """Un coin résolvable par `store.class_resolver` (nécessite un numista_id
    non-NULL) — distinct du `_coin` de test_decisions_parity, qui n'en pose
    pas et laisserait la classe non-résolue (unresolved) côté funnel."""
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value, "
        "numista_id) VALUES (?, 'FR', 2001, 2.0, ?)",
        (eurio_id, numista_id),
    )


def _seed_cohort(conn, cohort_id="c1", name="cohort-1", eurio_id="fr-2001-2eur-x"):
    import json

    _coin_with_numista(conn, eurio_id)
    conn.execute(
        "INSERT INTO experiment_cohorts (id, name, eurio_ids_json, status) "
        "VALUES (?, ?, ?, 'frozen')",
        (cohort_id, name, json.dumps([eurio_id])),
    )


def test_training_crops_state_200(env):
    conn, db = env
    _seed_cohort(conn)
    _seed_asset(conn, "a1", eurio_id="fr-2001-2eur-x", status="manual", training=1)
    client = _make_client(db)

    r = client.get("/lab/cohorts/c1/training-crops")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cohort_id"] == "c1"
    assert body["cohort_name"] == "cohort-1"
    assert body["min_real"] == 10
    assert len(body["classes"]) == 1
    cls = body["classes"][0]
    assert cls["member_eurio_ids"] == ["fr-2001-2eur-x"]
    assert len(cls["crops"]) == 1
    crop = cls["crops"][0]
    assert crop["asset_id"] == "a1"
    assert crop["eurio_id"] == "fr-2001-2eur-x"
    assert crop["training_eligible"] is True


def test_training_crops_state_resolves_by_name(env):
    conn, db = env
    _seed_cohort(conn, cohort_id="c-id", name="cohort-by-name")
    client = _make_client(db)
    r = client.get("/lab/cohorts/cohort-by-name/training-crops")
    assert r.status_code == 200, r.text
    assert r.json()["cohort_id"] == "c-id"


def test_training_crops_state_excludes_derived_fields(env):
    """Blocker #1/#2 : la réponse lean ne contient aucun champ dérivé GPU
    (r_at_1/confused_with/intruder_*) ni FS (has_numista_ref/n_bce_ref)."""
    conn, db = env
    _seed_cohort(conn)
    _seed_asset(conn, "a1", eurio_id="fr-2001-2eur-x")
    client = _make_client(db)

    body = client.get("/lab/cohorts/c1/training-crops").json()
    assert "r_at_1" not in body and "confused_with" not in body and "scan" not in body
    cls = body["classes"][0]
    forbidden = {
        "has_numista_ref", "n_bce_ref", "r_at_1", "r_at_1_prev", "r_at_1_delta",
        "confused_with", "n_real_last_bake", "n_real_prev_bake",
    }
    assert not (forbidden & cls.keys())
    crop = cls["crops"][0]
    assert not any(k.startswith("intruder_") for k in crop)


def test_training_crops_state_404_unknown_cohort(env):
    conn, db = env
    client = _make_client(db)
    assert client.get("/lab/cohorts/nope/training-crops").status_code == 404


def test_training_crops_state_missing_scope_403(env):
    conn, db = env
    _seed_cohort(conn)
    client = _make_client(db, scopes=())  # authentifié mais sans lab:read
    assert client.get("/lab/cohorts/c1/training-crops").status_code == 403


def test_training_crops_state_wrong_scope_403(env):
    """Un scope `review:write` (écriture) ne donne pas accès à la lecture
    funnel lean — les deux scopes sont volontairement distincts."""
    conn, db = env
    _seed_cohort(conn)
    client = _make_client(db, scopes=("review:write",))
    assert client.get("/lab/cohorts/c1/training-crops").status_code == 403


# ─── Blocker #3 : contamination lean (numpy/torch/cv2) ──────────────────────


_LEAN_IMPORT_CHECK = """
import sys
sys.path.insert(0, {ml_dir!r})
import store.funnel  # noqa: F401
import store.funnel_constants  # noqa: F401
import store.class_resolver  # noqa: F401
import store.decisions  # noqa: F401
import serving.lab_read_models  # noqa: F401
import serving.lab_read_routes  # noqa: F401
import store.thresholds  # noqa: F401
import serving.thresholds_routes  # noqa: F401
leaked = {{m for m in ("numpy", "torch", "cv2") if m in sys.modules}}
assert not leaked, f"lean import chain pulled in: {{leaked}}"
print("OK")
"""


def test_lab_read_chain_does_not_import_numpy_torch_cv2():
    """Filet anti-contamination (blocker #3) : la chaîne d'imports servie sur
    l'image lean VPS (store.funnel + store.funnel_constants +
    store.class_resolver + serving.lab_read_routes/_models + store.thresholds +
    serving.thresholds_routes) ne doit tirer NI
    numpy NI torch NI cv2 — sinon l'image lean (sans ces deps lourdes) casse
    au démarrage. Vérifié dans un sous-process frais pour ne pas être faussé
    par d'autres tests de la même session pytest qui auraient déjà importé
    ``training.*``."""
    script = _LEAN_IMPORT_CHECK.format(ml_dir=str(ML_DIR))
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(ML_DIR),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
