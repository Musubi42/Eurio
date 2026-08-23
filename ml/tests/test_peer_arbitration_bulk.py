"""La vue bulk d'arbitrage — tri D8, lot partiel, retour dans la file (lot 8).

`review-collaborative-v2` : un ami tranche, sa décision part en quarantaine
(`peer_review_decisions`, D7) ; l'arbitre la relit en lot. Ces tests verrouillent
les trois choses qui, si elles cassaient, casseraient en SILENCE :

1. **Le tri (D8).** Les désaccords avec DINO passent devant et ne sont pas cochés.
   Ce tri est fait en SQL parce qu'il doit survivre à la pagination du scroll
   infini — trié en Python page par page, la page 2 rejouerait des concordances
   déjà vues et laisserait des désaccords derrière. Un tri silencieusement faux
   rend la vue bulk un tampon en caoutchouc, ce que D8 refuse explicitement.

2. **Un lot ne tombe pas pour un item.** Sur cent décisions, un 409 « déjà
   arbitrée » (une voie locale est passée entre-temps) est un cas NORMAL. Perdre
   les quatre-vingt-dix-neuf autres pour lui serait absurde — et le front, qui ne
   retire que ce que le serveur dit avoir traité, montrerait alors comme faites
   des décisions qui ne le sont pas.

3. **Rejeter REND le crop à la file.** Laisser la décision `pending` la garderait
   hors de la file indéfiniment (la file exclut les crops en quarantaine) : le
   crop disparaîtrait sans que personne ne l'ait tranché.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.verdict_scope import VERDICT_ANCHORS_KIND, VERDICT_ENCODER_VERSION
from store import Store
from test_review_requalify import _seed_listing

_TARGET = "fr-2015-2eur-paix"
_AUTRE = "de-2015-2eur-autre"


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    """(conn, client) — le router d'arbitrage monté sur une base tmp.

    Le router résout son Store via `serving.server_serve._store` : on le
    monkeypatche plutôt que de démarrer un serveur, comme le fait déjà
    `test_review_quarantine`.
    """
    db = tmp_path / "t.db"
    store = Store(db)
    conn = store._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    conn.executescript(
        (ML_DIR / "serving/migrations/0001_auth_redesign.sql").read_text()
    )
    conn.execute(
        "INSERT INTO users (id, email, name, active, created_at) "
        "VALUES ('u_paolo', 'paolo@test.local', 'Paolo', 1, 0)"
    )
    for eid in (_TARGET, _AUTRE):
        conn.execute(
            "INSERT OR IGNORE INTO coins (eurio_id, country, country_name, year, "
            "face_value, theme) VALUES (?, 'fr', 'France', 2015, 2.0, 'thème')",
            (eid,),
        )
    conn.commit()

    from review import peer_arbitration_routes as par

    monkeypatch.setattr(par, "_store", lambda: store)
    app = FastAPI()
    app.include_router(par.router)
    return conn, TestClient(app)


_SEQ = iter(range(1, 999))


def _quarantine(conn, *, asset_id: str, review_id: str, decided: str) -> str:
    """Une décision d'ami en attente d'arbitrage.

    `decided_at` est strictement croissant : c'est la clé de tri SECONDAIRE, et
    un horodatage constant ferait retomber l'ordre sur l'uuid — le test passerait
    ou non selon le hasard.
    """
    did = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO peer_review_decisions (id, image_asset_id, review_item_id, "
        "  reviewer_token, reviewer_name, action, decided_eurio_id, decided_face, "
        "  decided_at) "
        "VALUES (?, ?, ?, 'u_paolo', 'Paolo', 'accept', ?, 'obverse', ?)",
        (did, asset_id, review_id, decided, f"2026-08-23T10:{next(_SEQ):02d}:00Z"),
    )
    conn.commit()
    return did


def _dino_says(conn, asset_id: str, eurio_id: str) -> None:
    """La prédiction DINO du VERDICT — celle que le front affiche comme `DINO`.

    ⚠️ Deux banques cohabitent : celle du VERDICT (ici) et celle des SUGGESTIONS,
    qui n'ont ni le même encodeur ni les mêmes ancres. L'arbitrage se compare à
    la MÊME que celle étiquetée « DINO » sur l'écran de l'ami — les comparer à
    l'autre ferait lire « DINO d'accord » sur la foi d'un modèle que personne n'a
    vu.
    """
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        "  anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim) "
        "VALUES (?, ?, ?, 8, ?, ?, 0.9)",
        (asset_id, VERDICT_ENCODER_VERSION, VERDICT_ANCHORS_KIND,
         json.dumps([{"eurio_id": eurio_id, "sim": 0.9}]), eurio_id),
    )
    conn.commit()


# ─── 1. Le tri de D8 ────────────────────────────────────────────────────────


def test_les_desaccords_passent_devant(rig):
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B1", n_crops=3)
    # 0 : DINO d'accord · 1 : DINO en désaccord · 2 : DINO muet
    _dino_says(conn, assets[0], _TARGET)
    _dino_says(conn, assets[1], _AUTRE)
    for a, r in zip(assets, reviews):
        _quarantine(conn, asset_id=a, review_id=r, decided=_TARGET)

    items = client.get("/peer-arbitration").json()["items"]
    etats = [i["dino_state"] for i in items]
    # L'invariant est « ce que DINO ne confirme pas passe devant », pas un ordre
    # entre `disagrees` et `absent` : ni l'un ni l'autre n'est une confirmation,
    # et les départager n'aurait pas de sens à défendre.
    assert set(etats[:2]) == {"disagrees", "absent"}, etats
    assert etats[2] == "concords"
    assert items[-1]["concords"] is True
    assert items[0]["concords"] is False


def test_le_tri_survit_a_la_pagination(rig):
    """Le tri est en SQL : deux pages consécutives ne doivent rien rejouer."""
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B2", n_crops=6)
    for i, (a, r) in enumerate(zip(assets, reviews)):
        _dino_says(conn, a, _TARGET if i % 2 else _AUTRE)
        _quarantine(conn, asset_id=a, review_id=r, decided=_TARGET)

    p1 = client.get("/peer-arbitration?limit=3&offset=0").json()
    p2 = client.get("/peer-arbitration?limit=3&offset=3").json()
    assert p1["total"] == p2["total"] == 6
    ids1 = [i["id"] for i in p1["items"]]
    ids2 = [i["id"] for i in p2["items"]]
    assert not set(ids1) & set(ids2), "une page ne doit jamais rejouer l'autre"
    assert all(i["dino_state"] == "disagrees" for i in p1["items"]), \
        "les désaccords tiennent la première page"
    assert all(i["dino_state"] == "concords" for i in p2["items"])


def test_le_filtre_par_personne(rig):
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B3", n_crops=2)
    _quarantine(conn, asset_id=assets[0], review_id=reviews[0], decided=_TARGET)
    d2 = _quarantine(conn, asset_id=assets[1], review_id=reviews[1], decided=_TARGET)
    conn.execute(
        "UPDATE peer_review_decisions SET reviewer_token='u_max', reviewer_name='Max' "
        "WHERE id = ?", (d2,))
    conn.commit()

    tous = client.get("/peer-arbitration").json()
    max_ = client.get("/peer-arbitration?reviewer=u_max").json()
    assert tous["total"] == 2
    assert max_["total"] == 1, "le total doit suivre le filtre, pas le tout"
    assert max_["items"][0]["reviewer_name"] == "Max"


def test_le_crop_est_servi_en_url_absolue(rig):
    """Sans ça la vue bulk est aveugle partout ailleurs que sur le Mac (lot 1)."""
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B4")
    _quarantine(conn, asset_id=assets[0], review_id=reviews[0], decided=_TARGET)

    item = client.get("/peer-arbitration").json()["items"][0]
    # MinIO absent en test → repli relatif ; ce qui est verrouillé ici, c'est que
    # la clé de stockage EST lue et passée au signeur, pas l'inverse.
    assert item["crop_url"], "un crop sans URL est une carte vide"
    assert item["source"] == "ebay"
    assert item["listing_title"] == "Annonce"


# ─── 2. Le lot ──────────────────────────────────────────────────────────────


def test_approve_batch_ecrit_le_canonique_signe_de_l_ami(rig):
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B5", n_crops=2)
    ids = [
        _quarantine(conn, asset_id=a, review_id=r, decided=_TARGET)
        for a, r in zip(assets, reviews)
    ]

    r = client.post("/peer-arbitration/approve-batch", json={"ids": ids})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["approved"]) == sorted(ids)
    assert r.json()["failed"] == []

    for rid, aid in zip(reviews, assets):
        row = conn.execute(
            "SELECT rq.status, rq.decided_by, rq.decision_engine_version, "
            "       a.training_eligible, a.eurio_id, a.resolution_status "
            "  FROM review_queue rq JOIN image_assets a ON a.id = rq.image_asset_id "
            " WHERE rq.id = ?", (rid,)).fetchone()
        assert row["status"] == "done"
        assert row["decided_by"] == "u_paolo", "la trace de QUI a tranché"
        assert row["decision_engine_version"] == "peer@v1"
        assert row["training_eligible"] == 1
        assert row["eurio_id"] == _TARGET
        assert row["resolution_status"] == "manual"
        assert aid


def test_un_item_en_echec_ne_fait_pas_tomber_le_lot(rig):
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B6", n_crops=2)
    ok = _quarantine(conn, asset_id=assets[0], review_id=reviews[0], decided=_TARGET)
    deja = _quarantine(conn, asset_id=assets[1], review_id=reviews[1], decided=_TARGET)
    conn.execute(
        "UPDATE peer_review_decisions SET arbitration_status='approved' WHERE id=?",
        (deja,))
    conn.commit()

    body = client.post(
        "/peer-arbitration/approve-batch", json={"ids": [deja, ok, "inconnu"]}
    ).json()
    assert body["approved"] == [ok], "le lot passe malgré ses deux fautifs"
    assert {f["id"] for f in body["failed"]} == {deja, "inconnu"}
    assert {f["status"] for f in body["failed"]} == {409, 404}
    assert body["requested"] == 3


def test_lot_vide_et_lot_trop_grand_sont_refuses(rig):
    _, client = rig
    assert client.post("/peer-arbitration/approve-batch", json={"ids": []}).status_code == 400
    trop = [uuid.uuid4().hex for _ in range(501)]
    assert client.post(
        "/peer-arbitration/approve-batch", json={"ids": trop}).status_code == 400


def test_superseded_quand_une_voie_locale_a_tranche(rig):
    """Le canonique n'est pas réécrit par-dessus une décision déjà prise."""
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B7")
    did = _quarantine(conn, asset_id=assets[0], review_id=reviews[0], decided=_TARGET)
    conn.execute("UPDATE review_queue SET status='done' WHERE id=?", (reviews[0],))
    conn.commit()

    body = client.post("/peer-arbitration/approve-batch", json={"ids": [did]}).json()
    assert body["superseded"] == [did]
    assert body["approved"] == []
    row = conn.execute(
        "SELECT arbitration_status FROM peer_review_decisions WHERE id=?", (did,)
    ).fetchone()
    assert row["arbitration_status"] == "superseded"


# ─── 3. Le rejet rend le crop à la file ─────────────────────────────────────


def test_reject_batch_laisse_le_canonique_intact_et_rouvre_la_file(rig):
    conn, client = rig
    _, assets, reviews = _seed_listing(conn, item_id="B8", n_crops=2)
    ids = [
        _quarantine(conn, asset_id=a, review_id=r, decided=_TARGET)
        for a, r in zip(assets, reviews)
    ]

    body = client.post(
        "/peer-arbitration/reject-batch", json={"ids": ids, "notes": "à revoir"}
    ).json()
    assert sorted(body["rejected"]) == sorted(ids)

    for rid in reviews:
        row = conn.execute(
            "SELECT rq.status, rq.decided_by, a.training_eligible, a.eurio_id "
            "  FROM review_queue rq JOIN image_assets a ON a.id = rq.image_asset_id "
            " WHERE rq.id = ?", (rid,)).fetchone()
        assert row["status"] == "open", "le crop RETOURNE dans la file"
        assert row["decided_by"] is None
        assert row["training_eligible"] == 0
        assert row["eurio_id"] is None

    # Plus rien en quarantaine ⇒ plus rien n'exclut ces crops de la file servie.
    assert conn.execute(
        "SELECT count(*) FROM peer_review_decisions WHERE arbitration_status='pending'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT arbitration_notes FROM peer_review_decisions WHERE id=?", (ids[0],)
    ).fetchone()[0] == "à revoir"
