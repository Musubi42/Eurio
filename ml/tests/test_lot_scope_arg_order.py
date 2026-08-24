"""L'ordre des args de `_lot_scope` suit l'ordre TEXTUEL des `?`, pas le logique.

LA PANNE QUE CE TEST GARDE
--------------------------
La pêche en LOTS annonçait « plus de lot à trancher » au-dessus d'une page qui
venait d'en compter 3 (constaté en production le 2026-08-24 par le PO, classe
`ad-2021-2eur-centenary-of-the-coronation-of-our-lady-of-meritxell` : la fiche
disait « 3 en lots », la pêche zéro).

`_lot_scope` rendait `[*run_args, *scope.args]`. Mais ses deux appelants —
`list_lots` et `_lot_keys_in_scope` — posent `match_expr` dans le **SELECT** et
`where_clause` dans le **WHERE** :

    SELECT …, SUM({match_expr}) AS n_matching_crops     ← les `?` du MATCH
      FROM review_queue rq … {join_sql}
     WHERE rq.kind = 'lot' AND rq.status = 'open'{where_clause}   ← ceux du WHERE

sqlite3 substitue les paramètres positionnels dans l'ordre où ils APPARAISSENT
dans le texte. Les args du WHERE partaient donc dans les `?` du SELECT, et
réciproquement : les 562 `class_id` du filtre de besoin atterrissaient dans le
`CASE WHEN` de la classe pêchée.

⚠️ **AUCUNE ERREUR SQL.** Le nombre de `?` est le bon, les types passent : la
requête rend simplement zéro ligne. C'est la signature exacte des pannes de ce
dépôt — un compteur à zéro, parfaitement crédible.

POURQUOI ÇA N'AVAIT JAMAIS PÉTÉ AVANT
--------------------------------------
Seule la branche `dino_class` porte À LA FOIS un `match_expr` et un
`where_clause` ; les autres n'ont pas de match, l'ordre y est sans effet. Et en
pêche, `where_clause` était toujours vide — jusqu'à D9 (2026-08-23), qui a fait
de `need_only` le défaut de `/review/peche`. Le défaut dormait dans le code, et
c'est un changement de valeur par défaut qui l'a réveillé.

CE QUE CE TEST VÉRIFIE, ET CE QU'IL NE PEUT PAS
-----------------------------------------------
Il vérifie la COMPOSITION : les args du match viennent en tête. Il ne rejoue pas
une requête complète — il faudrait une banque, des prédictions et un lot
cohérents, et une réplique de dev ne reproduit pas forcément le cas (mesuré :
sur la réplique du 2026-08-23, `need_only` True et False rendent le même compte,
donc elle ne discrimine rien). La preuve sur données réelles se fait en prod,
route contre route : `total` doit passer de 0 à 3 sur la classe ci-dessus.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from serving.review_queue import repository as R
from shared.dino_scope import build_dino_scope

CLS = "fr-2015-2eur-paix"


@pytest.fixture()
def conn(tmp_path):
    from store import Store
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.row_factory = sqlite3.Row
    c.execute(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value,"
        " is_commemorative, theme) VALUES (?,'FR','France',2015,2.0,1,'paix')",
        (CLS,),
    )
    # Une banque minimale : sans elle `build_dino_scope` rend un scope vide et
    # `_lot_scope` sort par la porte « rien à pêcher », sans args du tout.
    #
    # ⛔ TROIS classes, et pas une seule. Avec une seule, le filtre de besoin et
    # le scope de la classe portent le MÊME nombre de `?` ET les mêmes valeurs
    # (le couple de banque + l'identifiant) : une inversion serait indétectable,
    # et le test passerait au vert sur du code faux. Les deux classes en plus
    # font diverger les deux listes — c'est ce qui rend l'ordre observable.
    for autre in (CLS, "de-2016-2eur-sachsen", "it-2018-2eur-sante"):
        if autre != CLS:
            c.execute(
                "INSERT INTO coins (eurio_id, country, country_name, year,"
                " face_value, is_commemorative, theme)"
                " VALUES (?,'XX','Pays',2016,2.0,1,'thème')", (autre,),
            )
        c.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version,"
            " class_id, eurio_id, method, build_id, built_at)"
            " VALUES ('2eur_all','dinov2-vitl14',?,?,'canonical','b','2026-08-24')",
            (autre, autre),
        )
    c.commit()
    return c


def _scope(conn):
    return R._lot_scope(  # noqa: SLF001
        conn, cohort_id=None, target_eurio_id=None, design_group=None,
        dino_class=CLS, dino_rank=1, dino_min_spread=None,
        dino_country_only=False, dino_era_only=True, dino_min_denom=None,
        run_ids=None, need_only=True,
    )


def test_les_args_du_match_viennent_en_tete(conn):
    """Le contrat, verrouillé sur la composition plutôt que sur la promesse.

    `scope.args` est recalculé ici par le MÊME `build_dino_scope` que la
    fonction sous test : on n'écrit pas une seconde fois la règle, on vérifie
    que les deux morceaux sont assemblés dans le bon sens.
    """
    _join, where_clause, match_expr, args = _scope(conn)
    attendu = build_dino_scope(
        conn, dino_class=CLS, rank=1, country_only=False, source_alias="si",
    )
    assert attendu.args, "sans args de scope, ce test ne prouverait rien"
    assert where_clause, (
        "`need_only=True` doit produire un WHERE non vide — c'est ce qui rend "
        "l'ordre des args observable, et c'est le cas de production depuis D9"
    )
    assert args[:len(attendu.args)] == list(attendu.args), (
        "les args du MATCH doivent venir en tête : `match_expr` est dans le "
        "SELECT, donc ses `?` apparaissent AVANT ceux du WHERE. Inversés, la "
        "requête rend zéro ligne sans lever la moindre erreur."
    )


def test_le_compte_de_placeholders_correspond_a_chaque_morceau(conn):
    """Le garde-fou du garde-fou.

    Si `match_expr` et `where_clause` portaient le même nombre de `?`, le test
    ci-dessus passerait au vert sur des args inversés. On vérifie donc que les
    deux morceaux ont des tailles DIFFÉRENTES — sans quoi il faudrait un autre
    montage pour prouver quoi que ce soit.
    """
    _join, where_clause, match_expr, args = _scope(conn)
    n_match, n_where = match_expr.count("?"), where_clause.count("?")
    assert n_match + n_where == len(args), (
        f"{len(args)} args pour {n_match + n_where} placeholders — le décompte "
        "ne tombe pas juste, l'assemblage est faux quelque part"
    )
    assert n_match != n_where, (
        "les deux morceaux portent autant de `?` : l'inversion serait "
        "indétectable par comparaison de listes, ce test doit être revu"
    )
