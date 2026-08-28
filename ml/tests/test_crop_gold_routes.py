"""Les routes de l'or : qui peut écrire, et le gel est-il opposable ?

Le point qui compte : **le `sha256` du gel est calculé par le SERVEUR**. Un gel
dont le client fournit l'empreinte n'atteste rien — c'est la même leçon que L1,
où `before_r` est relu en base au lieu d'être cru sur parole (le client envoyait
200, la ligne porte 102,6).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving import crop_gold_routes
from serving.auth_principal import Principal, require_principal
from serving.deps import db_connection
from store.crop_gold import instantane
from tests._schema_reel import base_au_schema_reel

ELL = {"cx": 100.0, "cy": 110.0, "a": 50.0, "b": 44.0, "theta": 12.0}


def _principal(scopes, user="po"):
    return Principal(user_id=user, email=f"{user}@test.local", roles=["owner"],
                     scopes=set(scopes), auth_method="api_token")


@pytest.fixture()
def env(tmp_path):
    chemin = tmp_path / "or.db"
    c = base_au_schema_reel(chemin)
    c.execute("INSERT INTO source_images (id, source, source_ref, storage_path,"
              " width, height, sha256) VALUES ('si','ebay','r','ebay/x.jpg',900,900,'sha')")
    for i in range(2):
        c.execute("INSERT INTO image_assets (id, source_image_id, crop_index,"
                  " bbox_json, resolution_status, storage_path)"
                  " VALUES (?,?,?,?,'manual','crops/x.png')",
                  (f"ia{i}", "si", i, json.dumps({"x": 1, "y": 2, "w": 3, "h": 4})))
    c.commit()
    c.close()

    def _conn():
        con = sqlite3.connect(str(chemin), check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
        finally:
            con.close()

    app = FastAPI()
    app.include_router(crop_gold_routes.router)
    app.dependency_overrides[db_connection] = _conn
    app.dependency_overrides[require_principal] = lambda: _principal(
        {"lab:read", "review:write", "review:arbitrate"})
    return app, TestClient(app), chemin


def _relire(chemin):
    con = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM crop_gold_annotations")]
    finally:
        con.close()


def _lot(*assets, **kw):
    return {"annotations": [{"asset_id": a, "ellipse": dict(ELL), **kw}
                            for a in assets]}


def test_ecrire_puis_relire(env):
    app, cli, chemin = env
    r = cli.put("/crop-gold/v1/annotations",
                json={**_lot("ia0", "ia1"), "requete_sha256": "req"})
    assert r.status_code == 200 and r.json()["comptes"] == {"ecrit": 2}
    # relecture SQL directe : on ne croit pas la réponse HTTP sur parole
    assert {l["asset_id"] for l in _relire(chemin)} == {"ia0", "ia1"}
    g = cli.get("/crop-gold/v1").json()
    assert g["n"] == 2 and g["version"]["requete_sha256"] == "req"


def test_l_acteur_ne_peut_pas_venir_du_client(env):
    """Le client n'a aucun moyen de signer l'or au nom de quelqu'un d'autre —
    et la garde est le SCHÉMA, pas un contrôle à l'exécution : `AnnotationIn`
    n'a pas de champ `actor`, donc pydantic le jette avant toute logique.
    Ce test verrouille l'absence du champ ; l'ajouter rouvrirait le trou."""
    assert "actor" not in crop_gold_routes.AnnotationIn.model_fields
    app, cli, chemin = env
    cli.put("/crop-gold/v1/annotations",
            json={"annotations": [{"asset_id": "ia0", "ellipse": dict(ELL),
                                   "actor": "quelqu-un-d-autre"}]})
    assert {l["actor"] for l in _relire(chemin)} == {"po"}


def test_ecrire_exige_review_arbitrate_pas_review_write(env):
    """L'or est la RÉFÉRENCE contre laquelle on juge. Un ami invité tranche des
    crops (`review:write`) ; il ne fixe pas la référence."""
    app, cli, _ = env
    app.dependency_overrides[require_principal] = lambda: _principal(
        {"lab:read", "review:write"}, user="ami")
    assert cli.put("/crop-gold/v1/annotations", json=_lot("ia0")).status_code == 403
    # …mais il peut REGARDER : la planche est faite pour être vue
    assert cli.get("/crop-gold/v1").status_code == 200


def test_lire_exige_lab_read(env):
    app, cli, _ = env
    app.dependency_overrides[require_principal] = lambda: _principal({"coins:read"})
    assert cli.get("/crop-gold/v1").status_code == 403


def test_le_sha_du_gel_est_calcule_par_le_serveur(env):
    app, cli, chemin = env
    cli.put("/crop-gold/v1/annotations", json=_lot("ia0"))
    r = cli.post("/crop-gold/v1/geler", json={"snapshot_key": "gold-crop/v1.json"})
    assert r.status_code == 200
    con = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    attendu = hashlib.sha256(instantane(con, "v1").encode()).hexdigest()
    ligne = dict(con.execute("SELECT * FROM crop_gold_versions").fetchone())
    con.close()
    assert r.json()["snapshot_sha256"] == attendu == ligne["snapshot_sha256"]
    assert ligne["snapshot_key"] == "gold-crop/v1.json" and ligne["frozen_at"]


def test_une_version_gelee_rend_409_pas_500(env):
    """Un or gelé n'est pas une panne : c'est une réponse. Le front doit
    pouvoir la lire et le dire."""
    app, cli, chemin = env
    cli.put("/crop-gold/v1/annotations", json=_lot("ia0"))
    cli.post("/crop-gold/v1/geler", json={})
    r = cli.put("/crop-gold/v1/annotations", json=_lot("ia1"))
    assert r.status_code == 409 and "NOUVELLE version" in r.json()["detail"]
    assert len(_relire(chemin)) == 1


def test_geler_une_version_inconnue_rend_404(env):
    app, cli, _ = env
    assert cli.post("/crop-gold/fantome/geler", json={}).status_code == 404


def test_l_instantane_est_servi_avec_son_sha(env):
    app, cli, _ = env
    cli.put("/crop-gold/v1/annotations", json=_lot("ia0"))
    r = cli.get("/crop-gold/v1/instantane").json()
    assert r["sha256"] == hashlib.sha256(r["contenu"].encode()).hexdigest()
    assert json.loads(r["contenu"])["annotations"][0]["asset_id"] == "ia0"


def test_une_version_absente_ne_plante_pas(env):
    app, cli, _ = env
    r = cli.get("/crop-gold/jamais-creee").json()
    assert r["n"] == 0 and r["version"] is None


def test_chaque_ligne_porte_une_url_d_image(env):
    """La planche doit s'afficher depuis le front HÉBERGÉ, qui n'a pas accès au
    disque du Mac. Sans URL servable, la galerie est aveugle hors de la machine
    du ML — c'est le défaut que `_raw_url` corrige côté review."""
    app, cli, _ = env
    cli.put("/crop-gold/v1/annotations", json=_lot("ia0"))
    (ligne,) = cli.get("/crop-gold/v1").json()["annotations"]
    assert ligne["raw_url"]
    assert ligne["raw_path"] == "ebay/x.jpg" and ligne["source_image_id"] == "si"
