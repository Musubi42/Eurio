"""Tri de la file de review par la prédiction DINO — bout en bout, base réelle.

Deux choses sont verrouillées ici, et la seconde est la plus importante :

1. Le tri `order=dino` classe par spread décroissant, et les crops **jamais
   scorés** finissent en queue plutôt qu'en tête (un NULL qui remonte, c'est le
   pire des tris : l'opérateur reçoit d'abord ce dont le modèle ne sait rien).

2. Le filtre `dino_top1_only` fonctionne sur une pièce courante qui n'est PAS
   la plus ancienne de son ère. La banque `2eur_all` indexe une courante sous
   l'eurio_id du plus ancien millésime du groupe ; un filtre naïf sur
   l'identifiant demandé renverrait zéro ligne — une liste vide parfaitement
   plausible, donc une panne muette. Cf. `shared/bank_classes`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from serving.review_queue import repository
from shared.bank_classes import bank_class_ids
from shared.verdict_scope import SUGGESTIONS_ANCHORS_KIND, SUGGESTIONS_ENCODER_VERSION
from store import Store


@pytest.fixture()
def conn(tmp_path):
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.execute(
        "INSERT INTO design_groups (id, designation) "
        "VALUES ('be-albert-t1','BE 2€ Albert II (1er type)')",
    )
    # Une ère à deux millésimes : c'est 1999 qui porte l'ancre, 2007 non.
    c.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id, "
        "is_commemorative, design_group_id) VALUES "
        "('be-1999-std','BE',1999,2.0,1,0,'be-albert-t1')",
    )
    c.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id, "
        "is_commemorative, design_group_id) VALUES "
        "('be-2007-std','BE',2007,2.0,2,0,'be-albert-t1')",
    )
    return c


def _crop(conn, *, ref: str, spread: float | None, top1: str | None) -> str:
    """Un crop en file, éventuellement scoré par la banque des suggestions."""
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        "listing_country, listing_year, storage_path) "
        f"VALUES ('si-{ref}','ebay','r-{ref}','be-2007-std','BE',NULL,'x.jpg')",
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, "
        "storage_status, face) "
        f"VALUES ('a-{ref}','si-{ref}','c.jpg','present','obverse')",
    )
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, kind, lane, "
        "priority, enqueued_at) "
        f"VALUES ('rq-{ref}','a-{ref}','open','single','manual',5,'2026-01-01')",
    )
    if spread is not None:
        conn.execute(
            "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
            "anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim, "
            "spread) VALUES (?,?,?,?,?,?,?,?)",
            (f"a-{ref}", SUGGESTIONS_ENCODER_VERSION, SUGGESTIONS_ANCHORS_KIND,
             10, "[]", top1, 0.8, spread),
        )
    conn.commit()
    return f"rq-{ref}"


def _ids(items) -> list[str]:
    return [i.id for i in items]


def test_tri_par_spread_decroissant_et_non_scores_en_queue(conn):
    _crop(conn, ref="faible", spread=0.02, top1="be-1999-std")
    _crop(conn, ref="net", spread=0.30, top1="be-1999-std")
    _crop(conn, ref="jamais", spread=None, top1=None)

    got = repository.list_queue(
        conn, status="open", limit=10, order="dino", kind="single",
        lane=None, cohort_id=None, eurio_id=None, review_ids=None,
    )
    assert _ids(got) == ["rq-net", "rq-faible", "rq-jamais"]

    # Et le front doit pouvoir DIRE pourquoi : le signal voyage avec l'item.
    assert got[0].sugg_spread == pytest.approx(0.30)


def test_le_tri_par_defaut_ne_change_pas(conn):
    """Garde-fou de non-régression : la seconde jointure ne doit ni réordonner
    ni dupliquer la liste servie aujourd'hui."""
    _crop(conn, ref="a", spread=0.30, top1="be-1999-std")
    _crop(conn, ref="b", spread=None, top1=None)

    base = repository.list_queue(
        conn, status="open", limit=10, order="priority", kind="single",
        lane=None, cohort_id=None, eurio_id=None, review_ids=None,
    )
    assert len(base) == 2  # pas de fan-out de la jointure


def test_palier_de_spread(conn):
    _crop(conn, ref="sous", spread=0.05, top1="be-1999-std")
    _crop(conn, ref="sur", spread=0.15, top1="be-1999-std")

    got = repository.list_queue(
        conn, status="open", limit=10, order="dino", kind="single",
        lane=None, cohort_id=None, eurio_id=None, review_ids=None,
        dino_min_spread=0.10,
    )
    assert _ids(got) == ["rq-sur"]


def test_filtre_top1_sur_une_courante_non_representante(conn):
    """LE test qui attrape le piège : on travaille `be-2007-std`, mais la
    banque connaît l'ère sous `be-1999-std`. Un filtre naïf renverrait []."""
    assert bank_class_ids(conn, "be-2007-std") == ["be-2007-std", "be-1999-std"]

    _crop(conn, ref="ere", spread=0.20, top1="be-1999-std")
    _crop(conn, ref="ailleurs", spread=0.40, top1="fr-2016-autre")

    got = repository.list_queue(
        conn, status="open", limit=10, order="dino", kind="single",
        lane=None, cohort_id=None, eurio_id="be-2007-std", review_ids=None,
        dino_top1_only=True,
    )
    assert _ids(got) == ["rq-ere"], (
        "le crop de l'ère doit remonter : la banque l'indexe sous le plus "
        "ancien millésime, pas sous la pièce demandée"
    )


def test_la_classe_travaillee_passe_devant_un_spread_plus_net(conn):
    """Le critère qui manquait, et qui se voyait à l'écran : trier par le seul
    spread remonte ce dont le modèle est le plus sûr — y compris qu'il ne
    s'agit PAS de la classe. Mesuré en vrai : la file « Philippe » ouvrait sur
    un Spa-Francorchamps 2025 à 0,28. Utile, mais pas ce qu'on vient trancher.
    """
    _crop(conn, ref="autre", spread=0.28, top1="be-2025-spa")
    _crop(conn, ref="laclasse", spread=0.01, top1="be-1999-std")

    got = repository.list_queue(
        conn, status="open", limit=10, order="dino", kind="single",
        lane=None, cohort_id=None, eurio_id="be-2007-std", review_ids=None,
    )
    assert _ids(got) == ["rq-laclasse", "rq-autre"], (
        "la classe travaillée passe devant, même moins nette"
    )
