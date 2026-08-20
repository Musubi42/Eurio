"""P6-5 — le store des résultats du banc multi-encodeurs.

Le test lit le VRAI fichier de migration (``0009_encoder_bench.sql``) et
l'applique par ``executescript`` : il vaut donc aussi test de syntaxe de la
migration, et de sa rejouabilité.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from shared.stats.paired import paired_compare
from store.encoder_bench import (
    SCHEMA_SQL,
    EncoderBenchPrediction,
    EncoderBenchRun,
    calibration_blockers,
    ensure_schema,
    get_run,
    list_runs,
    load_correctness,
    paired_overlap,
    record_predictions,
    record_run,
)

_MIGRATION = ML_DIR / "serving" / "migrations" / "0009_encoder_bench.sql"


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(_MIGRATION.read_text(encoding="utf-8"))
    yield c
    c.close()


def _run(run_id="r1", *, encoder_version="dinov2-vitl14", created_at="2026-08-19T10:00:00Z"):
    return EncoderBenchRun(
        run_id=run_id,
        created_at=created_at,
        gold_version="abc123def456",
        gold_n_crops=1911,
        anchors_kind="2eur_all",
        encoder_spec="dinov2_vitl14",
        encoder_version=encoder_version,
        n_in_scope=1800,
        recall1=0.81,
        recall5=0.93,
        sweep_json='[{"threshold":0.02}]',
    )


def _pred(asset_id, correct, in_top5=1):
    return EncoderBenchPrediction(
        asset_id=asset_id,
        truth_class_id="fr-1999-2eur",
        correct=int(correct),
        in_top5=int(in_top5),
        top1_eurio_id="fr-1999-2eur" if correct else "de-2002-2eur",
        top1_sim=0.71,
        top2_sim=0.68,
        spread=0.03,
    )


# ─── Migration ────────────────────────────────────────────────────────────────


def test_migration_est_rejouable():
    """`CREATE TABLE IF NOT EXISTS` pur : deux passages ne lèvent pas."""
    c = sqlite3.connect(":memory:")
    sql = _MIGRATION.read_text(encoding="utf-8")
    c.executescript(sql)
    c.executescript(sql)  # ne doit pas lever
    tables = {
        r[0]
        for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"encoder_bench_runs", "encoder_bench_predictions"} <= tables
    c.close()


def test_schema_sql_du_store_est_la_migration():
    """Une seule source de DDL — pas de copie dans le store qui dériverait."""
    assert SCHEMA_SQL == _MIGRATION.read_text(encoding="utf-8")


def test_ensure_schema_bootstrape_une_base_vierge():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_schema(c)
    assert get_run(c, "absent") is None
    c.close()


def test_lectures_sur_connexion_nue_sans_row_factory():
    """D14 — le module expose ``ensure_schema`` « pour les tests et les bases
    locales » : il doit donc marcher sur une connexion sqlite3 nue.

    Avant : ``TypeError: tuple indices must be integers`` au premier ``dict(r)``.
    """
    c = sqlite3.connect(":memory:")  # pas de row_factory
    ensure_schema(c)
    record_run(c, _run())
    record_predictions(c, "r1", [_pred("a", True), _pred("b", False)])

    assert get_run(c, "r1")["recall1"] == 0.81
    assert [r["run_id"] for r in list_runs(c)] == ["r1"]
    assert load_correctness(c, "r1") == {"a": True, "b": False}
    # ...et la connexion ressort telle qu'elle est entrée.
    assert c.row_factory is None
    c.close()


def test_lectures_restaurent_le_row_factory_de_lappelant():
    c = sqlite3.connect(":memory:")
    sentinel = lambda cur, row: tuple(row)  # noqa: E731
    c.row_factory = sentinel
    ensure_schema(c)
    record_run(c, _run())
    list_runs(c)
    get_run(c, "r1")
    load_correctness(c, "r1")
    assert c.row_factory is sentinel
    c.close()


def test_provisional_vaut_1_par_defaut(conn):
    """Le défaut SQL protège même un INSERT qui oublierait la colonne."""
    conn.execute(
        "INSERT INTO encoder_bench_runs (run_id, created_at, gold_version, "
        " gold_n_crops, anchors_kind, encoder_spec, encoder_version, n_in_scope) "
        "VALUES ('x','t','v',1,'2eur_all','s','e',1)"
    )
    assert get_run(conn, "x")["provisional"] == 1


# ─── Runs ─────────────────────────────────────────────────────────────────────


def test_record_run_roundtrip(conn):
    record_run(conn, _run())
    got = get_run(conn, "r1")
    assert got["recall1"] == 0.81
    assert got["encoder_version"] == "dinov2-vitl14"
    assert got["provisional"] == 1  # défaut de la dataclass
    assert got["gold_sample_n"] is None


def test_record_run_remplace(conn):
    record_run(conn, _run())
    r2 = _run()
    r2.recall1 = 0.85
    record_run(conn, r2)
    assert len(list_runs(conn)) == 1
    assert get_run(conn, "r1")["recall1"] == 0.85


def test_list_runs_filtre_par_couple_et_trie(conn):
    record_run(conn, _run("old", created_at="2026-08-01T00:00:00Z"))
    record_run(conn, _run("new", created_at="2026-08-19T00:00:00Z"))
    record_run(conn, _run("other", encoder_version="timm:vit_small_patch16_dinov3.lvd1689m"))

    ids = [r["run_id"] for r in list_runs(conn, anchors_kind="2eur_all")]
    assert ids[0] == "other" or ids[0] == "new"  # tri created_at DESC
    vitl = [
        r["run_id"]
        for r in list_runs(conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14")
    ]
    assert vitl == ["new", "old"]
    assert len(list_runs(conn, limit=1)) == 1


# ─── Prédictions ──────────────────────────────────────────────────────────────


def test_record_predictions_remplace_en_bloc(conn):
    record_run(conn, _run())
    assert record_predictions(conn, "r1", [_pred("a", True), _pred("b", False)]) == 2
    # Rejeu sur un sous-ensemble : les lignes orphelines ne doivent PAS rester,
    # elles fausseraient l'apparié en silence.
    assert record_predictions(conn, "r1", [_pred("a", False)]) == 1
    rows = conn.execute(
        "SELECT asset_id, correct FROM encoder_bench_predictions WHERE run_id='r1'"
    ).fetchall()
    assert [(r["asset_id"], r["correct"]) for r in rows] == [("a", 0)]


def test_record_predictions_liste_vide_ne_purge_pas(conn):
    """D9 — ré-envoyer un run sans prédictions ne doit PAS effacer les siennes.

    Le cas réel : on repousse un run pour corriger sa ``note`` ou son
    ``mcnemar_p``. La route ``POST /ingest/encoder-bench`` accepte
    ``predictions: []`` ; avec un DELETE inconditionnel, ce geste anodin
    détruisait la seule chose qui rend l'apparié rejouable sans ré-encoder.
    """
    record_run(conn, _run())
    record_predictions(conn, "r1", [_pred("a", True)])
    assert record_predictions(conn, "r1", []) == 0
    assert load_correctness(conn, "r1") == {"a": True}


def test_record_predictions_purge_explicite(conn):
    """La purge reste possible, mais elle se demande."""
    record_run(conn, _run())
    record_predictions(conn, "r1", [_pred("a", True)])
    assert record_predictions(conn, "r1", [], purge_empty=True) == 0
    assert load_correctness(conn, "r1") == {}


def test_load_correctness_alimente_paired_compare(conn):
    record_run(conn, _run("a1"))
    record_run(conn, _run("b1", encoder_version="dinov3-vits16"))
    record_predictions(
        conn, "a1", [_pred("x", True), _pred("y", True), _pred("z", False)]
    )
    record_predictions(
        conn, "b1", [_pred("x", True), _pred("y", False), _pred("z", True)]
    )

    res = paired_compare(load_correctness(conn, "a1"), load_correctness(conn, "b1"))
    assert res.n_paired == 3
    assert (res.both_correct, res.a_only, res.b_only, res.neither) == (1, 1, 1, 0)
    assert res.delta_acc == 0.0


# ─── Bloqueurs de calibration — c'est le test qui rend l'attente de P3 visible ─


#: ⚠️ La fixture déclarait ``dino_class_references`` à **3 colonnes sur 11** —
#: sans ``encoder_version``. Aucun test ne pouvait donc voir que ``_p1_blockers``
#: ignorait l'encodeur : on réparait le code et le test continuait de mentir.
#: Le DDL ci-dessous est celui de ``state/schema.sql`` §Références Dino, réduit
#: aux contraintes qui comptent ici (la clé et le CHECK sur ``method``).
#: ⚠️ Il a fallu le corriger une SECONDE fois, le 2026-08-20 : sa clé primaire
#: était ``(anchors_kind, class_id, eurio_id, asset_id)`` et son
#: ``encoder_version`` nullable — la forme d'AVANT la migration 0010. Une
#: fixture qui décrit une table qui n'existe plus est un test qui ment à
#: nouveau (défaut M5, même famille que M1). La forme d'arrivée est
#: DÉRIVÉE du vrai ``state/schema.sql`` par ``tests/_schema_reel.py`` dans
#: ``tests/test_dino_refs_encoder_key.py`` ; ici on la recopie, et
#: ``test_la_fixture_porte_la_meme_cle_que_le_vrai_schema`` (plus bas) vérifie
#: qu'elle n'en dérive pas.
_DDL_REFERENTIEL_DINO = """
CREATE TABLE dino_anchor_builds (
  build_id TEXT PRIMARY KEY, anchors_kind TEXT NOT NULL,
  encoder_version TEXT NOT NULL, built_at TEXT NOT NULL);
CREATE TABLE image_asset_dino_predictions (
  asset_id TEXT, anchors_kind TEXT, encoder_version TEXT, computed_at TEXT);
CREATE TABLE dino_class_references (
  anchors_kind    TEXT NOT NULL DEFAULT '2eur_all',
  class_id        TEXT NOT NULL,
  eurio_id        TEXT NOT NULL,
  asset_id        TEXT,
  method          TEXT NOT NULL
                  CHECK (method IN ('canonical','fps','manual_pin','manual_exclude')),
  rank            INTEGER,
  selected_sim    REAL,
  built_at        TEXT NOT NULL DEFAULT (datetime('now')),
  encoder_version TEXT NOT NULL DEFAULT '',
  build_id        TEXT,
  source_path     TEXT,
  PRIMARY KEY (anchors_kind, encoder_version, class_id, eurio_id, asset_id)
);
"""

#: Constantes de FIXTURE, pas de mesure : elles fixent les proportions du cas
#: (couverture insuffisante / suffisante). Un test ne doit rien lire de la
#: réplique locale — son état diverge du canonique par construction
#: (Direction A : la trace du build part au VPS par HTTP).
#:
#: ⚠️ Elles se lisent en classes **couvertes** (≥ ``USEFUL_MIN_REFS``
#: exemplaires) depuis le 2026-08-20, et plus en classes « à au moins un
#: exemplaire » : c'est la métrique que P1 mesure désormais. Les valeurs
#: encadrent ``DEFAULT_MIN_USEFUL_CLASSES`` — 60 dessous, 124 dessus, 124 étant
#: la couverture réelle de la banque servie au 2026-08-20T17:16Z. La fixture
#: garde donc la FORME du cas (banque amputée / banque saine) sans rien lire de
#: la réplique.
_COUVERTURE_AMPUTEE = 60
_COUVERTURE_SAINE = 124

_ENCODEUR_PROD = "dinov2-vitl14"
_ENCODEUR_CANDIDAT = "timm:vit_small_patch16_dinov3.lvd1689m"


def _ajoute_refs_fps(
    conn, encoder_version, ids, anchors_kind="2eur_all", *, n_refs=2
):
    """Insère des exemplaires ``fps`` pour un encodeur donné.

    ``n_refs`` est le nombre d'exemplaires POSÉS PAR CLASSE, et son défaut est
    2 : c'est le régime minimal que P1 compte comme couvert, et celui que le
    builder produit depuis le plancher. ``n_refs=1`` sert à fabriquer le cas
    que le garde doit refuser — une banque faite de classes à exemplaire
    unique, que l'ancien compte « au moins un » validait.

    ⚠️ L'``asset_id`` est le MÊME d'un encodeur à l'autre (``asset-<i>-<r>``), et
    ce n'est pas un détail : c'est le cas NOMINAL — les deux encodeurs piochent
    dans le même pool de crops validés. La fixture fabriquait auparavant un
    ``asset-<encodeur>-<i>``, ce qui rendait le défaut M1 (deux encodeurs qui
    se marchent dessus) littéralement inexprimable dans les tests.
    """
    conn.executemany(
        "INSERT INTO dino_class_references "
        "(anchors_kind, class_id, eurio_id, asset_id, method, rank, "
        " encoder_version, build_id) VALUES (?,?,?,?, 'fps', ?, ?, 'b1')",
        [
            (anchors_kind, f"c{i}", f"c{i}", f"asset-{i}-{r}", r, encoder_version)
            for i in ids
            for r in range(n_refs)
        ],
    )


def _seed_etat_du_jour(conn):
    """Reproduit la FORME de l'état mesuré le 2026-08-19 sur
    ``ml/state/eurio.replica.db`` : des prédictions toutes antérieures au
    dernier build, et une couverture d'exemplaires insuffisante — le tout pour
    le seul encodeur de production. (Version miniature : les proportions
    comptent, pas le volume.)"""
    conn.executescript(_DDL_REFERENTIEL_DINO)
    conn.execute(
        "INSERT INTO dino_anchor_builds VALUES "
        "('b1','2eur_all','dinov2-vitl14','2026-08-19T00:28:21+00:00')"
    )
    for i in range(5):
        conn.execute(
            "INSERT INTO image_asset_dino_predictions VALUES "
            "(?, '2eur_all','dinov2-vitl14','2026-08-10T00:00:00+00:00')",
            (f"a{i}",),
        )
    _ajoute_refs_fps(conn, _ENCODEUR_PROD, range(_COUVERTURE_AMPUTEE))


def test_calibration_blockers_non_vide_sur_letat_du_jour(conn):
    _seed_etat_du_jour(conn)
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14",
        gold_sample_n=None,
    )
    assert len(blockers) == 2
    assert any(b.startswith("P3:") for b in blockers)
    assert any(b.startswith("P1:") for b in blockers)
    assert "5 predictions" in blockers[0]


def test_calibration_blockers_vide_quand_tout_est_propre(conn):
    _seed_etat_du_jour(conn)
    # P3 levé : les prédictions sont postérieures au build.
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    # P1 levé : le rebuild a porté la couverture au-delà du seuil.
    _ajoute_refs_fps(
        conn,
        _ENCODEUR_PROD,
        range(_COUVERTURE_AMPUTEE, _COUVERTURE_SAINE),
    )
    assert (
        calibration_blockers(
            conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14"
        )
        == []
    )


def test_calibration_blockers_signale_lechantillon(conn):
    _seed_etat_du_jour(conn)
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14",
        gold_sample_n=200, gold_n_crops=1911,
    )
    assert "echantillon: run sur 200 crops sur les 1911 du gold" in blockers


def test_calibration_blockers_referentiel_absent_bloque_sans_exploser(conn):
    """D1 — une base sans le référentiel DINO ne doit pas exploser, mais elle
    ne doit surtout pas rendre « promouvable ».

    L'absence de preuve de fraîcheur est un bloqueur, pas un feu vert. Avant :
    ``[]`` sur une base ``:memory:`` vide, donc ``provisional=0``.
    """
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14"
    )
    assert any(b.startswith("P3:") for b in blockers), blockers
    assert any(b.startswith("P1:") for b in blockers), blockers
    assert "dino_anchor_builds" in " ".join(blockers)


def test_calibration_blockers_encodeur_candidat_sans_build(conn):
    """D1 — le cas qui désarmait le garde : un encodeur CANDIDAT n'a aucune
    ligne dans ``dino_anchor_builds``, donc ``last_build`` était NULL et tout
    le bloc P3 était sauté. Un run DINOv3 sortait alors ``provisional=0``."""
    _seed_etat_du_jour(conn)  # ne trace que le build dinov2-vitl14
    blockers = calibration_blockers(
        conn,
        anchors_kind="2eur_all",
        encoder_version="timm:vit_small_patch16_dinov3.lvd1689m",
    )
    p3 = [b for b in blockers if b.startswith("P3:")]
    assert p3, blockers
    assert "aucun build" in p3[0]
    assert any(b.startswith("P1:") for b in blockers), blockers


def test_calibration_blockers_build_trace_mais_zero_prediction(conn):
    """D1 — un build tracé et zéro prédiction recalculée, c'est le même trou :
    rien n'a été mesuré, donc rien n'est promouvable."""
    _seed_etat_du_jour(conn)
    conn.execute(
        "INSERT INTO dino_anchor_builds VALUES "
        "('b2','2eur_all','dinov3-vits16','2026-08-19T00:28:21+00:00')"
    )
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version="dinov3-vits16",
        min_useful_classes=0,
    )
    assert len(blockers) == 1, blockers
    assert blockers[0].startswith("P3:")
    assert "aucune prediction" in blockers[0]


def test_calibration_blockers_gold_entier_nest_pas_un_echantillon(conn):
    """D8 — un run sur la TOTALITÉ du gold n'est pas un échantillon.

    Avant, le bloqueur tombait dès que ``gold_sample_n`` était renseigné : le
    seul contournement était de mentir sur la trace (``gold_sample_n=None``).
    """
    _seed_etat_du_jour(conn)
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    assert (
        calibration_blockers(
            conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14",
            gold_sample_n=1958, gold_n_crops=1958, min_useful_classes=0,
        )
        == []
    )


def test_calibration_blockers_echantillon_sans_total_reste_bloquant(conn):
    """``gold_n_crops`` inconnu : on ne peut pas prouver que le run couvre tout,
    donc on bloque — l'absence de preuve reste un bloqueur."""
    _seed_etat_du_jour(conn)
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14",
        gold_sample_n=200, gold_n_crops=None, min_useful_classes=0,
    )
    assert len(blockers) == 1 and blockers[0].startswith("echantillon:")


# ─── D1 volet P1 — le garde de couverture doit voir l'ENCODEUR ───────────────


def test_p1_ne_valide_pas_un_candidat_avec_la_couverture_de_la_prod(conn):
    """D1/P1 — un candidat DINOv3 a 0 exemplaire en base ; P1 se taisait dès
    que le seuil était franchi par les lignes ``dinov2-vitl14``.

    La table est pourtant scopée sur le couple
    (``UNIQUE(anchors_kind, encoder_version, class_id)``), et le DELETE de
    ``store.dino_references.replace_auto_references`` scope pareil.
    """
    _seed_etat_du_jour(conn)
    # La prod dépasse largement le seuil…
    _ajoute_refs_fps(
        conn, _ENCODEUR_PROD, range(_COUVERTURE_AMPUTEE, _COUVERTURE_SAINE)
    )
    # …mais le candidat n'a rien du tout.
    n_candidat = conn.execute(
        "SELECT COUNT(*) FROM dino_class_references WHERE encoder_version = ?",
        (_ENCODEUR_CANDIDAT,),
    ).fetchone()[0]
    assert n_candidat == 0

    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_CANDIDAT
    )
    p1 = [b for b in blockers if b.startswith("P1:")]
    assert p1, blockers
    assert "0 classes a 2 exemplaires ou plus" in p1[0]
    assert _ENCODEUR_CANDIDAT in p1[0]


def test_p1_ne_debloque_pas_la_prod_avec_les_exemplaires_du_candidat(conn):
    """D1/P1, symétrique — 60 classes ``fps`` arrivant pour un candidat
    faisaient passer P1 de « bloqué » à ``[]`` pour l'encodeur de PRODUCTION,
    dont la couverture n'avait pas bougé d'un pouce."""
    _seed_etat_du_jour(conn)
    _ajoute_refs_fps(conn, _ENCODEUR_CANDIDAT, range(1000, 1060))

    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD
    )
    p1 = [b for b in blockers if b.startswith("P1:")]
    assert p1, blockers
    assert f"{_COUVERTURE_AMPUTEE} classes a 2 exemplaires ou plus" in p1[0]


def test_p1_ignore_les_lignes_sans_encodeur(conn):
    """Les rows d'avant la migration 0007 n'appartiennent à aucun encodeur
    prouvable. Les compter rouvrirait le trou pour n'importe quel candidat.

    ⚠️ Elles portaient ``encoder_version`` **NULL** ; depuis la migration 0010
    la colonne est ``NOT NULL DEFAULT ''`` (une colonne nullable dans une clé
    primaire ne déduplique rien) et 0010 les replie sur ``''``, qui se lit
    « aucun encodeur attribué ». Le comportement attendu est inchangé — le
    prédicat strict ``encoder_version = ?`` ne matche pas ``''`` — mais la
    valeur semée doit être celle que la base peut réellement contenir, sinon
    le test garde une forme disparue.
    """
    _seed_etat_du_jour(conn)
    conn.executemany(
        "INSERT INTO dino_class_references "
        "(anchors_kind, class_id, eurio_id, asset_id, method, encoder_version) "
        "VALUES ('2eur_all', ?, ?, ?, 'fps', '')",
        [(f"legacy{i}", f"legacy{i}", f"legacy-asset-{i}") for i in range(300)],
    )
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_CANDIDAT
    )
    assert any(b.startswith("P1:") and "0 classes" in b for b in blockers), blockers


# ─── B2 — le garde P1 mesure la couverture UTILE ─────────────────────────────


def test_p1_ne_compte_pas_une_classe_a_un_seul_exemplaire(conn):
    """200 classes à UN exemplaire ne sont pas une banque calibrable.

    Le compte « au moins un exemplaire » les compte toutes et franchit le
    seuil ; la courbe held-out dit que chacune de ces classes est PIRE qu'à
    zéro (N=1 à 50,1 % contre N=0 à 53,1 %). Le garde validait donc une banque
    entièrement composée du seul régime qu'on s'interdit.
    """
    _seed_etat_du_jour(conn)
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    conn.executemany(
        "INSERT INTO dino_class_references "
        "(anchors_kind, class_id, eurio_id, asset_id, method, rank, "
        " encoder_version, build_id) VALUES ('2eur_all',?,?,?, 'fps', 0, ?, 'b1')",
        [(f"s{i}", f"s{i}", f"asset-s{i}", _ENCODEUR_PROD) for i in range(200)],
    )
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD
    )
    p1 = [b for b in blockers if b.startswith("P1:")]
    assert p1, blockers
    # Le message doit dire les DEUX comptes : sinon « 60 classes couvertes » ne
    # distingue pas une banque pauvre d'une banque pleine de classes à un seul
    # exemplaire, et les deux n'appellent pas le même geste.
    assert f"{_COUVERTURE_AMPUTEE} classes a 2 exemplaires ou plus" in p1[0]
    assert "200 autres restent sous le palier de 2 exemplaires" in p1[0]

    # …et les MÊMES classes, avec deux exemplaires chacune, passent.
    _ajoute_refs_fps(conn, _ENCODEUR_PROD, range(2000, 2200), n_refs=2)
    assert (
        calibration_blockers(
            conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD
        )
        == []
    )


def test_p1_ne_lit_pas_le_plancher_min_exemplars(conn):
    """Le garde ne doit PAS dépendre de ``dino_thresholds.min_exemplars``.

    C'est le couplage qui a périmé le seuil de 180 : une cible calibrée sur ce
    que le builder écrivait à ce moment-là. Si le plancher disparaît (les
    classes à un exemplaire reviennent en base), la couverture utile mesurée ne
    doit pas bouger d'une ligne — et si le plancher passe à 0, le garde ne doit
    pas retomber sur son ancien compte « au moins un exemplaire ».

    Vérifié de deux façons, parce qu'aucune ne suffit seule : par la MESURE
    (mêmes classes, avec et sans les lignes qu'un plancher retirerait), et par
    la STRUCTURE (aucun **code** du module ne nomme la clé du plancher — un
    futur ``resolve(...)["min_exemplars"]`` ferait rougir ce test avant d'être
    déployé). La lecture structurelle passe par l'AST et non par un ``in`` sur
    le source : les docstrings PARLENT du plancher, longuement et exprès, pour
    dire pourquoi il ne faut pas s'y brancher.
    """
    import ast
    import inspect

    from store import encoder_bench as eb

    tree = ast.parse(inspect.getsource(eb))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "min_exemplars":
            raise AssertionError(f"clé du plancher en dur ligne {node.lineno}")
        if isinstance(node, ast.Name) and node.id == "min_exemplars":
            raise AssertionError(f"plancher lu ligne {node.lineno}")
        if isinstance(node, ast.Attribute) and node.attr == "min_exemplars":
            raise AssertionError(f"plancher lu ligne {node.lineno}")
    importe = {
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module
    } | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not any("dino_threshold" in m for m in importe), importe

    _seed_etat_du_jour(conn)  # 60 classes couvertes
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    _ajoute_refs_fps(conn, _ENCODEUR_PROD, range(500, 540), n_refs=2)
    avant = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD
    )
    # Plancher retiré : 300 classes à UN exemplaire réapparaissent en base.
    _ajoute_refs_fps(conn, _ENCODEUR_PROD, range(3000, 3300), n_refs=1)
    apres = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD
    )
    # Le VERDICT ne bouge pas : mêmes bloqueurs, même compte de classes
    # couvertes. Seule la clause informative diffère (les 300 classes sous le
    # palier sont désormais là et le message les nomme) — c'est le contenu du
    # message, pas la mesure.
    assert len(avant) == len(apres) == 1, (avant, apres)
    assert avant[0].startswith("P1:") and apres[0].startswith("P1:")
    assert "100 classes a 2 exemplaires ou plus" in avant[0], avant
    assert "100 classes a 2 exemplaires ou plus" in apres[0], apres
    assert "300 autres restent sous le palier de 2 exemplaires" in apres[0], apres


def test_le_message_p1_propose_une_commande_qui_marche_sous_le_devshell(conn):
    """Le geste proposé doit tourner là où le bloqueur se lit : le devShell.

    Mesuré le 2026-08-20 sur ``ml/state/eurio.replica.db`` avec le préflight
    réel (``scripts.build_dino_anchors.preflight_db_traceability``) sous
    ``EURIO_DB_READONLY=1`` : ``push=True`` passe (la trace part au canonique),
    ``push=False`` lève ``ReadOnlyTraceabilityError`` AVANT l'encodage. Le
    message de P3 (« aucun build tracé ») proposait la variante sans ``--push``
    — donc une commande qui refuse de démarrer.
    """
    _seed_etat_du_jour(conn)
    # L'encodeur candidat rend les DEUX messages porteurs d'un geste : P3
    # « aucun build tracé » et P1 « 0 classe couverte ».
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_CANDIDAT
    )
    p1 = [b for b in blockers if b.startswith("P1:")]
    p3 = [b for b in blockers if b.startswith("P3:")]
    assert p1 and p3, blockers
    for msg in p1 + p3:
        if "dino-anchors:build" in msg:
            assert "--push" in msg, msg
            assert "EURIO_DB_READONLY" in msg, msg
    assert any("dino-anchors:build" in m for m in p1 + p3), blockers


# ─── D8 — le garde d'échantillon est symétrique ──────────────────────────────


def test_echantillon_plus_grand_que_le_gold_est_incoherent(conn):
    """D8 — ``gold_sample_n=99999`` sur un gold de 1958 n'est pas « plus que
    complet », c'est une trace fausse (désynchro ``--gold`` ↔ sidecar, ou
    payload forgé par un appelant tiers de ``POST /ingest/encoder-bench``).
    Avec ``<``, elle rendait ``[]`` donc ``provisional=0``."""
    _seed_etat_du_jour(conn)
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD,
        gold_sample_n=99999, gold_n_crops=1958, min_useful_classes=0,
    )
    assert blockers == [
        "echantillon: run sur 99999 crops sur les 1958 du gold"
    ], blockers


# ─── D16 — le recouvrement PARTIEL avec la baseline ──────────────────────────


def test_paired_overlap_compte_les_crops_communs(conn):
    """La mesure que rien ne persistait : combien de crops les deux runs
    partagent, relue sans ré-encoder."""
    record_run(conn, _run("a1"))
    record_run(conn, _run("b1", encoder_version="dinov3-vits16"))
    record_predictions(conn, "a1", [_pred(f"x{i}", True) for i in range(500)])
    record_predictions(
        conn, "b1", [_pred("x0", True)] + [_pred(f"y{i}", True) for i in range(500)]
    )
    assert paired_overlap(conn, "a1", "b1") == 1
    assert paired_overlap(conn, "b1", "a1") == 1


def test_recouvrement_partiel_bloque(conn):
    """D16 — 1 crop commun sur 501 donne ``mcnemar_p=1.0, b=0, c=0``,
    indiscernable d'une égalité mesurée sur tout le gold. Seul le compte de
    paires les distingue, donc il doit bloquer."""
    _seed_etat_du_jour(conn)
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    kw = dict(
        anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD,
        gold_sample_n=501, gold_n_crops=501, min_useful_classes=0,
    )
    # Sans baseline déclarée : rien à apparier, rien à bloquer.
    assert calibration_blockers(conn, **kw) == []
    # Baseline déclarée, recouvrement complet : promouvable.
    assert calibration_blockers(conn, baseline_run_id="a1", n_paired=501, **kw) == []
    # Baseline déclarée, 1 crop commun : bloqué.
    blockers = calibration_blockers(conn, baseline_run_id="a1", n_paired=1, **kw)
    assert len(blockers) == 1, blockers
    assert blockers[0].startswith("apparie:")
    assert "1 crops communs" in blockers[0] and "501" in blockers[0]


def test_baseline_sans_n_paired_bloque(conn):
    """Le champ n'est persisté nulle part aujourd'hui — c'est précisément ce
    qui rend D16 invisible. Un run qui compare sans dire sur combien de crops
    n'est pas promouvable."""
    _seed_etat_du_jour(conn)
    conn.execute(
        "UPDATE image_asset_dino_predictions SET computed_at='2026-09-01T00:00:00+00:00'"
    )
    blockers = calibration_blockers(
        conn, anchors_kind="2eur_all", encoder_version=_ENCODEUR_PROD,
        gold_sample_n=501, gold_n_crops=501, min_useful_classes=0,
        baseline_run_id="a1",
    )
    assert len(blockers) == 1 and blockers[0].startswith("apparie:")
    assert "sans n_paired" in blockers[0]


def test_n_paired_fait_l_aller_retour_en_base(conn):
    """D16 — la colonne ``n_paired INTEGER`` a été posée le 2026-08-19 dans
    ``0009_encoder_bench.sql`` et son miroir ``state/schema.sql``. Le
    recouvrement apparié doit donc revenir tel quel de la base.

    Inconditionnel exprès : la première rédaction se branchait sur la présence
    de la colonne, donc la retirer de la migration laissait le test vert. La
    branche « colonne absente » est couverte à part par
    ``test_record_run_leve_si_la_colonne_manque`` — le garde de ``record_run``
    n'est pas devenu du code mort, il est devenu dormant.
    """
    assert "n_paired" in {
        r[1] for r in conn.execute("PRAGMA table_info(encoder_bench_runs)")
    }, "0009_encoder_bench.sql ne déclare plus n_paired"
    record_run(conn, EncoderBenchRun(**dict(_run().to_dict(), n_paired=501)))
    assert get_run(conn, "r1")["n_paired"] == 501
    # Un run sans baseline n'a légitimement pas de recouvrement : NULL passe.
    record_run(conn, _run(run_id="r2"))
    assert get_run(conn, "r2")["n_paired"] is None

def test_record_run_leve_si_la_colonne_manque():
    """Le garde anti-perte-silencieuse de ``record_run``, exercé sur une base
    dont ``encoder_bench_runs`` précède la migration du 2026-08-19.

    Sans ce test, poser la colonne ferait passer le garde en code mort non
    couvert — et la prochaine colonne ajoutée au dataclass sans DDL retomberait
    dans la panne muette que D16 a coûtée (un run qui croit tracer, et ne trace
    rien).
    """
    vieux = sqlite3.connect(":memory:")
    vieux.row_factory = sqlite3.Row
    ddl = _MIGRATION.read_text(encoding="utf-8")
    # On retire la colonne comme si la migration n'avait pas été amendée.
    assert "\n  n_paired          INTEGER,\n" in ddl
    vieux.executescript(ddl.replace("\n  n_paired          INTEGER,\n", "\n"))
    assert "n_paired" not in {
        r[1] for r in vieux.execute("PRAGMA table_info(encoder_bench_runs)")
    }
    try:
        # Sans valeur renseignée : rien ne se perd, l'écriture passe.
        record_run(vieux, _run())
        assert get_run(vieux, "r1")["recall1"] == 0.81
        with pytest.raises(RuntimeError, match="n_paired"):
            record_run(vieux, EncoderBenchRun(**dict(_run().to_dict(), n_paired=501)))
    finally:
        vieux.close()


# ─── La fixture décrit-elle encore la vraie table ? (famille M1/M5) ──────────


def test_la_fixture_porte_la_meme_cle_que_le_vrai_schema(conn, tmp_path):
    """Une fixture est son propre référentiel : rien ne la rattrape quand le
    schéma bouge. Celle-ci a menti deux fois (3 colonnes sur 11, puis la clé
    d'avant 0010). Ce test la confronte au DDL RÉEL de ``state/schema.sql``,
    extrait par ``tests/_schema_reel.py`` — la clé et la nullabilité de
    ``encoder_version``, c'est-à-dire exactement ce dont ``_p1_blockers``
    dépend."""
    from tests._schema_reel import base_au_schema_reel

    def _forme(c):
        info = c.execute("PRAGMA table_info(dino_class_references)").fetchall()
        pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
        nn = {r[1]: r[3] for r in info}
        return pk, nn["encoder_version"]

    _seed_etat_du_jour(conn)
    fixture = _forme(conn)

    reelle_conn = base_au_schema_reel(tmp_path / "reelle.db")
    try:
        reelle = _forme(reelle_conn)
    finally:
        reelle_conn.close()

    assert fixture == reelle, (
        "la fixture _DDL_REFERENTIEL_DINO a dérivé de state/schema.sql : "
        f"fixture={fixture} vs réel={reelle}"
    )
