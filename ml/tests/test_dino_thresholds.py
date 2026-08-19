"""Les seuils DINO résolus en base (store/dino_thresholds.py).

Ce que ces tests protègent, dans l'ordre d'importance :

1. **Le filet.** Table absente (canonique pas encore redéployé, réplique en
   retard) → les défauts du code, pas une erreur. C'est une précondition de
   démarrage de la file de review.
2. **L'isolation par encodeur.** Un seuil posé sur `2eur_all`/vitl14 ne doit
   JAMAIS fuiter sur `2eur_commemo`/vits14 : les deux échelles de similarité
   ne sont pas comparables, et servir la mauvaise valeur ne lève aucune erreur.
3. **Le silence borné.** Seul « no such table » se tait. Un `database is
   locked` avalé ferait passer un défaut pour une valeur réglée.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from store import dino_thresholds as dt

MIGRATION = ML_DIR / "serving/migrations/0008_dino_thresholds.sql"
ALL = {"anchors_kind": "2eur_all", "encoder_version": "dinov2-vitl14"}
COMMEMO = {"anchors_kind": "2eur_commemo", "encoder_version": "dinov2-vits14"}


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(MIGRATION.read_text())
    return c


def test_base_sans_migration_sert_les_defauts():
    bare = sqlite3.connect(":memory:")
    r = dt.resolve(bare, **ALL)
    assert r.values["spread_auto_accept_min"] == 0.10
    assert set(r.source.values()) == {"code"}
    assert dt.read_history(bare, **ALL) == []
    assert dt.read_state(bare, **ALL)["overrides"] == {}


def test_table_vide_equivaut_au_comportement_davant(conn):
    assert dt.resolve(conn, **ALL).values == dt.resolve(sqlite3.connect(":memory:"), **ALL).values


def test_un_seuil_appartient_a_son_encodeur(conn):
    """Le test qui compte : 0,55 calibré sur vits14 ne veut rien dire pour
    vitl14. Une fuite entre couples déplacerait le taux de faux positifs sans
    lever la moindre erreur."""
    dt.set_threshold(conn, "spread_auto_accept_min", 0.25, **ALL)

    assert dt.resolve(conn, **ALL).values["spread_auto_accept_min"] == 0.25
    assert dt.resolve(conn, **ALL).source["spread_auto_accept_min"] == "db"
    # L'autre couple n'a pas bougé.
    assert dt.resolve(conn, **COMMEMO).values["spread_auto_accept_min"] == 0.10
    assert dt.resolve(conn, **COMMEMO).source["spread_auto_accept_min"] == "code"


def test_retirer_une_surcharge_rend_au_defaut(conn):
    dt.set_threshold(conn, "country_spread_min", 0.20, **ALL)
    dt.clear_threshold(conn, "country_spread_min", **ALL)
    r = dt.resolve(conn, **ALL)
    assert r.values["country_spread_min"] == 0.05
    assert r.source["country_spread_min"] == "code"


def test_refus_cle_inconnue_et_bornes(conn):
    with pytest.raises(dt.DinoThresholdError):
        dt.set_threshold(conn, "plancher", 0.1, **ALL)
    with pytest.raises(dt.DinoThresholdError):
        dt.set_threshold(conn, "spread_auto_accept_min", 0.9, **ALL)  # borne 0.5
    with pytest.raises(dt.DinoThresholdError):
        dt.set_threshold(conn, "top1_country_sim_min", 1.5, **ALL)


def test_reposer_la_meme_valeur_ne_journalise_rien(conn):
    dt.set_threshold(conn, "spread_auto_accept_min", 0.12, **ALL)
    again = dt.set_threshold(conn, "spread_auto_accept_min", 0.12, **ALL)
    assert again["changed"] is False
    assert len(dt.read_history(conn, **ALL)) == 1


def test_la_calibration_voyage_avec_la_valeur(conn):
    """Un seuil sans son origine est un nombre que personne n'ose bouger."""
    dt.set_threshold(
        conn, "spread_auto_accept_min", 0.10, **ALL,
        calibrated_on="1952 crops tranchés (2026-08-19)",
        precision_at=0.971, n_samples=1952,
    )
    row = conn.execute(
        "SELECT calibrated_on, precision_at, n_samples FROM dino_thresholds "
        " WHERE key='spread_auto_accept_min'",
    ).fetchone()
    assert row[0].startswith("1952 crops") and row[1] == 0.971 and row[2] == 1952


def test_une_erreur_sqlite_qui_nest_pas_labsence_de_table_remonte():
    class Locked:
        def execute(self, *_a, **_k):
            raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        dt.resolve(Locked(), **ALL)  # type: ignore[arg-type]


def test_ecrire_sans_la_table_dit_pourquoi(conn=None):
    bare = sqlite3.connect(":memory:")
    with pytest.raises(dt.DinoThresholdError) as exc:
        dt.set_threshold(bare, "spread_auto_accept_min", 0.2, **ALL)
    assert exc.value.status_code == 503 and "0008" in exc.value.detail
