"""Le manifeste figé d'un corpus d'évaluation — chantier `juge-et-banc`.

Ce que ces tests verrouillent, et pourquoi chacun existe :

1. **la MAILLE décide de ce qu'on mesure.** `design_group` (celle du produit et
   d'ArcFace) vs `bank` (celle de la banque d'ancres) donnent deux jeux
   différents sur les mêmes crops. Mesuré sur les 300 réels : 60 classes contre
   64, l'écart venant des émissions communes européennes que la banque éclate
   par pays — jusqu'à **21 classes pour un seul dessin**. Noter à la maille
   `bank` demanderait à DINO de désigner le bon PAYS parmi 21 dessins quasi
   identiques, pendant qu'ArcFace a raison quoi qu'il dise ;
2. **un crop sans décision de review n'est pas perdu, mais il le DIT.** Les
   deux cas réels (une ligne `skipped`, une absence de ligne) doivent entrer
   avec une provenance vide et être comptés dans le sidecar ;
3. **la sortie est déterministe** — triée, donc diffable, donc hashable sans
   surprise ;
4. **le sidecar porte la maille.** Deux manifestes du MÊME corpus à deux
   mailles ne notent pas la même tâche, et rien d'autre dans le fichier ne le
   dirait.

Run: `.venv/bin/python -m pytest ml/tests/test_eval_corpus_gold.py -q`
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402

from review.eval_corpus_gold import (  # noqa: E402
    build_eval_gold,
    eval_gold_extra,
)

_SCHEMA = """
CREATE TABLE coins (
  eurio_id TEXT PRIMARY KEY,
  design_group_id TEXT,
  is_commemorative INTEGER NOT NULL DEFAULT 0,
  canonical_eurio_id TEXT,   -- lu par `bank_class_ids` pour choisir le représentant
  year INTEGER
);
CREATE TABLE source_images (id TEXT PRIMARY KEY, target_eurio_id TEXT);
CREATE TABLE image_assets (
  id TEXT PRIMARY KEY,
  source_image_id TEXT,
  eurio_id TEXT,
  storage_path TEXT,
  face TEXT,
  training_eligible INTEGER,
  eval_corpus TEXT
);
CREATE TABLE review_queue (
  id TEXT PRIMARY KEY,
  image_asset_id TEXT,
  status TEXT,
  decided_eurio_id TEXT,
  decided_face TEXT,
  decided_at TEXT,
  decided_by TEXT,
  kind TEXT
);
"""

CORPUS = "matrice-test"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    c.executemany(
        "INSERT INTO coins(eurio_id, design_group_id, is_commemorative, year)"
        " VALUES (?,?,?,?)",
        [
            # LE cas qui sépare les deux mailles : une émission COMMUNE
            # européenne. Un seul dessin, plusieurs pays. `design_group_id` les
            # rassemble ; `bank_class_ids` les éclate, parce qu'elle rend
            # `[eurio_id]` pour toute commémorative.
            ("at-2015-2eur-flag", "eu-eu-flag-2015", 1, 2015),
            ("be-2015-2eur-flag", "eu-eu-flag-2015", 1, 2015),
            ("fr-2015-2eur-flag", "eu-eu-flag-2015", 1, 2015),
            # Une courante à deux millésimes : les DEUX mailles la rassemblent,
            # mais sous des identifiants différents (groupe vs représentant).
            ("fr-1999-2eur-standard", "fr-2euro-standard-t1", 0, 1999),
            ("fr-2007-2eur-standard", "fr-2euro-standard-t1", 0, 2007),
            # Une commémorative nationale : une pièce, une classe, partout.
            ("de-2018-2eur-schmidt", None, 1, 2018),
        ],
    )
    c.execute("INSERT INTO source_images(id, target_eurio_id) VALUES ('s1', NULL)")
    yield c
    c.close()


def _asset(conn, aid, eurio_id, *, corpus=CORPUS, eligible=1, review="done"):
    conn.execute(
        "INSERT INTO image_assets(id, source_image_id, eurio_id, storage_path,"
        " face, training_eligible, eval_corpus) VALUES (?,'s1',?,?, 'obverse', ?, ?)",
        (aid, eurio_id, f"ebay/run/{aid}.png", eligible, corpus),
    )
    if review == "done":
        conn.execute(
            "INSERT INTO review_queue(id, image_asset_id, status, decided_eurio_id,"
            " decided_at, decided_by, kind) VALUES (?,?, 'done', ?, "
            "'2026-06-15T17:33:57Z', 'admin', 'single')",
            (f"rq-{aid}", aid, eurio_id),
        )
    elif review == "skipped":
        conn.execute(
            "INSERT INTO review_queue(id, image_asset_id, status, kind)"
            " VALUES (?,?, 'skipped', 'lot')",
            (f"rq-{aid}", aid),
        )
    # review == "none" : aucune ligne du tout.
    conn.commit()


# ─── 1. La maille décide de ce qu'on mesure ──────────────────────────────────


def test_la_maille_design_group_rassemble_une_emission_commune(conn):
    """LE test de ce module.

    Trois pays, un seul dessin. À la maille du produit c'est UNE classe — et
    c'est ce qu'ArcFace apprend. À la maille de la banque, c'est trois, et le
    banc demanderait de désigner le bon pays entre trois images identiques.
    """
    for i, e in enumerate(("at-2015-2eur-flag", "be-2015-2eur-flag",
                           "fr-2015-2eur-flag")):
        _asset(conn, f"a{i}", e)

    dg = build_eval_gold(conn, CORPUS, mesh="design_group")
    assert {r.class_id for r in dg} == {"eu-eu-flag-2015"}, (
        "à la maille du produit, une émission commune est UNE classe"
    )

    bk = build_eval_gold(conn, CORPUS, mesh="bank")
    assert {r.class_id for r in bk} == {
        "at-2015-2eur-flag", "be-2015-2eur-flag", "fr-2015-2eur-flag"
    }, "à la maille de la banque, elle éclate par pays — le handicap fabriqué"

    # Et la vérité par crop, elle, ne bouge pas : c'est bien la MAILLE qui
    # change, pas l'étiquetage.
    assert [r.truth_eurio_id for r in dg] == [r.truth_eurio_id for r in bk]


def test_une_courante_est_rassemblee_par_les_deux_mailles(conn):
    """Le pendant : sur une courante, les deux mailles rassemblent — sous des
    identifiants différents. Sans ce test, le précédent pourrait passer avec
    une maille qui ne rassemble jamais rien."""
    _asset(conn, "a0", "fr-1999-2eur-standard")
    _asset(conn, "a1", "fr-2007-2eur-standard")

    dg = build_eval_gold(conn, CORPUS, mesh="design_group")
    bk = build_eval_gold(conn, CORPUS, mesh="bank")
    assert {r.class_id for r in dg} == {"fr-2euro-standard-t1"}
    # La banque indexe sous le représentant : le millésime le plus ancien.
    assert {r.class_id for r in bk} == {"fr-1999-2eur-standard"}


def test_une_maille_inconnue_est_refusee(conn):
    """Un nom de maille mal tapé ne doit pas se replier sur un défaut : il
    changerait la tâche mesurée sans un mot."""
    _asset(conn, "a0", "de-2018-2eur-schmidt")
    with pytest.raises(ValueError, match="maille inconnue"):
        build_eval_gold(conn, CORPUS, mesh="design-group")


# ─── 2. Un crop sans décision de review entre, mais il le dit ────────────────


def test_un_crop_sans_decision_de_review_entre_avec_une_provenance_vide(conn):
    """Les deux cas réels rencontrés sur les 300 : une ligne `skipped` (kind
    'lot') et aucune ligne du tout. Les exclure ferait tomber deux classes de
    5 à 4 crops et casserait l'invariant du prélèvement, pour zéro gain de
    justesse — `image_assets.eurio_id` est d'accord avec la review partout où
    les deux existent (0/298 de divergence, mesuré)."""
    _asset(conn, "a0", "de-2018-2eur-schmidt")                    # décidé
    _asset(conn, "a1", "de-2018-2eur-schmidt", review="skipped")  # lot skippé
    _asset(conn, "a2", "de-2018-2eur-schmidt", review="none")     # aucune ligne

    rows = build_eval_gold(conn, CORPUS)
    assert len(rows) == 3, "aucun crop n'est perdu"
    par_id = {r.asset_id: r for r in rows}
    assert par_id["a0"].decided_by == "admin"
    for orphelin in ("a1", "a2"):
        r = par_id[orphelin]
        assert r.truth_eurio_id == "de-2018-2eur-schmidt", "le label tranché fait foi"
        assert r.decided_at == "" and r.decided_by is None and r.review_kind is None, (
            "la ligne doit dire elle-même qu'il n'y a personne derrière"
        )


def test_le_sidecar_compte_les_crops_sans_decision(conn):
    """Un plancher de bruit qu'on ne compte pas est un plancher de bruit qu'on
    oublie d'annoncer avec le chiffre."""
    _asset(conn, "a0", "de-2018-2eur-schmidt")
    _asset(conn, "a1", "de-2018-2eur-schmidt", review="none")

    extra = eval_gold_extra(build_eval_gold(conn, CORPUS), CORPUS)
    assert extra["n_sans_decision_review"] == 1


def test_le_sidecar_signale_un_crop_devenu_non_eligible(conn):
    """Devrait être 0 : le pool de prélèvement exigeait `training_eligible=1`.
    Non nul = la review a dégradé un crop APRÈS son entrée dans le corpus, et
    le jeu n'est plus celui qu'on croit."""
    _asset(conn, "a0", "de-2018-2eur-schmidt")
    _asset(conn, "a1", "de-2018-2eur-schmidt", eligible=0)

    extra = eval_gold_extra(build_eval_gold(conn, CORPUS), CORPUS)
    assert extra["n_non_training_eligible"] == 1


def test_le_sidecar_signale_une_classe_hors_quota(conn):
    """L'invariant du prélèvement est 5 par classe (D1). Une classe en dessous
    signale un crop perdu entre le marquage et ici."""
    for i in range(3):
        _asset(conn, f"a{i}", "de-2018-2eur-schmidt")
    _asset(conn, "b0", "fr-1999-2eur-standard")

    extra = eval_gold_extra(build_eval_gold(conn, CORPUS), CORPUS)
    assert extra["n_crops_par_classe"] == [1, 3]
    assert extra["classes_hors_quota"] == ["fr-2euro-standard-t1"]


# ─── 3. La population, et rien qu'elle ───────────────────────────────────────


def test_seul_le_corpus_demande_est_pris(conn):
    """Un autre corpus d'éval, ou aucun, ne doit pas fuir dans le manifeste."""
    _asset(conn, "a0", "de-2018-2eur-schmidt")
    _asset(conn, "a1", "de-2018-2eur-schmidt", corpus="autre-corpus")
    _asset(conn, "a2", "de-2018-2eur-schmidt", corpus=None)

    assert [r.asset_id for r in build_eval_gold(conn, CORPUS)] == ["a0"]


def test_la_sortie_est_deterministe_et_triee(conn):
    """Triée par `asset_id` : diffable, et hashable sans surprise — c'est ce
    qui rend `gold_version` stable d'une exécution à l'autre."""
    for aid in ("z9", "a0", "m5"):
        _asset(conn, aid, "de-2018-2eur-schmidt")

    une = build_eval_gold(conn, CORPUS)
    deux = build_eval_gold(conn, CORPUS)
    assert [r.asset_id for r in une] == ["a0", "m5", "z9"]
    assert une == deux


def test_le_row_factory_de_lappelant_est_rendu_intact(conn):
    """La fonction bascule en `sqlite3.Row` pour lire ses colonnes par nom ; si
    elle ne rendait pas la connexion telle qu'elle l'a trouvée, l'appelant
    verrait ses propres requêtes changer de forme après coup."""
    conn.row_factory = None
    _asset(conn, "a0", "de-2018-2eur-schmidt")
    build_eval_gold(conn, CORPUS)
    assert conn.row_factory is None


# ─── 4. Le sidecar porte la maille ───────────────────────────────────────────


def test_le_sidecar_porte_la_maille(conn):
    """Deux manifestes du MÊME corpus à deux mailles ne notent pas la même
    tâche. Sans ce champ, rien dans le fichier ne le dirait."""
    _asset(conn, "a0", "at-2015-2eur-flag")

    assert eval_gold_extra(
        build_eval_gold(conn, CORPUS, mesh="bank"), CORPUS, mesh="bank"
    )["mesh"] == "bank"
    assert eval_gold_extra(
        build_eval_gold(conn, CORPUS), CORPUS
    )["mesh"] == "design_group"


def test_le_sidecar_recopie_la_selection_en_toutes_lettres(conn):
    """Un lecteur dans six mois doit savoir ce qui a été retenu sans relire le
    module — et le `LEFT JOIN` sur la review est précisément la subtilité qu'il
    faut pouvoir constater."""
    _asset(conn, "a0", "de-2018-2eur-schmidt")
    sql = eval_gold_extra(build_eval_gold(conn, CORPUS), CORPUS)["selection_sql"]
    assert "LEFT JOIN" in sql and "eval_corpus = :corpus" in sql
