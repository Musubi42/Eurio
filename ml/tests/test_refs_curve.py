"""Tests de la courbe « références par classe » (``scripts.bench_refs_curve``).

Aucun modèle n'est chargé : tout ce qui est testé ici est le protocole —
le sous-échantillonnage par rang FPS, le garde qui vérifie que le ``.npz`` et
le build tracé décrivent la MÊME banque, la séparation des deux populations,
l'exclusion des crops fuités, et la détection du coude.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from review.bench_gold import GoldCrop  # noqa: E402
from scripts.bench_refs_curve import (  # noqa: E402
    check_bank_matches_build,
    class_max_rank,
    diminishing_returns,
    exemplars_per_class,
    load_reference_ranks,
    parse_class_set,
    split_populations,
    sub_bank,
    subsample_indices,
)
from training.foundation import AnchorBank  # noqa: E402


# ─── Fixtures minuscules ─────────────────────────────────────────────────────


def _bank() -> AnchorBank:
    """3 classes : A (2 exemplaires), B (1), C (0). 6 lignes."""
    eurio_ids = ["a", "a", "a", "b", "b", "c"]
    asset_ids = [None, "a1", "a2", None, "b1", None]
    matrix = np.eye(6, dtype=np.float32)
    return AnchorBank(
        eurio_ids=eurio_ids,
        matrix=matrix,
        encoder_version="dinov2-vitl14",
        anchors_kind="2eur_all",
        built_at="test",
        asset_ids=asset_ids,
    )


_RANKS = {"a1": 1, "a2": 2, "b1": 1}
_CANONICAL = {"a", "b", "c"}


def _crop(asset_id: str, class_id: str) -> tuple[GoldCrop, Path]:
    return (
        GoldCrop(
            asset_id=asset_id,
            truth_eurio_id=class_id,
            class_id=class_id,
            storage_path=f"{asset_id}.jpg",
            truth_country=class_id[:2],
            face="obverse",
            decided_at="2026-01-01",
            decided_by="test",
            review_kind="crop",
            training_eligible=1,
        ),
        Path(f"/tmp/{asset_id}.jpg"),
    )


# ─── Le sous-échantillonnage ─────────────────────────────────────────────────


def test_n0_ne_garde_que_les_canoniques_et_perd_aucune_classe():
    """À N=0 la banque est la banque canonique : une classe ne disparaît pas."""
    bank = _bank()
    keep = subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, 0)
    assert keep == [0, 3, 5]
    assert {bank.eurio_ids[i] for i in keep} == {"a", "b", "c"}


def test_n1_prend_le_rang_1_et_pas_le_rang_2():
    bank = _bank()
    keep = subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, 1)
    assert [bank.asset_ids[i] for i in keep] == [None, "a1", None, "b1", None]


def test_le_plafond_est_par_classe_pas_global():
    """Une classe pauvre reste pauvre à N élevé — c'est tout le sujet de la
    lecture « population variable »."""
    bank = _bank()
    keep = subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, 10)
    assert len(keep) == 6
    assert sum(1 for i in keep if bank.eurio_ids[i] == "b") == 2  # 1 canon + 1 ex.


def test_un_asset_sans_rang_leve_au_lieu_de_le_sauter_en_silence():
    bank = _bank()
    with pytest.raises(KeyError, match="a2"):
        subsample_indices(bank.eurio_ids, bank.asset_ids, {"a1": 1, "b1": 1}, 5)


def test_n_negatif_refuse():
    bank = _bank()
    with pytest.raises(ValueError):
        subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, -1)


def test_sub_bank_reindexe_la_matrice_dans_le_meme_ordre():
    bank = _bank()
    keep = subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, 1)
    sb = sub_bank(bank, bank.matrix, keep)
    assert sb.count == 5
    assert sb.eurio_ids == [bank.eurio_ids[i] for i in keep]
    np.testing.assert_array_equal(sb.matrix, bank.matrix[np.asarray(keep)])


def test_exemplars_per_class_ignore_les_canoniques():
    bank = _bank()
    assert exemplars_per_class(bank.eurio_ids, bank.asset_ids) == {"a": 2, "b": 1}


# ─── Le garde : le .npz et le build doivent décrire la même banque ───────────


def test_le_garde_passe_quand_npz_et_build_coincident():
    check_bank_matches_build(_bank(), _RANKS, _CANONICAL, "build-1")


def test_le_garde_refuse_un_build_absent():
    with pytest.raises(RuntimeError, match="Aucun build tracé"):
        check_bank_matches_build(_bank(), {}, set(), None)


def test_le_garde_refuse_une_banque_rebatie_sans_trace():
    """Le cas qui rendrait la courbe fausse en silence : le .npz porte un
    exemplaire que le build ne connaît pas."""
    with pytest.raises(RuntimeError, match="divergent"):
        check_bank_matches_build(_bank(), {"a1": 1, "b1": 1}, _CANONICAL, "build-1")


def test_le_garde_refuse_des_canoniques_divergents():
    with pytest.raises(RuntimeError, match="canoniques divergentes"):
        check_bank_matches_build(_bank(), _RANKS, {"a", "b"}, "build-1")


def test_le_garde_refuse_un_npz_sans_asset_ids():
    bank = _bank()
    bank.asset_ids = []
    with pytest.raises(RuntimeError, match="asset_ids"):
        check_bank_matches_build(bank, _RANKS, _CANONICAL, "build-1")


# ─── Lecture des rangs en base ───────────────────────────────────────────────


def _db_with_build(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE dino_anchor_builds (
          build_id TEXT PRIMARY KEY, anchors_kind TEXT, encoder_version TEXT,
          built_at TEXT);
        CREATE TABLE dino_class_references (
          anchors_kind TEXT, class_id TEXT, eurio_id TEXT, asset_id TEXT,
          method TEXT, rank INTEGER, build_id TEXT);
        INSERT INTO dino_anchor_builds VALUES
          ('vieux','2eur_all','dinov2-vitl14','2026-01-01T00:00:00'),
          ('recent','2eur_all','dinov2-vitl14','2026-08-19T14:36:14');
        INSERT INTO dino_class_references VALUES
          ('2eur_all','a','a',NULL,'canonical',0,'recent'),
          ('2eur_all','a','a','a1','fps',1,'recent'),
          ('2eur_all','a','a','a2','fps',2,'recent'),
          ('2eur_all','b','b',NULL,'canonical',0,'recent'),
          ('2eur_all','b','b','b1','fps',1,'recent'),
          ('2eur_all','c','c',NULL,'canonical',0,'recent'),
          ('2eur_all','z','z','z9','fps',1,'vieux');
        """
    )
    conn.commit()
    conn.close()
    return db


def test_load_reference_ranks_prend_le_build_le_plus_recent(tmp_path):
    conn = sqlite3.connect(_db_with_build(tmp_path))
    try:
        build_id, ranks, canonical = load_reference_ranks(
            conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14"
        )
    finally:
        conn.close()
    assert build_id == "recent"
    assert ranks == _RANKS  # z9 (build 'vieux') n'y est pas
    assert canonical == _CANONICAL


def test_load_reference_ranks_rend_none_sans_build(tmp_path):
    conn = sqlite3.connect(_db_with_build(tmp_path))
    try:
        build_id, ranks, canonical = load_reference_ranks(
            conn, anchors_kind="2eur_all", encoder_version="timm:inconnu"
        )
    finally:
        conn.close()
    assert (build_id, ranks, canonical) == (None, {}, set())


def test_une_ligne_fps_sans_rang_leve(tmp_path):
    db = _db_with_build(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO dino_class_references VALUES "
        "('2eur_all','a','a','a3','fps',NULL,'recent')"
    )
    conn.commit()
    try:
        with pytest.raises(ValueError, match="sans rang"):
            load_reference_ranks(
                conn, anchors_kind="2eur_all", encoder_version="dinov2-vitl14"
            )
    finally:
        conn.close()


# ─── Les deux populations, et la fuite ───────────────────────────────────────


def test_les_crops_qui_sont_des_ancres_sont_exclus_des_deux_lectures():
    """LE point méthodologique : un exemplaire de la banque noté contre cette
    banque rend une similarité de 1,0 avec lui-même."""
    crops = [_crop("a1", "a"), _crop("x1", "a"), _crop("b1", "b"), _crop("y1", "c")]
    pops = split_populations(
        crops,
        bank_class_ids={"a", "b", "c"},
        bank_asset_ids={"a1", "a2", "b1"},
        per_class={"a": 2, "b": 1},
        n_max=2,
    )
    variable = next(p for p in pops if p.name == "variable")
    assert {c.asset_id for c, _p in variable.crops} == {"x1", "y1"}


def test_population_constante_ne_garde_que_les_classes_pleines():
    crops = [_crop("x1", "a"), _crop("x2", "b"), _crop("x3", "c")]
    pops = split_populations(
        crops,
        bank_class_ids={"a", "b", "c"},
        bank_asset_ids=set(),
        per_class={"a": 2, "b": 1},
        n_max=2,
    )
    constante = next(p for p in pops if p.name == "constante")
    assert {c.class_id for c, _p in constante.crops} == {"a"}
    variable = next(p for p in pops if p.name == "variable")
    assert variable.n_crops == 3


def test_les_crops_hors_banque_sont_ecartes():
    crops = [_crop("x1", "a"), _crop("x2", "inconnue")]
    pops = split_populations(
        crops, bank_class_ids={"a"}, bank_asset_ids=set(),
        per_class={"a": 1}, n_max=1,
    )
    assert pops[0].n_crops == 1


def test_la_courbe_fuitee_n_est_pas_produite_par_defaut():
    crops = [_crop("a1", "a")]
    assert [p.name for p in split_populations(
        crops, {"a"}, {"a1"}, {"a": 1}, 1)] == ["variable", "constante"]
    assert [p.name for p in split_populations(
        crops, {"a"}, {"a1"}, {"a": 1}, 1, include_leaked=True)] == [
        "variable", "constante", "fuitee"]


# ─── Le coude ────────────────────────────────────────────────────────────────


def _pt(n: int, r1: float) -> dict:
    return {"n_refs": n, "recall1": r1}


def test_le_coude_est_le_premier_n_dont_TOUT_le_reste_est_plat():
    pts = [_pt(0, 0.50), _pt(1, 0.60), _pt(2, 0.68), _pt(5, 0.70), _pt(10, 0.705)]
    knee = diminishing_returns(pts)
    assert knee is not None
    assert knee["knee_n_refs"] == 2


def test_un_creux_initial_ne_fait_pas_passer_le_coude_pour_zero():
    """Le cas RÉEL mesuré sur ``dinov2_vits14`` : la première référence FPS —
    la plus diversifiante, donc la plus atypique — FAIT BAISSER le recall
    (53,1 % → 50,1 %) avant que la courbe ne remonte. Un détecteur qui prend
    le premier segment plat rend « coude à N=0 », c'est-à-dire « ne validez
    aucun crop » : le contresens opérationnel exact."""
    pts = [_pt(0, 0.531), _pt(1, 0.501), _pt(2, 0.546), _pt(3, 0.573),
           _pt(5, 0.664), _pt(8, 0.739), _pt(10, 0.755)]
    knee = diminishing_returns(pts)
    assert knee is not None
    assert knee["knee_n_refs"] == 8, "le coude est là où la courbe PLIE, pas où elle creuse"
    assert knee["marginal_gain_pt_per_ref"] == pytest.approx(0.8, abs=0.05)


def test_pas_de_coude_quand_la_courbe_monte_encore():
    pts = [_pt(0, 0.30), _pt(1, 0.45), _pt(2, 0.60), _pt(3, 0.75)]
    assert diminishing_returns(pts) is None


def test_coude_indetectable_sur_un_seul_point():
    assert diminishing_returns([_pt(0, 0.5)]) is None
    assert diminishing_returns([{"n_refs": 0, "recall1": None}]) is None


# ─── La restriction à un sous-ensemble de classes ────────────────────────────
#
# Pourquoi ces tests existent : le plancher `min_exemplars=2` a été posé sur la
# foi d'un point AGRÉGÉ de la courbe (N=1 à 50,1 % contre N=0 à 53,1 %). Ce
# point décrit une banque où TOUTES les classes sont plafonnées à 1 ; il ne dit
# rien d'une banque où 68 classes en ont 1 et les autres sont pleines. Poser la
# question correctement demande de restreindre — et les deux restrictions
# possibles ne mesurent pas la même chose (cf. `--bank-classes` / `--gold-classes`).


def test_bank_classes_ne_plafonne_que_les_classes_demandees():
    """Le cœur de la mesure : `a` est plafonnée, `b` garde son exemplaire."""
    bank = _bank()
    keep = subsample_indices(
        bank.eurio_ids, bank.asset_ids, _RANKS, 0, cap_classes={"a"}
    )
    assert [bank.asset_ids[i] for i in keep] == [None, None, "b1", None]


def test_sans_bank_classes_le_plafond_reste_global():
    bank = _bank()
    assert subsample_indices(
        bank.eurio_ids, bank.asset_ids, _RANKS, 0, cap_classes=None
    ) == subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, 0)


def test_bank_classes_inconnue_ne_plafonne_rien():
    """Une classe absente de la banque ne doit pas silencieusement tout garder
    OU tout couper : les classes réelles restent intactes, point."""
    bank = _bank()
    keep = subsample_indices(
        bank.eurio_ids, bank.asset_ids, _RANKS, 0, cap_classes={"zzz"}
    )
    assert len(keep) == 6


def test_rank_order_last_garde_le_moins_diversifiant():
    """`last` garde le DERNIER rang de chaque classe, pas le premier — c'est la
    sonde qui distingue « un exemplaire de trop » de « un exemplaire ATYPIQUE
    de trop »."""
    bank = _bank()
    keep = subsample_indices(
        bank.eurio_ids, bank.asset_ids, _RANKS, 1, order="last"
    )
    assert [bank.asset_ids[i] for i in keep] == [None, "a2", None, "b1", None]


def test_rank_order_last_a_n0_est_identique_a_first():
    bank = _bank()
    assert subsample_indices(
        bank.eurio_ids, bank.asset_ids, _RANKS, 0, order="last"
    ) == subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, 0)


def test_rank_order_inconnu_refuse():
    bank = _bank()
    with pytest.raises(ValueError, match="order"):
        subsample_indices(bank.eurio_ids, bank.asset_ids, _RANKS, 1, order="middle")


def test_class_max_rank_est_par_classe():
    bank = _bank()
    assert class_max_rank(bank.eurio_ids, bank.asset_ids, _RANKS) == {"a": 2, "b": 1}


# ─── L'analyse des ensembles de classes passés en ligne de commande ──────────


def test_parse_class_set_none_veut_dire_aucune_restriction():
    assert parse_class_set(None) is None


def test_parse_class_set_liste_inline():
    assert parse_class_set("a, b ,c") == {"a", "b", "c"}


def test_parse_class_set_fichier_avec_commentaires(tmp_path):
    f = tmp_path / "classes.txt"
    f.write_text("# les 68\na\n\nb  # celle-ci\n", encoding="utf-8")
    assert parse_class_set(f"@{f}") == {"a", "b"}


def test_parse_class_set_vide_refuse_au_lieu_de_passer_pour_aucune_restriction():
    """Le piège muet : un fichier vide qui se lirait « pas de restriction »
    rendrait la courbe globale sous l'étiquette d'une mesure restreinte."""
    with pytest.raises(ValueError, match="vide"):
        parse_class_set(" , ")
