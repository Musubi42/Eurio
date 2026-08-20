"""La pêche — une file définie par la PRÉDICTION, pas par la cible du scrape.

Le problème que ces tests verrouillent, mesuré le 2026-08-20 sur la base réelle :

    /review-queue?eurio_id=it-2002-…                        57 items,  2 utiles
    périmètre par prédiction (top-1)                       137 items, tous utiles

Une file scopée par `eurio_id` sur une pièce COURANTE sert tout le pool ambigu
du pays et **uniquement des singles** (le code force `kind='single'`) : les
crops de lots — 136 sur 137 ici — sont hors d'atteinte. La pêche les ramène.

Trois choses sont verrouillées, la deuxième étant celle qui débloque le sujet :

1. le périmètre par prédiction REMPLACE celui par cible (il ne s'y ajoute pas) ;
2. il traverse les `kind` : un crop de lot est pêchable ;
3. le compte de la page d'une pièce est celui du préflight, pas un troisième.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from serving.review_queue import repository
from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
)
from store import Store

CLASSE = "it-2euro-standard-t1"


@pytest.fixture()
def conn(tmp_path):
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.execute(
        "INSERT INTO design_groups (id, designation) "
        f"VALUES ('{CLASSE}','IT 2€ standard (1er type)')",
    )
    for eid, year, nid in (("it-2002-std", 2002, 1), ("it-2008-std", 2008, 2)):
        c.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
            " is_commemorative, design_group_id) VALUES (?,?,?,2.0,?,0,?)",
            (eid, "IT", year, nid, CLASSE),
        )
    c.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
        " is_commemorative) VALUES ('de-2009-saarland','DE',2009,2.0,9,1)",
    )
    return c


def _crop(
    conn, ref, *, kind="single", top1=None, spread=None, country="IT",
    target=None, listing_year=None, lane="manual", status="open",
    training_eligible=0, enqueue=True, eurio_id=None, face=None,
):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        "listing_country, listing_year, storage_path) VALUES (?,?,?,?,?,?,?)",
        (f"si-{ref}", "ebay", f"r-{ref}", target, country, listing_year, "x.jpg"),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, "
        "storage_status, resolution_status, training_eligible, eurio_id, face) "
        "VALUES (?,?,?,'present','needs_review',?,?,?)",
        (f"a-{ref}", f"si-{ref}", "c.jpg", training_eligible, eurio_id, face),
    )
    if enqueue:
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, kind, lane, "
            "priority, enqueued_at) VALUES (?,?,?,?,?,5,?)",
            (f"rq-{ref}", f"a-{ref}", status, kind, lane, f"2026-01-{ref[:2]}"),
        )
    if top1 is not None:
        conn.execute(
            "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version,"
            " anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim,"
            " spread) VALUES (?,?,?,?,?,?,?,?)",
            (f"a-{ref}", SUGGESTIONS_ENCODER_VERSION, SUGGESTIONS_ANCHORS_KIND,
             10, json.dumps([{"eurio_id": top1, "sim": 0.8}]), top1, 0.8, spread),
        )
    conn.commit()
    return f"rq-{ref}"


def _peche(conn, **kw):
    kw.setdefault("kind", "all")
    return [
        i.id for i in repository.list_queue(
            conn, status="open", limit=50, order="dino", lane=None,
            cohort_id=None, eurio_id=None, review_ids=None,
            dino_class=CLASSE, **kw,
        )
    ]


def test_la_peche_traverse_les_kind_la_file_par_cible_non(conn):
    """LE test du chantier : le gisement d'une classe standard est en LOTS."""
    _crop(conn, "01lot", kind="lot", top1="it-2002-std", spread=0.30)
    _crop(conn, "02sgl", kind="single", top1="it-2008-std", spread=0.20)

    assert set(_peche(conn)) == {"rq-01lot", "rq-02sgl"}

    # La file par cible, elle, force kind='single' sur une courante : le crop
    # de lot n'y apparaît pas. C'est le comportement d'origine, pas un bug —
    # mais c'est pour ça que la pêche existe.
    par_cible = [
        i.id for i in repository.list_queue(
            conn, status="open", limit=50, order="dino", kind="single",
            lane=None, cohort_id=None, eurio_id="it-2002-std", review_ids=None,
        )
    ]
    assert "rq-01lot" not in par_cible


def test_la_peche_ignore_le_pool_ambigu_pays(conn):
    """Un crop italien que la banque attribue AILLEURS ne doit pas être servi.

    C'est exactement ce que la file par cible faisait : 57 items du pool
    ambigu IT pour 2 utiles."""
    _crop(conn, "03bon", top1="it-2002-std", spread=0.30)
    _crop(conn, "04ail", top1="de-2009-saarland", spread=0.50)

    assert _peche(conn) == ["rq-03bon"]


def test_la_peche_traverse_les_pays_de_listing(conn):
    """Une italienne photographiée dans une annonce allemande est pêchable :
    le pays du LISTING n'est pas le pays de la PIÈCE."""
    _crop(conn, "05de", country="DE", top1="it-2002-std", spread=0.30)
    assert _peche(conn) == ["rq-05de"]


def test_le_rang_elargit_le_filet(conn):
    """La classe en 3ᵉ position : invisible en top-1, atteignable en élargissant.

    C'est le recours d'une classe affamée — BE Philippe n'a que 2 candidats à
    marge en top-1 pour 6 crops à trouver.
    """
    _crop(conn, "06t3", top1="de-2009-saarland", spread=0.05)
    conn.execute(
        "UPDATE image_asset_dino_predictions SET top_k_json = ? "
        "WHERE asset_id = 'a-06t3'",
        (json.dumps([
            {"eurio_id": "de-2009-saarland", "sim": 0.90},
            {"eurio_id": "de-2009-saarland", "sim": 0.85},
            {"eurio_id": "it-2002-std", "sim": 0.80},
        ]),),
    )
    conn.commit()

    assert _peche(conn, dino_rank=1) == []
    assert _peche(conn, dino_rank=3) == ["rq-06t3"]


def test_la_marge_filtre(conn):
    _crop(conn, "07net", top1="it-2002-std", spread=0.30)
    _crop(conn, "08flou", top1="it-2002-std", spread=0.01)

    assert _peche(conn, dino_min_spread=0.10) == ["rq-07net"]


def test_le_tri_reste_du_plus_net_au_plus_flou(conn):
    _crop(conn, "09flou", top1="it-2002-std", spread=0.05)
    _crop(conn, "10net", top1="it-2002-std", spread=0.40)

    assert _peche(conn) == ["rq-10net", "rq-09flou"]


# ─── Le résumé servi à la page d'une pièce ────────────────────────────────


def test_le_resume_separe_les_trois_populations(conn):
    _crop(conn, "11sgl", kind="single", top1="it-2002-std", spread=0.3)
    _crop(conn, "12lot", kind="lot", top1="it-2002-std", spread=0.3)
    # Orphelin : needs_review, AUCUNE ligne de review ouverte → invisible
    # partout. C'est le stock que l'écran ne doit pas taire.
    _crop(conn, "13orp", top1="it-2002-std", spread=0.3, enqueue=False)
    # Tranché et déjà au train : ne doit compter que dans n_training_eligible.
    _crop(conn, "14ok", top1="it-2002-std", spread=0.3, status="done",
          training_eligible=1, eurio_id="it-2002-std", face="obverse")

    s = repository.dino_candidates_summary(conn, dino_class=CLASSE)
    assert (s.n_open_single, s.n_open_lot, s.n_orphans) == (1, 1, 1)
    assert s.orphan_asset_ids == ["a-13orp"]
    assert s.n_training_eligible == 1
    assert set(s.bank_class_ids) == {"it-2002-std", "it-2008-std"}


def test_le_resume_compte_le_train_comme_le_preflight(conn):
    """Le préflight compte `n_ebay` = eBay + training_eligible + fichier présent
    + revers exclu. Un compteur qui dirait autre chose ferait douter des deux.
    """
    _crop(conn, "15rev", top1="it-2002-std", status="done", training_eligible=1,
          eurio_id="it-2002-std", face="reverse")
    _crop(conn, "16avr", top1="it-2002-std", status="done", training_eligible=1,
          eurio_id="it-2008-std", face=None)

    s = repository.dino_candidates_summary(conn, dino_class=CLASSE)
    assert s.n_training_eligible == 1, (
        "le revers commun n'entre jamais au bake : le compter ici ferait "
        "mentir la barre de progression"
    )


def test_le_resume_dit_la_meilleure_marge_de_chaque_file(conn):
    """Un compte seul ment par omission.

    Vécu le 2026-08-20 : la file « 4 à l'unité » d'une classe ESPAGNOLE était
    faite de quatre annonces FRANÇAISES dont la meilleure marge plafonnait à
    0,023 — quatre skips pour rien, et l'impression que l'écran était cassé.
    Le compte dit combien il y a à voir ; la marge dit si ça vaut le coup.
    """
    _crop(conn, "20sf", kind="single", top1="it-2002-std", spread=0.02)
    _crop(conn, "21sf", kind="single", top1="it-2002-std", spread=0.01)
    _crop(conn, "22ln", kind="lot", top1="it-2002-std", spread=0.31)

    s = repository.dino_candidates_summary(conn, dino_class=CLASSE)
    assert (s.n_open_single, s.n_open_lot) == (2, 1)
    assert s.best_spread_single == pytest.approx(0.02)
    assert s.best_spread_lot == pytest.approx(0.31)


def test_une_file_vide_n_a_pas_de_marge(conn):
    """`None` = « pas de candidat », à ne pas confondre avec une marge nulle."""
    _crop(conn, "23lot", kind="lot", top1="it-2002-std", spread=0.20)
    s = repository.dino_candidates_summary(conn, dino_class=CLASSE)
    assert s.n_open_single == 0 and s.best_spread_single is None
