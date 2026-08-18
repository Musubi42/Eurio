"""Route lean de réglage des seuils (`serving/thresholds_routes.py`) bout-en-bout.

Miroir de ``test_lab_read_routes.py`` : on vérifie le CÂBLAGE réel de l'image
lean — dep ``db_connection`` (via ``EURIO_DB_PATH``), scopes ``lab:read`` /
``lab:write``, commit effectif, 404 sur cohorte inconnue. La logique de
résolution est testée séparément dans ``test_thresholds.py``.

Le test qui compte le plus est le dernier : **une base sans la migration doit
répondre les défauts**, pas 500. C'est la situation d'un canonique qu'on n'a pas
encore redéployé, et d'une réplique en retard.
"""
from __future__ import annotations

import sqlite3
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

MIGRATION = ML_DIR / "serving/migrations/0006_training_thresholds.sql"


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes=set(scopes), auth_method="api_token",
    )


def _client(scopes=("lab:read", "lab:write")):
    from serving import thresholds_routes

    app = FastAPI()
    app.include_router(thresholds_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal(scopes)
    return TestClient(app)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    conn = Store(path)._connection()  # noqa: SLF001
    conn.executescript(MIGRATION.read_text())
    conn.execute(
        "INSERT INTO experiment_cohorts (id, name, eurio_ids_json, status) "
        "VALUES ('c1', 'cohort-1', '[]', 'draft')",
    )
    conn.commit()
    monkeypatch.setenv("EURIO_DB_PATH", str(path))
    return path


def test_lecture_sert_les_defauts_quand_rien_nest_regle(db):
    r = _client().get("/lab/thresholds")
    assert r.status_code == 200
    body = r.json()
    assert body["effective"]["min_real"] == 10
    assert body["effective"]["source"]["min_real"] == "code"
    assert body["global"] == {}


def test_ecriture_globale_puis_relecture(db):
    c = _client()
    r = c.put("/lab/thresholds", json={"key": "min_real", "value": 25, "note": "vague 2"})
    assert r.status_code == 200, r.text
    assert r.json()["state"]["effective"]["min_real"] == 25

    # Persisté : une nouvelle requête (nouvelle connexion) le voit → le commit
    # a bien eu lieu. Sans ça, la façade « marcherait » et n'écrirait rien.
    again = c.get("/lab/thresholds").json()
    assert again["effective"]["min_real"] == 25
    assert again["effective"]["source"]["min_real"] == "global"
    assert again["history"][0]["new_value"] == 25


def test_surcharge_de_cohorte_puis_liberation(db):
    c = _client()
    c.put("/lab/thresholds", json={"key": "min_real", "value": 25})
    c.put("/lab/cohorts/c1/thresholds", json={"key": "min_real", "value": 50})

    scoped = c.get("/lab/cohorts/c1/thresholds").json()
    assert scoped["effective"]["min_real"] == 50
    assert scoped["effective"]["source"]["min_real"] == "cohort"

    # value=null libère la cohorte : elle retombe sur le global.
    r = c.put("/lab/cohorts/c1/thresholds", json={"key": "min_real", "value": None})
    assert r.status_code == 200
    assert r.json()["state"]["effective"]["min_real"] == 25


def test_cohorte_acceptee_par_nom(db):
    """Le reste des routes lab accepte id OU name — sinon un lien qui marche
    ailleurs 404 ici, et on croit à un bug de seuils."""
    r = _client().get("/lab/cohorts/cohort-1/thresholds")
    assert r.status_code == 200
    assert r.json()["cohort_id"] == "c1"


def test_404_403_et_valeurs_refusees(db):
    c = _client()
    assert c.put("/lab/cohorts/nope/thresholds", json={"key": "min_real", "value": 12}).status_code == 404
    assert c.put("/lab/thresholds", json={"key": "min_real", "value": 0}).status_code == 400
    assert c.put("/lab/thresholds", json={"key": "plancher", "value": 12}).status_code == 400
    # Le global se change, il ne se retire pas.
    assert c.put("/lab/thresholds", json={"key": "min_real", "value": None}).status_code == 400

    lecteur = _client(scopes=("lab:read",))
    assert lecteur.get("/lab/thresholds").status_code == 200
    assert lecteur.put("/lab/thresholds", json={"key": "min_real", "value": 12}).status_code == 403


def test_base_sans_migration_repond_les_defauts(tmp_path, monkeypatch):
    """Le filet. Un canonique pas encore redéployé, une réplique en retard : la
    table n'existe pas. La lecture doit servir les constantes, pas planter."""
    path = tmp_path / "bare.db"
    sqlite3.connect(path).close()
    monkeypatch.setenv("EURIO_DB_PATH", str(path))

    r = _client().get("/lab/thresholds")
    assert r.status_code == 200
    assert r.json()["effective"] == {
        "m_per_class": 4,
        "min_real": 10,
        "training_target": 100,
        "source": {"m_per_class": "code", "min_real": "code", "training_target": "code"},
    }
    assert r.json()["history"] == []
