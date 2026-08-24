"""``GET /me/review-stats`` — les deux compteurs personnels d'un reviewer.

Ce qui est verrouillé ici, et pourquoi chaque point est une décision produit
plutôt qu'un détail d'implémentation (``ACCUEIL-AMI.md`` §4, tranché avec le PO
le 2026-08-24) :

1. **Les compteurs ne redescendent JAMAIS.** Un rejet d'arbitrage ne retire rien
   à personne — ni à l'effort (la ligne de quarantaine reste) ni à l'effet (une
   décision rejetée n'a jamais écrit ``decided_by``).
2. **Une image triée compte UNE fois**, même quand l'arbitrage l'approuve et
   écrit ``decided_by`` avec l'identité de l'ami : sans dédoublonnage, le
   compteur d'un ami bondirait le jour où le PO arbitre, alors qu'il n'a rien
   fait de plus.
3. **L'arbitre a des compteurs, lui aussi.** Ses décisions n'entrent pas en
   quarantaine : sans la seconde source, son accueil afficherait zéro.
4. **« Contribué à », pas « ajouté ».** Deux amis qui ont nourri la même pièce
   la comptent tous les deux. S'approprier la pièce mentirait dès le deuxième.
5. **Un crop DÉJÀ bâti en banque compte encore.** C'est la contribution la plus
   forte qui soit ; l'exclure ferait disparaître le travail d'un ami au moment
   précis où il porte ses fruits.
6. **« Complétée » veut dire la même chose que sur `/besoin`.** Le verdict vient
   du même ``_build`` — le test d'équivalence le prouve plutôt que de le croire.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from serving.me_review_stats_routes import router as me_router
from store import Store

KIND = "2eur_all"
ENC = "dinov2-vitl14"
BUILD = "b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0"

FULL = "fr-2015-2eur-paix"        # 7 fps + 1 acquis de l'ami → complétée
NEEDY = "de-2016-2eur-sachsen"    # 2 fps → loin de la cible
AMI = "u_ami"
AUTRE = "u_autre"


def _coin(conn, eid, country):
    conn.execute(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value,"
        " is_commemorative, theme) VALUES (?,?,?,2016,2.0,1,'thème')",
        (eid, country, country),
    )


def _asset(conn, ref, *, eligible=0, face=None, status="present", etiquette=None):
    """Un crop. `etiquette` = la classe que la décision a écrite dans
    `image_assets.eurio_id` — c'est elle qui fait l'ACQUIS (D15), pas le top-1
    du modèle. Une décision réelle l'écrit toujours ; un crop non tranché, non.
    """
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, storage_path)"
        " VALUES (?,'ebay',?,'x.jpg')", (f"si-{ref}", f"r-{ref}"),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path,"
        " storage_status, training_eligible, face, eurio_id, resolution_status)"
        " VALUES (?,?,'c.jpg',?,?,?,?,?)",
        (f"a-{ref}", f"si-{ref}", status, eligible,
         face if face is not None else ("obverse" if etiquette else None),
         etiquette, "manual" if etiquette else "pending_match"),
    )
    return f"a-{ref}"


def _predict(conn, aid, top1):
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version,"
        " anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim,"
        " spread) VALUES (?,?,?,10,?,?,0.8,0.2)",
        (aid, ENC, KIND, json.dumps([{"eurio_id": top1, "sim": 0.8}]), top1),
    )


def _bank(conn, class_id, n_fps):
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, encoder_version,"
        " class_id, eurio_id, method, build_id, built_at)"
        " VALUES (?,?,?,?,'canonical',?, '2026-08-24 10:00:00')",
        (KIND, ENC, class_id, class_id, BUILD),
    )
    for i in range(n_fps):
        aid = _asset(conn, f"ref-{class_id}-{i}")
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version,"
            " class_id, eurio_id, asset_id, method, rank, build_id, built_at)"
            " VALUES (?,?,?,?,?,'fps',?,?, '2026-08-24 10:00:00')",
            (KIND, ENC, class_id, class_id, aid, i, BUILD),
        )


def _decided(conn, ref, top1, *, by, eligible=1, face=None, etiquette=None):
    """Une décision ARRIVÉE au canonique : `decided_by` porte son auteur.

    Elle écrit aussi l'étiquette du crop — par défaut celle que le modèle
    proposait (`top1`), qui est le cas nominal : l'opérateur accepte la
    suggestion. `etiquette=` pour le cas où il tranche autrement.
    """
    aid = _asset(conn, ref, eligible=eligible, face=face,
                 etiquette=etiquette if etiquette is not None else top1)
    _predict(conn, aid, top1)
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, decided_by)"
        " VALUES (?,?,'done',?)", (f"rq-{ref}", aid, by),
    )
    return aid


def _quarantaine(conn, ref, top1, *, by, status="pending", aid=None):
    """Une décision d'ami en quarantaine — `arbitration_status` au choix."""
    if aid is None:
        aid = _asset(conn, ref)
        _predict(conn, aid, top1)
    conn.execute(
        "INSERT INTO peer_review_decisions (id, image_asset_id, reviewer_token,"
        " reviewer_name, action, decided_at, imported_at, arbitration_status)"
        " VALUES (?,?,?,'Ami','accept','2026-08-24','2026-08-24',?)",
        (f"prd-{ref}", aid, by, status),
    )
    return aid


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    conn.executescript(
        (ML_DIR / "serving/migrations/0012_peer_review_une_seule_decision_pendante.sql")
        .read_text()
    )
    _coin(conn, FULL, "FR")
    _coin(conn, NEEDY, "DE")
    _bank(conn, FULL, 7)    # 7 fps : il manque UN exemplaire pour la cible 8
    _bank(conn, NEEDY, 2)
    conn.commit()
    return conn


def _client(user_id=AMI, scopes=("review:read",)) -> TestClient:
    app = FastAPI()
    app.include_router(me_router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id=user_id, email=f"{user_id}@test.local", roles=["reviewer"],
        scopes=set(scopes), auth_method="api_token",
    )
    return TestClient(app)


def _stats(user_id=AMI):
    r = _client(user_id).get("/me/review-stats")
    assert r.status_code == 200, r.text
    return r.json()


# ─── L'effort ───────────────────────────────────────────────────────────────


def test_l_effort_compte_des_la_decision_sans_attendre_l_arbitrage(env):
    """C'est tout l'objet du compteur : un ami qui trie un dimanche soir doit
    voir son chiffre bouger le soir même, pas la semaine suivante."""
    conn = env
    _quarantaine(conn, "q1", NEEDY, by=AMI)
    _quarantaine(conn, "q2", NEEDY, by=AMI)
    conn.commit()
    assert _stats()["n_sorted"] == 2


def test_un_rejet_d_arbitrage_ne_decremente_rien(env):
    """Décision produit (§4) : les compteurs comptent ce qu'il a FAIT, sans
    consulter l'issue. Un rejet laisse la ligne — donc le compte."""
    conn = env
    _quarantaine(conn, "r1", NEEDY, by=AMI, status="rejected")
    _quarantaine(conn, "r2", NEEDY, by=AMI, status="superseded")
    conn.commit()
    assert _stats()["n_sorted"] == 2


def test_une_image_approuvee_ne_compte_pas_deux_fois(env):
    """L'arbitrage écrit `decided_by` avec l'identité de l'AMI (lot 8) et laisse
    la ligne de quarantaine. Sans UNION, le compteur d'un ami bondirait le jour
    où le PO arbitre — alors qu'il n'a rien fait de plus ce jour-là."""
    conn = env
    aid = _decided(conn, "a1", NEEDY, by=AMI)
    _quarantaine(conn, "a1", NEEDY, by=AMI, status="approved", aid=aid)
    conn.commit()
    assert _stats()["n_sorted"] == 1


def test_l_arbitre_a_des_compteurs_lui_aussi(env):
    """Ses décisions n'entrent jamais en quarantaine. Sans la seconde source,
    son propre accueil afficherait zéro."""
    conn = env
    _decided(conn, "adm1", NEEDY, by=AUTRE)
    conn.commit()
    assert _stats(AUTRE)["n_sorted"] == 1


def test_le_travail_d_un_autre_ne_compte_pas_pour_soi(env):
    conn = env
    _quarantaine(conn, "x1", NEEDY, by=AUTRE)
    conn.commit()
    assert _stats()["n_sorted"] == 0


# ─── L'effet ────────────────────────────────────────────────────────────────


def test_l_effet_compte_les_pieces_completees_pas_les_images(env):
    """7 fps + 1 acquis de l'ami = 8 = la cible → `pleine`. NEEDY reste loin."""
    conn = env
    _decided(conn, "e1", FULL, by=AMI)
    _decided(conn, "e2", NEEDY, by=AMI)
    conn.commit()
    s = _stats()
    assert s["n_classes_completed"] == 1
    assert s["n_classes_touched"] == 2


def test_l_effet_n_attend_pas_le_rebuild(env):
    """`have` est FIGÉ entre deux `build_dino_anchors`. Le compte se fait sur
    `have + accepted_pending` — sinon un ami qui complète une pièce ne le voit
    pas avant le rebuild suivant, qui peut être dans une semaine."""
    conn = env
    aid = _decided(conn, "e1", FULL, by=AMI)
    in_bank = conn.execute(
        "SELECT COUNT(*) FROM dino_class_references WHERE asset_id = ?", (aid,),
    ).fetchone()[0]
    assert in_bank == 0, "le crop n'est PAS en banque — c'est le point du test"
    conn.commit()
    assert _stats()["n_classes_completed"] == 1


def test_une_decision_en_quarantaine_ne_produit_aucun_effet(env):
    """Sans arbitrage, rien d'autre que l'effort ne bouge (§4). Ce n'est pas un
    bug, c'est le prix de la quarantaine : `accepted_pending` exige
    `training_eligible = 1`, qu'une décision en quarantaine n'écrit PAS."""
    conn = env
    _quarantaine(conn, "q1", FULL, by=AMI)
    conn.commit()
    s = _stats()
    assert s["n_sorted"] == 1
    assert s["n_classes_completed"] == 0
    assert s["n_classes_touched"] == 0


def test_deux_amis_contribuent_a_la_meme_piece(env):
    """« Contribué à », pas « ajouté » : une pièce se complète à plusieurs. Un
    compteur qui s'approprierait la pièce se contredirait entre deux écrans."""
    conn = env
    _decided(conn, "c1", FULL, by=AMI)
    _decided(conn, "c2", FULL, by=AUTRE)
    conn.commit()
    assert _stats(AMI)["n_classes_completed"] == 1
    assert _stats(AUTRE)["n_classes_completed"] == 1


def test_un_crop_deja_bati_en_banque_compte_encore(env):
    """`_accepted_pending_by_class` exclut les crops déjà bâtis pour ne pas
    recompter ce que `have` compte — raison qui ne vaut PAS ici : c'est la
    contribution la plus forte qui soit."""
    conn = env
    aid = _decided(conn, "b1", FULL, by=AMI)
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, encoder_version,"
        " class_id, eurio_id, asset_id, method, rank, build_id, built_at)"
        " VALUES (?,?,?,?,?,'fps',9,?, '2026-08-24 10:00:00')",
        (KIND, ENC, FULL, FULL, aid, BUILD),
    )
    conn.commit()
    s = _stats()
    assert s["n_classes_touched"] == 1
    assert s["n_classes_completed"] == 1


def test_le_revers_commun_ne_compte_pas(env):
    """Le builder l'ignore : le compter promettrait un exemplaire qui n'arrivera
    jamais. Même règle que `shared.class_need`."""
    conn = env
    _decided(conn, "rev", FULL, by=AMI, face="reverse")
    conn.commit()
    assert _stats()["n_classes_touched"] == 0


def test_une_decision_non_eligible_ne_nourrit_rien(env):
    """Refuser la qualité d'une image est du travail (donc de l'effort), mais
    n'ajoute aucun exemplaire (donc aucun effet)."""
    conn = env
    _decided(conn, "ko", FULL, by=AMI, eligible=0)
    conn.commit()
    s = _stats()
    assert s["n_sorted"] == 1
    assert s["n_classes_touched"] == 0


# ─── Le contrat avec `/besoin` ──────────────────────────────────────────────


def test_completee_veut_dire_la_meme_chose_que_sur_besoin(env):
    """Le verdict n'est pas réécrit ici. S'il divergeait, un écran dirait
    « 6 pièces complétées » pendant que l'autre en montrerait 5, sans que rien
    ne soit faux nulle part — le genre d'écart qui coûte une soirée."""
    from shared.class_need import all_needs, needs_for_classes

    conn = env
    _decided(conn, "e1", FULL, by=AMI)
    _decided(conn, "e2", NEEDY, by=AMI)
    conn.commit()

    par_classe = {
        n.class_id: n.bottleneck
        for n in needs_for_classes(
            conn, {FULL, NEEDY}, anchors_kind=KIND, encoder_version=ENC)
    }
    global_ = {
        n.class_id: n.bottleneck
        for n in all_needs(conn, anchors_kind=KIND, encoder_version=ENC)
    }
    assert par_classe == {c: global_[c] for c in par_classe}
    assert global_[FULL] == "pleine"


def test_une_banque_introuvable_ne_ment_pas(env):
    """`/class-need` rend 409 (671 classes en `scrape` serait plausible et faux).
    Ici, 0 pièce complétée EST la réponse exacte — et l'effort, qui ne dépend
    d'aucune banque, reste juste."""
    conn = env
    _decided(conn, "e1", FULL, by=AMI)
    conn.commit()
    r = _client().get("/me/review-stats?anchors_kind=2eur_commemo"
                      "&encoder_version=dinov2-vits14")
    assert r.status_code == 200, r.text
    assert r.json()["n_classes_completed"] == 0
    assert r.json()["n_sorted"] == 1


def test_la_banque_lue_est_nommee(env):
    """Sans ça, deux lectures d'un même chiffre à deux builds différents se
    lisent comme un désaccord."""
    s = _stats()
    assert s["anchors_kind"] == KIND
    assert s["encoder_version"] == ENC


def test_le_scope_est_review_read(env):
    """Voir ce qu'on a fait soi-même n'est pas arbitrer : un ami doit pouvoir
    lire ses propres compteurs."""
    r = _client(scopes=("coins:read",)).get("/me/review-stats")
    assert r.status_code == 403, r.text


# ─── Le montage ─────────────────────────────────────────────────────────────


def test_la_route_est_montee_des_DEUX_cotes():
    """Piège n°2 de REPRISE.md : `serving/server.py` ≠ `serving/server_serve.py`.
    Le lean (VPS) est celui qui sert un ami ; le local est celui sur lequel on
    développe. Une route montée d'un seul côté marche exactement là où personne
    n'en a besoin.

    On vérifie la SOURCE et non l'app : importer `server_serve` déclenche le
    boot complet (DB canonique, migrations, auth, MinIO), hors de portée d'un
    test unitaire — même convention que `test_serve_router_order`.
    """
    for f in ("server_serve.py", "server.py"):
        src = (ML_DIR / "serving" / f).read_text(encoding="utf-8")
        assert "me_review_stats_router" in src, f"routeur absent de {f}"
        assert "app.include_router(me_review_stats_router)" in src, (
            f"importé mais pas monté dans {f} — le pire des cas : "
            "aucune erreur au boot, un 404 crédible à l'appel"
        )
