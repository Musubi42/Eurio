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
    geler,
    instantane,
    lire,
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
