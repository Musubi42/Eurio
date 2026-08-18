"""Les seuils d'entraînement résolus en base (store/thresholds.py).

Ce que ces tests protègent, dans l'ordre d'importance :

1. **Le filet.** Sur une base sans la migration 0006 (réplique d'un canonique
   plus vieux, image lean fraîche), la résolution doit servir les constantes —
   pas planter. C'est une précondition de démarrage du préflight.
2. **L'ordre de résolution.** classe → cohorte → global → code. Une surcharge de
   cohorte ne doit jamais fuiter sur une autre cohorte.
3. **L'historique.** Quand le plancher monte, des classes prêtes redeviennent
   incomplètes (DECISIONS §D1) ; sans la trace du changement, l'écran ne peut
   pas distinguer « la règle a changé » d'une régression.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from store import thresholds as th

MIGRATION = Path(__file__).resolve().parent.parent / "serving/migrations/0006_training_thresholds.sql"


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(MIGRATION.read_text())
    return c


def test_base_sans_migration_sert_les_constantes():
    """Le cas le plus important : la table n'existe pas encore."""
    bare = sqlite3.connect(":memory:")
    t = th.resolve(bare)
    assert (t.m_per_class, t.min_real, t.training_target) == (4, 10, 100)
    assert set(t.source.values()) == {"code"}
    # Et les lectures d'écran ne doivent pas exploser non plus.
    assert th.read_history(bare) == []
    assert th.read_state(bare)["global"] == {}


def test_table_vide_equivaut_au_comportement_davant(conn):
    assert th.resolve(conn).to_dict() == th.resolve(sqlite3.connect(":memory:")).to_dict()


def test_ordre_de_resolution_et_provenance(conn):
    th.set_threshold(conn, "min_real", 25, scope="global")
    th.set_threshold(conn, "min_real", 50, scope="cohort", scope_id="giga")

    assert th.resolve(conn).min_real == 25
    assert th.resolve(conn).source["min_real"] == "global"

    giga = th.resolve(conn, cohort_id="giga")
    assert giga.min_real == 50
    assert giga.source["min_real"] == "cohort"
    # Une surcharge de cohorte ne déborde pas sur les autres.
    assert th.resolve(conn, cohort_id="autre").min_real == 25
    # Les clés non surchargées restent aux constantes.
    assert giga.training_target == 100 and giga.source["training_target"] == "code"


def test_scope_classe_prevu_mais_jamais_alimente(conn):
    """D2 : le point d'accroche existe, il suffira d'insérer des lignes."""
    th.set_threshold(conn, "min_real", 30, scope="cohort", scope_id="giga")
    th.set_threshold(conn, "min_real", 60, scope="class", scope_id="fr-2euro-standard-t1")

    assert th.resolve(conn, cohort_id="giga").min_real == 30
    assert th.resolve(
        conn, cohort_id="giga", class_id="fr-2euro-standard-t1"
    ).min_real == 60


def test_retirer_une_surcharge_rend_la_cohorte_a_la_regle_generale(conn):
    th.set_threshold(conn, "min_real", 25, scope="global")
    th.set_threshold(conn, "min_real", 50, scope="cohort", scope_id="giga")
    th.clear_threshold(conn, "min_real", scope="cohort", scope_id="giga")

    assert th.resolve(conn, cohort_id="giga").min_real == 25
    # Retirer, ce n'est pas figer 25 : la cohorte suit le global s'il rebouge.
    th.set_threshold(conn, "min_real", 40, scope="global")
    assert th.resolve(conn, cohort_id="giga").min_real == 40


def test_le_global_se_change_mais_ne_se_retire_pas(conn):
    with pytest.raises(th.ThresholdError):
        th.clear_threshold(conn, "min_real", scope="global", scope_id="")


def test_refus_cle_inconnue_scope_incoherent_et_bornes(conn):
    with pytest.raises(th.ThresholdError):
        th.set_threshold(conn, "plancher", 10, scope="global")
    with pytest.raises(th.ThresholdError):
        th.set_threshold(conn, "min_real", 10, scope="cohort", scope_id="")
    with pytest.raises(th.ThresholdError):
        th.set_threshold(conn, "min_real", 10, scope="global", scope_id="giga")
    with pytest.raises(th.ThresholdError):
        th.set_threshold(conn, "min_real", 0, scope="global")
    with pytest.raises(th.ThresholdError):
        th.set_threshold(conn, "training_target", 99_999, scope="global")


def test_reposer_la_meme_valeur_ne_journalise_rien(conn):
    """Sinon l'historique se remplit de non-événements et on n'y voit plus les
    vrais changements — ceux qui expliquent qu'une classe soit repassée rouge."""
    th.set_threshold(conn, "min_real", 25, scope="global")
    again = th.set_threshold(conn, "min_real", 25, scope="global")

    assert again["changed"] is False
    assert len(th.read_history(conn)) == 1


def test_historique_dit_dou_vient_et_ou_va(conn):
    th.set_threshold(conn, "min_real", 25, scope="global", note="essai vague 2")
    th.set_threshold(conn, "min_real", 50, scope="global")

    hist = th.read_history(conn)
    assert [(h["old_value"], h["new_value"]) for h in hist] == [(25, 50), (None, 25)]
    assert hist[-1]["note"] == "essai vague 2"


def test_historique_dune_cohorte_inclut_le_global(conn):
    """Le plancher d'une cohorte peut bouger de deux façons : sa surcharge, ou
    le défaut qu'elle suit. L'écran doit voir les deux."""
    th.set_threshold(conn, "min_real", 25, scope="global")
    th.set_threshold(conn, "min_real", 50, scope="cohort", scope_id="giga")
    th.set_threshold(conn, "min_real", 12, scope="cohort", scope_id="autre")

    scopes = {(h["scope"], h["scope_id"]) for h in th.read_history(conn, cohort_id="giga")}
    assert scopes == {("global", None), ("cohort", "giga")}


def test_gel_dans_literation(conn):
    """Ce qu'on écrit dans training_config_json : les trois valeurs, rien de
    plus — sans elles on ne peut plus dire avec quel plancher un run a tourné."""
    th.set_threshold(conn, "min_real", 25, scope="cohort", scope_id="giga")
    frozen = th.resolve(conn, cohort_id="giga").frozen_config()

    assert frozen == {"m_per_class": 4, "min_real": 25, "training_target": 100}
