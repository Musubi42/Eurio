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


# ─── le TIRAGE servi au front hébergé (D12) ─────────────────────────────────

HINT = {"cx": 450.0, "cy": 449.0, "r": 440.0}
PREFILL = {"cx": 453.5, "cy": 450.3, "a": 401.4, "b": 394.6, "theta_deg": 21.5}


def _img(aid, **kw):
    base = {"asset_id": aid, "role": "tirage", "rn": 1,
            "strate_tiree": "S1_facile", "width": 900, "height": 900,
            "hint": dict(HINT), "prefill": dict(PREFILL),
            "prefill_reason": "too_circular:0.983"}
    base.update(kw)
    return base


def _tirage(*images, **kw):
    return {"images": list(images), **kw}


def _relire_tirage(chemin):
    con = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM crop_gold_tirage")]
    finally:
        con.close()


def test_publier_le_tirage_puis_le_relire(env):
    app, cli, chemin = env
    r = cli.put("/crop-gold/v1/tirage",
                json=_tirage(_img("ia0"), requete_sha256="req"))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "gold_version": "v1", "n": 1, "ignorees": []}
    # relecture SQL directe : on ne croit pas la réponse HTTP sur parole
    assert [l["asset_id"] for l in _relire_tirage(chemin)] == ["ia0"]


def test_le_contrat_du_get_est_celui_contre_lequel_le_front_est_ecrit(env):
    """Contrat FIGÉ : `hint` et `prefill` imbriqués, `prefill` null EN BLOC, et
    un `raw_url` servable. Le changer casse la séance sans rien dire."""
    app, cli, _ = env
    cli.put("/crop-gold/v1/tirage", json=_tirage(_img("ia0")))
    corps = cli.get("/crop-gold/v1/tirage").json()
    assert set(corps) == {"gold_version", "n", "images"}
    assert corps["gold_version"] == "v1" and corps["n"] == 1
    (image,) = corps["images"]
    assert set(image) == {"asset_id", "role", "rn", "strate_tiree", "width",
                          "height", "hint", "prefill", "prefill_reason",
                          "source", "source_image_id", "raw_url"}
    assert image["hint"] == HINT
    assert image["prefill"] == PREFILL
    assert image["source"] == "ebay" and image["source_image_id"] == "si"
    assert image["raw_url"]


def test_le_verdict_humain_n_est_jamais_servi(env):
    """L'annotateur qui voit le verdict le confirme au lieu de tracer ce qu'il
    voit — et RE-4 ne mesure plus rien. Ce n'est pas un oubli."""
    app, cli, _ = env
    cli.put("/crop-gold/v1/tirage", json=_tirage(_img("ia0")))
    (image,) = cli.get("/crop-gold/v1/tirage").json()["images"]
    assert "verdict" not in image and "resolution_status" not in image


def test_un_prefill_absent_est_null_en_bloc_mais_garde_sa_raison(env):
    app, cli, _ = env
    cli.put("/crop-gold/v1/tirage",
            json=_tirage(_img("ia0", prefill=None, prefill_reason="no_contour")))
    (image,) = cli.get("/crop-gold/v1/tirage").json()["images"]
    assert image["prefill"] is None and image["prefill_reason"] == "no_contour"


def test_le_filtre_de_role_et_l_ordre_de_la_seance(env):
    app, cli, _ = env
    cli.put("/crop-gold/v1/tirage", json=_tirage(
        _img("ia1", role="reserve", rn=1),
        _img("ia0", role="tirage", strate_tiree="S2_capsule", rn=1)))
    tous = cli.get("/crop-gold/v1/tirage").json()
    # 'tirage' d'abord, quel que soit l'ordre d'envoi ET l'ordre des `asset_id`
    assert [i["asset_id"] for i in tous["images"]] == ["ia0", "ia1"]
    seance = cli.get("/crop-gold/v1/tirage?role=tirage").json()
    assert seance["n"] == 1 and seance["images"][0]["asset_id"] == "ia0"
    assert cli.get("/crop-gold/v1/tirage?role=reserve").json()["n"] == 1
    # un rôle inventé ne rend pas « tout » en silence
    assert cli.get("/crop-gold/v1/tirage?role=nawak").status_code == 422


def test_un_asset_inconnu_est_ignore_pas_un_404_global(env):
    app, cli, chemin = env
    r = cli.put("/crop-gold/v1/tirage", json=_tirage(_img("ia0"), _img("fantome")))
    assert r.status_code == 200
    assert r.json()["n"] == 1 and r.json()["ignorees"] == ["fantome"]
    assert len(_relire_tirage(chemin)) == 1


def test_un_tirage_sur_une_version_gelee_rend_409_pas_500(env):
    """Un or gelé n'est pas une panne : c'est une réponse. Le front doit
    pouvoir la lire et le dire."""
    app, cli, chemin = env
    cli.put("/crop-gold/v1/annotations", json=_lot("ia0"))
    cli.post("/crop-gold/v1/geler", json={})
    r = cli.put("/crop-gold/v1/tirage", json=_tirage(_img("ia0")))
    assert r.status_code == 409 and "NOUVELLE version" in r.json()["detail"]
    assert _relire_tirage(chemin) == []


def test_un_tirage_d_une_autre_requete_rend_409(env):
    app, cli, chemin = env
    cli.put("/crop-gold/v1/tirage",
            json=_tirage(_img("ia0"), requete_sha256="req-a"))
    r = cli.put("/crop-gold/v1/tirage",
                json=_tirage(_img("ia1"), requete_sha256="req-b"))
    assert r.status_code == 409 and "MÊME requête" in r.json()["detail"]
    assert [l["asset_id"] for l in _relire_tirage(chemin)] == ["ia0"]


def test_publier_le_tirage_exige_review_arbitrate(env):
    """Le tirage fixe la POPULATION mesurée : c'est une pièce de la référence,
    un ami invité ne la pose pas. Mais il peut la LIRE — la séance se tient
    depuis le front hébergé, donc depuis un téléphone."""
    app, cli, _ = env
    app.dependency_overrides[require_principal] = lambda: _principal(
        {"lab:read", "review:write"}, user="ami")
    assert cli.put("/crop-gold/v1/tirage",
                   json=_tirage(_img("ia0"))).status_code == 403
    assert cli.get("/crop-gold/v1/tirage").status_code == 200


def test_lire_le_tirage_exige_lab_read(env):
    app, cli, _ = env
    app.dependency_overrides[require_principal] = lambda: _principal({"coins:read"})
    assert cli.get("/crop-gold/v1/tirage").status_code == 403


def test_un_tirage_absent_ne_plante_pas(env):
    app, cli, _ = env
    assert cli.get("/crop-gold/jamais-creee/tirage").json() == {
        "gold_version": "jamais-creee", "n": 0, "images": []}
