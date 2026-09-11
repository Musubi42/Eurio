"""L'or arrive-t-il dans le canonique, et le gel tient-il RE-5 ?

Une séance d'annotation dure 40 minutes et ne se refait pas. Deux propriétés
comptent ici et rien d'autre :

* **rien ne se perd** — un asset purgé ne fait pas tomber les 59 autres ;
* **rien ne se corrige en douce** — une version gelée refuse l'écriture. RE-5
  dit « aucune annotation n'est corrigée au passage » ; le dire ne suffit pas,
  la garde doit vivre dans le writer.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from store.crop_gold import (
    EDITOR_VERSION,
    OrGele,
    assurer_version,
    enregistrer_annotation,
    enregistrer_lot,
    enregistrer_tirage,
    geler,
    instantane,
    lire,
    lire_tirage,
)
from tests._schema_reel import base_au_schema_reel

ELL = {"cx": 100.0, "cy": 110.0, "a": 50.0, "b": 44.0, "theta": 12.0}


@pytest.fixture()
def conn(tmp_path):
    c = base_au_schema_reel(tmp_path / "or.db")
    c.execute("INSERT INTO source_images (id, source, source_ref, storage_path,"
              " width, height, sha256) VALUES ('si','ebay','r','ebay/x.jpg',900,900,'sha')")
    for i in range(3):
        c.execute("INSERT INTO image_assets (id, source_image_id, crop_index,"
                  " bbox_json, resolution_status, storage_path)"
                  " VALUES (?,?,?,?,'manual','crops/x.png')",
                  (f"ia{i}", "si", i, json.dumps({"x": 1, "y": 2, "w": 3, "h": 4})))
    c.commit()
    yield c
    c.close()


def _ann(aid, **kw):
    return {"asset_id": aid, "ellipse": dict(ELL), **kw}


# ─── l'écriture ─────────────────────────────────────────────────────────────

def test_une_annotation_arrive_en_base(conn):
    assurer_version(conn, "v1")
    assert enregistrer_annotation(conn, _ann("ia0"), actor="po",
                                  gold_version="v1")["statut"] == "ecrit"
    (row,) = lire(conn, "v1")
    assert (row["cx"], row["a"], row["b"]) == (100.0, 50.0, 44.0)
    assert row["actor"] == "po" and row["editor_version"] == EDITOR_VERSION
    # la jointure ramène ce dont le banc a besoin, sans second aller-retour
    assert row["raw_path"] == "ebay/x.jpg" and row["width"] == 900


def test_un_asset_inconnu_ne_fait_pas_tomber_le_lot(conn):
    """Perdre 59 annotations parce que la 60ᵉ pointe un asset purgé serait le
    pire échec possible ici."""
    res = enregistrer_lot(conn, [_ann("ia0"), _ann("fantome"), _ann("ia1")],
                          actor="po", gold_version="v1")
    assert res["comptes"] == {"ecrit": 2, "missing": 1}
    assert res["details"][0]["asset_id"] == "fantome"
    assert len(lire(conn, "v1")) == 2


def test_reannoter_remplace_au_lieu_de_dupliquer(conn):
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    enregistrer_lot(conn, [_ann("ia0", ellipse={**ELL, "a": 60.0})],
                    actor="po", gold_version="v1")
    lignes = lire(conn, "v1")
    assert len(lignes) == 1 and lignes[0]["a"] == 60.0


def test_la_seconde_passe_n_ecrase_pas_la_premiere(conn):
    """La double annotation fixe le PLAFOND du banc. L'écraser détruirait la
    seule borne qui dise ce qu'aucune méthode ne peut dépasser."""
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    enregistrer_lot(conn, [_ann("ia0", passe=2, ellipse={**ELL, "a": 52.0})],
                    actor="po", gold_version="v1")
    assert [(r["passe"], r["a"]) for r in lire(conn, "v1")] == [(1, 50.0), (2, 52.0)]
    assert [r["a"] for r in lire(conn, "v1", passe=2)] == [52.0]


def test_une_ellipse_incomplete_sans_indecidable_est_refusee(conn):
    assurer_version(conn, "v1")
    r = enregistrer_annotation(conn, {"asset_id": "ia0", "ellipse": {"cx": 1}},
                               actor="po", gold_version="v1")
    assert r["statut"] == "invalide"
    assert lire(conn, "v1") == []


def test_un_indecidable_entre_sans_ellipse(conn):
    res = enregistrer_lot(conn, [{"asset_id": "ia0", "indecidable": True}],
                          actor="po", gold_version="v1")
    assert res["comptes"] == {"ecrit": 1}
    assert lire(conn, "v1")[0]["indecidable"] == 1


def test_les_demi_axes_sont_remis_dans_le_bon_ordre(conn):
    """`cv2.fitEllipse` rend (largeur, hauteur), PAS (grand, petit). Laisser
    entrer l'inversion rendrait tout `d = 0,08·a` faux d'un facteur b/a."""
    enregistrer_lot(conn, [_ann("ia0", ellipse={**ELL, "a": 30.0, "b": 70.0})],
                    actor="po", gold_version="v1")
    row = lire(conn, "v1")[0]
    assert (row["a"], row["b"]) == (70.0, 30.0)
    assert row["theta_deg"] == pytest.approx(102.0)   # +90° avec l'échange


# ─── le gel, c'est-à-dire RE-5 ──────────────────────────────────────────────

def test_une_version_gelee_refuse_l_ecriture(conn):
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    geler(conn, "v1", snapshot_sha256="a" * 64)
    with pytest.raises(OrGele, match="NOUVELLE version"):
        enregistrer_lot(conn, [_ann("ia1")], actor="po", gold_version="v1")
    assert len(lire(conn, "v1")) == 1


def test_la_garde_de_gel_vit_au_point_d_ecriture(conn):
    """Toute écriture passe par `enregistrer_annotation` : c'est là que la garde
    doit être, et nulle part ailleurs. Deux gardes qui se couvrent l'une l'autre
    ne seraient tuées par aucune mutation — donc vérifiées par rien."""
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    geler(conn, "v1", snapshot_sha256="a" * 64)
    with pytest.raises(OrGele):
        enregistrer_annotation(conn, _ann("ia1"), actor="po", gold_version="v1")


def test_regeler_le_meme_contenu_est_idempotent(conn):
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    geler(conn, "v1", snapshot_sha256="a" * 64)
    assert geler(conn, "v1", snapshot_sha256="a" * 64)["deja"] is True


def test_regeler_un_contenu_different_est_refuse(conn):
    """Sinon le gel ne prouve rien : on pourrait geler, éditer, re-geler."""
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    geler(conn, "v1", snapshot_sha256="a" * 64)
    with pytest.raises(OrGele, match="déjà gelé"):
        geler(conn, "v1", snapshot_sha256="b" * 64)


def test_assurer_version_ne_degele_jamais(conn):
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    geler(conn, "v1", snapshot_sha256="a" * 64)
    assert assurer_version(conn, "v1")["frozen_at"] is not None


def test_l_instantane_est_deterministe_et_ne_bouge_pas_sur_du_bruit(conn):
    """Deux appels sur le même contenu doivent rendre le même sha256, sinon le
    gel n'atteste rien. Et le temps passé à annoter n'est PAS le contenu."""
    enregistrer_lot(conn, [_ann("ia1"), _ann("ia0")], actor="po", gold_version="v1")
    a = instantane(conn, "v1")
    enregistrer_lot(conn, [_ann("ia0", secondes=999.0)], actor="po",
                    gold_version="v1")
    assert instantane(conn, "v1") == a


def test_l_instantane_bouge_quand_la_geometrie_bouge(conn):
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    a = instantane(conn, "v1")
    enregistrer_lot(conn, [_ann("ia0", ellipse={**ELL, "a": 51.0})],
                    actor="po", gold_version="v1")
    assert instantane(conn, "v1") != a


# ─── la contrainte lean ─────────────────────────────────────────────────────

def test_le_module_s_importe_sans_les_paquets_lourds():
    """Un import lourd au niveau module fait skipper le routeur ENTIER, en
    silence. C'est le défaut qui a tué `backfill_denom --reject` en prod le
    2026-08-27 : `review.review_lanes` tire `training.foundation` en TRANSITIF,
    et un contrôle des imports DIRECTS ne le voit pas. On fait donc l'import
    RÉEL, en sous-process, avec les lourds rendus introuvables.
    """
    code = (
        "import sys\n"
        "class Bloqueur:\n"
        "    def find_module(self, nom, chemin=None):\n"
        "        if nom.split('.')[0] in ('cv2','torch','training'):\n"
        "            raise ImportError('bloqué par le test : ' + nom)\n"
        "sys.meta_path.insert(0, Bloqueur())\n"
        "import store.crop_gold, serving.crop_gold_routes\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


# ─── le TIRAGE : ce qu'il y a À annoter (D12) ───────────────────────────────

HINT = {"cx": 450.0, "cy": 449.0, "r": 440.0}
PREFILL = {"cx": 453.5, "cy": 450.3, "a": 401.4, "b": 394.6, "theta_deg": 21.5}


def _img(aid, **kw):
    base = {"asset_id": aid, "role": "tirage", "rn": 1,
            "strate_tiree": "S1_facile", "width": 900, "height": 900,
            "hint": dict(HINT), "prefill": dict(PREFILL),
            "prefill_reason": "too_circular:0.983"}
    base.update(kw)
    return base


def test_le_tirage_arrive_en_base_avec_ce_qu_il_faut_pour_l_afficher(conn):
    res = enregistrer_tirage(conn, [_img("ia0")], gold_version="v1",
                             requete_sha256="req")
    assert res["n"] == 1 and res["ignorees"] == []
    (row,) = lire_tirage(conn, "v1")
    assert (row["role"], row["strate_tiree"], row["rn"]) == ("tirage", "S1_facile", 1)
    assert (row["hint_cx"], row["hint_r"]) == (450.0, 440.0)
    assert row["prefill_a"] == 401.4 and row["prefill_reason"] == "too_circular:0.983"
    # la jointure ramène de quoi fabriquer une URL servable — le front hébergé
    # n'a pas accès au disque du Mac
    assert row["raw_path"] == "ebay/x.jpg" and row["source"] == "ebay"
    assert row["source_image_id"] == "si"


def test_publier_deux_fois_met_a_jour_au_lieu_de_doubler(conn):
    enregistrer_tirage(conn, [_img("ia0")], gold_version="v1")
    enregistrer_tirage(conn, [_img("ia0", role="reserve", rn=3)],
                       gold_version="v1")
    lignes = lire_tirage(conn, "v1")
    assert len(lignes) == 1 and (lignes[0]["role"], lignes[0]["rn"]) == ("reserve", 3)


def test_un_asset_inconnu_est_ignore_sans_faire_tomber_le_tirage(conn):
    """Même doctrine que les annotations : perdre 83 images parce que la 84ᵉ
    pointe un asset purgé serait le pire échec possible ici."""
    res = enregistrer_tirage(conn, [_img("ia0"), _img("fantome"), _img("ia1")],
                             gold_version="v1")
    assert res["n"] == 2 and res["ignorees"] == ["fantome"]
    assert {l["asset_id"] for l in lire_tirage(conn, "v1")} == {"ia0", "ia1"}


def test_le_tirage_cree_la_version_avec_sa_requete(conn):
    enregistrer_tirage(conn, [_img("ia0")], gold_version="v1",
                       requete_sha256="req-a")
    assert conn.execute("SELECT requete_sha256 FROM crop_gold_versions"
                        " WHERE gold_version='v1'").fetchone()[0] == "req-a"


def test_un_tirage_d_une_autre_requete_est_refuse(conn):
    """Un tirage et sa version sortent de la MÊME requête d'échantillonnage.
    Les découpler rendrait le jeu irreproductible EN LE LAISSANT CROIRE
    reproductible — ce qui est pire que pas de requête du tout (RE-5)."""
    enregistrer_tirage(conn, [_img("ia0")], gold_version="v1",
                       requete_sha256="req-a")
    with pytest.raises(ValueError, match="MÊME requête"):
        enregistrer_tirage(conn, [_img("ia1")], gold_version="v1",
                           requete_sha256="req-b")
    assert len(lire_tirage(conn, "v1")) == 1


def test_republier_la_meme_requete_passe(conn):
    enregistrer_tirage(conn, [_img("ia0")], gold_version="v1",
                       requete_sha256="req-a")
    assert enregistrer_tirage(conn, [_img("ia1")], gold_version="v1",
                              requete_sha256="req-a")["n"] == 1


def test_une_version_gelee_refuse_le_tirage(conn):
    """Le tirage fixe la POPULATION mesurée : le changer après le gel change ce
    que le banc mesure, exactement ce que RE-5 interdit."""
    enregistrer_tirage(conn, [_img("ia0")], gold_version="v1")
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v1")
    geler(conn, "v1", snapshot_sha256="a" * 64)
    with pytest.raises(OrGele, match="NOUVELLE version"):
        enregistrer_tirage(conn, [_img("ia1")], gold_version="v1")
    assert len(lire_tirage(conn, "v1")) == 1


def test_le_prefill_est_remis_dans_le_bon_ordre(conn):
    """`cv2.fitEllipse` rend (largeur, hauteur), PAS (grand, petit) — et le
    pré-remplissage vient précisément de là. Inversé, il donnerait à
    l'annotateur une ellipse tournée de 90°."""
    enregistrer_tirage(conn, [_img("ia0", prefill={**PREFILL, "a": 300.0,
                                                  "b": 400.0, "theta_deg": 12.0})],
                       gold_version="v1")
    row = lire_tirage(conn, "v1")[0]
    assert (row["prefill_a"], row["prefill_b"]) == (400.0, 300.0)
    assert row["prefill_theta_deg"] == pytest.approx(102.0)


def test_un_prefill_absent_entre_en_bloc_a_null(conn):
    """`measure_tilt` peut échouer : l'annotateur part alors du cercle de
    production. La RAISON, elle, reste — elle dit sur quelles strates le
    pré-remplissage propose mal."""
    enregistrer_tirage(conn, [_img("ia0", prefill=None,
                                   prefill_reason="no_contour")],
                       gold_version="v1")
    row = lire_tirage(conn, "v1")[0]
    assert row["prefill_cx"] is None and row["prefill_theta_deg"] is None
    assert row["prefill_reason"] == "no_contour"


def test_un_prefill_a_moitie_rempli_ne_passe_pas_en_base(conn):
    """Tout ou rien : une proposition à moitié remplie serait une proposition
    au jugé. Le store le range à NULL AVANT que la contrainte ne morde."""
    enregistrer_tirage(conn, [_img("ia0", prefill={"cx": 1.0, "cy": 2.0})],
                       gold_version="v1")
    assert lire_tirage(conn, "v1")[0]["prefill_cx"] is None


def test_le_filtre_de_role_ne_rend_que_ce_qu_on_demande(conn):
    """La réserve remplace un « indécidable » ; elle n'est pas dans la séance.
    Servir les deux en vrac ferait annoter 84 images au lieu de 60."""
    enregistrer_tirage(conn, [_img("ia0"), _img("ia1", role="reserve")],
                       gold_version="v1")
    assert [l["asset_id"] for l in lire_tirage(conn, "v1", "tirage")] == ["ia0"]
    assert [l["asset_id"] for l in lire_tirage(conn, "v1", "reserve")] == ["ia1"]
    assert len(lire_tirage(conn, "v1")) == 2


def test_l_ordre_de_la_seance_est_le_meme_pour_deux_annotateurs(conn):
    """'tirage' avant 'reserve', puis strate, puis rang. Un ordre instable
    ferait dériver le temps par image entre deux passes, qui est la mesure du
    plafond du banc."""
    enregistrer_tirage(conn, [
        _img("ia0", role="tirage", strate_tiree="S1_facile", rn=2),
        _img("ia1", role="reserve", strate_tiree="S1_facile", rn=1),
        _img("ia2", role="tirage", strate_tiree="S2_capsule", rn=1),
    ], gold_version="v1")
    # ni l'ordre d'insertion ni un tri par `asset_id` ne donnent cette suite :
    # sinon le test passerait aussi sans ORDER BY, et ne garderait rien.
    assert [l["asset_id"] for l in lire_tirage(conn, "v1")] == ["ia0", "ia2", "ia1"]
    assert [(l["role"], l["strate_tiree"], l["rn"]) for l in lire_tirage(conn, "v1")] == [
        ("tirage", "S1_facile", 2), ("tirage", "S2_capsule", 1),
        ("reserve", "S1_facile", 1)]


# ─── les familles, en étiquettes (D16, migration 0021) ──────────────────────

def _familles_brutes(conn):
    return [r[0] for r in conn.execute(
        "SELECT familles FROM crop_gold_annotations ORDER BY asset_id")]


def test_les_familles_arrivent_triees_dedoublonnees_et_se_relisent_en_liste(conn):
    res = enregistrer_lot(conn, [_ann("ia0", familles=["multi", "capsule", "multi"])],
                          actor="po", gold_version="v2")
    assert res["comptes"] == {"ecrit": 1}
    # trié et dédoublonné : deux fois le même geste = le même octet, sinon
    # l'empreinte du gel bouge sur du bruit
    assert _familles_brutes(conn) == ['["capsule", "multi"]']
    (ligne,) = lire(conn, "v2")
    assert ligne["familles"] == ["capsule", "multi"]


def test_facile_est_une_liste_vide_pas_une_absence(conn):
    enregistrer_lot(conn, [_ann("ia0", familles=[]), _ann("ia1")],
                    actor="po", gold_version="v2")
    par_asset = {l["asset_id"]: l["familles"] for l in lire(conn, "v2")}
    assert par_asset == {"ia0": [], "ia1": None}


def test_une_famille_inconnue_est_refusee_sans_faire_tomber_le_lot(conn):
    res = enregistrer_lot(conn, [_ann("ia0", familles=["dessin"]),
                                 _ann("ia1", familles=["oblique"])],
                          actor="po", gold_version="v2")
    assert res["comptes"] == {"invalide": 1, "ecrit": 1}
    assert "dessin" in res["details"][0]["raison"]
    assert [l["asset_id"] for l in lire(conn, "v2")] == ["ia1"]


def test_un_client_qui_ne_porte_pas_les_familles_ne_les_efface_pas(conn):
    # l'outil local `serve.py` est antérieur à D16 : il renvoie une annotation
    # sans le champ. Il ne doit pas remettre à « non étiquetée » ce que la page
    # a posé.
    enregistrer_lot(conn, [_ann("ia0", familles=["oblique"])], actor="po", gold_version="v2")
    enregistrer_lot(conn, [_ann("ia0")], actor="po", gold_version="v2")
    assert lire(conn, "v2")[0]["familles"] == ["oblique"]
    # …mais un client qui les porte les remplace, y compris par « facile »
    enregistrer_lot(conn, [_ann("ia0", familles=[])], actor="po", gold_version="v2")
    assert lire(conn, "v2")[0]["familles"] == []


def test_l_instantane_bouge_quand_les_familles_bougent(conn):
    enregistrer_lot(conn, [_ann("ia0", familles=["capsule"])], actor="po", gold_version="v2")
    avant = instantane(conn, "v2")
    enregistrer_lot(conn, [_ann("ia0", familles=["capsule", "multi"])],
                    actor="po", gold_version="v2")
    assert instantane(conn, "v2") != avant
    assert '"familles":["capsule","multi"]' in instantane(conn, "v2")
