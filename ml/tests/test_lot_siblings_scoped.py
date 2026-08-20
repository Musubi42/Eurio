"""Le chaînage des lots — « suivant » doit rester dans le périmètre.

Deux pannes que ces tests figent, et elles étaient bien vivantes le 2026-08-20 :

1. **Côté canonique, le chaînage n'existait pas.** `repository.get_lot_detail`
   renvoyait `prev_listing_key=None, next_listing_key=None` **en dur**, avec un
   commentaire « coûteux à reproduire ici ». Or le front lit le canonique : les
   flèches ← / → de la page lot étaient grisées en permanence. Vérifié en
   appelant l'API de prod avant correctif — les deux clés étaient nulles.

2. **Côté API locale, `_siblings` parcourait TOUTE la file lot ouverte** (5413
   items), sans le moindre scope. Enchaîner depuis une classe en sortait au
   premier clic.

L'invariant qui rattrape les deux : la nav lit **exactement** l'ordre que
`GET /review-queue/lots` a annoncé pour ce périmètre. Sinon « suivant » emmène
ailleurs que ce que l'écran promettait — et personne ne le remarque avant
d'avoir trié cent crops hors sujet.
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
    c.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
        f" is_commemorative, design_group_id) VALUES ('it-2002-std','IT',2002,"
        f"2.0,1,0,'{CLASSE}')",
    )
    c.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
        " is_commemorative) VALUES ('de-2009-saarland','DE',2009,2.0,9,1)",
    )
    return c


def _lot(conn, ref, *, day, top1, spread=0.30, target=None):
    """Un listing d'un crop, en file lot ouverte. `day` fixe l'ordre."""
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        "listing_country, storage_path) VALUES (?,?,?,?,'IT','x.jpg')",
        (f"si-{ref}", "ebay", ref, target),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, "
        f"storage_status) VALUES ('a-{ref}','si-{ref}','c.jpg','present')",
    )
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, kind, lane, "
        "priority, enqueued_at) VALUES (?,?, 'open','lot','manual',5,?)",
        (f"rq-{ref}", f"a-{ref}", f"2026-01-{day:02d}"),
    )
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version,"
        " anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim,"
        " spread) VALUES (?,?,?,?,?,?,?,?)",
        (f"a-{ref}", SUGGESTIONS_ENCODER_VERSION, SUGGESTIONS_ANCHORS_KIND, 10,
         json.dumps([{"eurio_id": top1, "sim": 0.8}]), top1, 0.8, spread),
    )
    conn.commit()
    return ref  # listing_key == source_ref hors payload eBay


def test_le_chainage_existe_desormais(conn):
    """Le correctif du `None` en dur : deux lots en file, le premier a un
    suivant."""
    _lot(conn, "aaa", day=1, top1="it-2002-std")
    _lot(conn, "bbb", day=2, top1="it-2002-std")

    prev, nxt = repository.lot_siblings(conn, "aaa")
    assert (prev, nxt) == (None, "bbb")

    detail = repository.get_lot_detail(conn, "aaa")
    assert detail.next_listing_key == "bbb", (
        "get_lot_detail renvoyait None en dur côté image lean — le front "
        "n'avait donc jamais de bouton « suivant » en prod"
    )


def test_suivant_reste_dans_le_perimetre_peche(conn):
    _lot(conn, "aaa", day=1, top1="it-2002-std")
    _lot(conn, "zzz", day=2, top1="de-2009-saarland")   # hors classe
    _lot(conn, "ccc", day=3, top1="it-2002-std")

    prev, nxt = repository.lot_siblings(conn, "aaa", dino_class=CLASSE)
    assert nxt == "ccc", "le lot hors classe doit être sauté, pas servi"

    # Sans périmètre, l'ancien comportement : on tombe sur le hors-sujet.
    assert repository.lot_siblings(conn, "aaa")[1] == "zzz"


def test_l_ordre_de_la_nav_est_celui_de_la_liste(conn):
    """L'invariant qui tient tout : ce que la liste annonce, la nav le suit."""
    for i, ref in enumerate(("aaa", "bbb", "ccc", "ddd"), start=1):
        _lot(conn, ref, day=i, top1="it-2002-std")

    items, _ = repository.list_lots(
        conn, limit=50, offset=0, cohort_id=None, target_eurio_id=None,
        design_group=None, dino_class=CLASSE,
    )
    annonce = [it.listing_key for it in items]

    parcouru = [annonce[0]]
    while True:
        nxt = repository.lot_siblings(conn, parcouru[-1], dino_class=CLASSE)[1]
        if nxt is None:
            break
        parcouru.append(nxt)
    assert parcouru == annonce


def test_la_marge_resserre_aussi_la_nav(conn):
    _lot(conn, "aaa", day=1, top1="it-2002-std", spread=0.30)
    _lot(conn, "flou", day=2, top1="it-2002-std", spread=0.01)
    _lot(conn, "ccc", day=3, top1="it-2002-std", spread=0.30)

    nxt = repository.lot_siblings(
        conn, "aaa", dino_class=CLASSE, dino_min_spread=0.10,
    )[1]
    assert nxt == "ccc"


def test_un_lot_hors_perimetre_ne_devine_pas(conn):
    """On vient de trancher tous ses crops, ou on l'a ouvert par son URL : il
    n'est plus dans la file. On ne saute pas au hasard — on le dit."""
    _lot(conn, "aaa", day=1, top1="it-2002-std")
    _lot(conn, "zzz", day=2, top1="de-2009-saarland")

    assert repository.lot_siblings(conn, "zzz", dino_class=CLASSE) == (None, None)


def test_la_liste_compte_les_crops_de_la_classe(conn):
    """`n_matching_crops` dit ce qu'il y a à trouver dans le coffret — et vaut
    None hors pêche : « pas demandé » ne se confond pas avec « zéro »."""
    _lot(conn, "aaa", day=1, top1="it-2002-std")

    items, total = repository.list_lots(
        conn, limit=50, offset=0, cohort_id=None, target_eurio_id=None,
        design_group=None, dino_class=CLASSE,
    )
    assert total == 1 and items[0].n_matching_crops == 1

    items, _ = repository.list_lots(
        conn, limit=50, offset=0, cohort_id=None, target_eurio_id=None,
        design_group=None,
    )
    assert items[0].n_matching_crops is None
