"""Lot 3 — ``--iteration`` : noter une itération du lab avec le juge.

Une itération n'est PAS un dossier de candidat : ses deux pièces vivent dans
``checkpoints/`` et ``embeddings/``. Ces tests gardent trois choses :

1. le constructeur lit les **chemins explicites** (et pas ce qui traîne ailleurs
   dans l'arbre de l'itération — cf. ``dataset/``) ;
2. l'absence d'un artefact **échoue**, elle ne se replie pas en silence ;
3. le CLI câble bien ``--iteration`` (candidat) et ``--source-iteration-id``
   (filtre du corpus) sur deux choses différentes — ils portaient le même nom
   avant ce lot.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts.replay_corpus import candidate_from_iteration, load_candidate
from store.scan_corpus import ScanCapture, ScanCorpusStore


# ─── Fixtures : une itération du lab, telle que le lab la range ──────────────


def _centroids_json(path: Path, coins: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "model": "stub",
                "embedding_dim": 3,
                "coins": {
                    cid: {
                        "name": cid,
                        "class_kind": "eurio_id",
                        "eurio_ids": [cid],
                        "embedding": vec,
                    }
                    for cid, vec in coins.items()
                },
            }
        )
    )


@pytest.fixture()
def lab_root(tmp_path: Path) -> Path:
    """Arbre d'itération conforme à ml/lab/iterations/<iid>/."""
    root = tmp_path / "iterations"
    it = root / "caf98145032c"
    _centroids_json(
        it / "embeddings" / "embeddings_v1.json",
        {"coin-red": [1.0, 0.0, 0.0], "coin-green": [0.0, 1.0, 0.0]},
    )
    (it / "embeddings" / "coin_embeddings.json").write_text("{}")
    (it / "checkpoints").mkdir(parents=True)
    (it / "checkpoints" / "best_model.pth").write_bytes(b"stub-pth")
    (it / "tflite").mkdir()
    (it / "tflite" / "eurio_embedder_v1.tflite").write_bytes(b"stub-tflite")
    return root


def test_construit_le_candidat_depuis_les_deux_sous_dossiers(lab_root: Path) -> None:
    cand = candidate_from_iteration("caf98145032c", lab_root=lab_root)
    assert cand.label == "caf98145032c"
    assert cand.centroids_path == lab_root / "caf98145032c/embeddings/embeddings_v1.json"
    assert cand.model_path == lab_root / "caf98145032c/checkpoints/best_model.pth"
    assert cand.has_thresholds is False  # pas de thresholds.json → répond toujours


def test_le_defaut_est_le_checkpoint_pas_le_tflite(lab_root: Path) -> None:
    """Deux artefacts coexistent ; le défaut doit être nommé, pas subi.

    ``load_candidate`` préfère ``*.tflite`` ; ici le défaut est
    ``best_model.pth``, et ``--iteration-model tflite`` bascule explicitement.
    """
    assert candidate_from_iteration("caf98145032c", lab_root=lab_root).model_path.suffix == ".pth"
    tfl = candidate_from_iteration("caf98145032c", lab_root=lab_root, model_kind="tflite")
    assert tfl.model_path.suffix == ".tflite"


def test_ignore_ce_qui_traine_ailleurs_dans_l_iteration(lab_root: Path) -> None:
    """Le contraste avec ``load_candidate``, qui balaie en ``rglob``.

    Une itération porte un ``dataset/`` (parfois un symlink mort). Un
    ``embeddings_v1.json`` qui y traîne ne doit pas pouvoir être choisi.
    """
    it = lab_root / "caf98145032c"
    _centroids_json(it / "dataset" / "embeddings_v1.json", {"leurre": [1.0, 0.0, 0.0]})

    assert candidate_from_iteration("caf98145032c", lab_root=lab_root).centroids_path == (
        it / "embeddings" / "embeddings_v1.json"
    )
    # rglob trie : 'dataset/...' passe avant 'embeddings/...' → load_candidate
    # prendrait le leurre. C'est pourquoi on n'assouplit pas son contrat.
    assert load_candidate(it).centroids_path == it / "dataset" / "embeddings_v1.json"


def test_iteration_inconnue_echoue(lab_root: Path) -> None:
    with pytest.raises(SystemExit, match="Itération introuvable"):
        candidate_from_iteration("0000deadbeef", lab_root=lab_root)


def test_centroides_absents_echouent(lab_root: Path) -> None:
    (lab_root / "caf98145032c/embeddings/embeddings_v1.json").unlink()
    with pytest.raises(SystemExit, match="embeddings_v1.json"):
        candidate_from_iteration("caf98145032c", lab_root=lab_root)


def test_checkpoint_absent_echoue(lab_root: Path) -> None:
    (lab_root / "caf98145032c/checkpoints/best_model.pth").unlink()
    with pytest.raises(SystemExit, match="best_model.pth"):
        candidate_from_iteration("caf98145032c", lab_root=lab_root)


def test_symlink_casse_echoue_au_lieu_de_passer(lab_root: Path) -> None:
    """Cas réel : ml/lab/iterations/53caddf5ab54 porte un symlink mort."""
    ckpt = lab_root / "caf98145032c/checkpoints/best_model.pth"
    ckpt.unlink()
    ckpt.symlink_to(lab_root / "nulle-part" / "best_model.pth")
    with pytest.raises(SystemExit, match="symlink"):
        candidate_from_iteration("caf98145032c", lab_root=lab_root)


def test_thresholds_de_l_iteration_sont_lus(lab_root: Path) -> None:
    (lab_root / "caf98145032c/thresholds.json").write_text(
        '{"top1_min": 0.42, "margin_min": 0.1}'
    )
    cand = candidate_from_iteration("caf98145032c", lab_root=lab_root)
    assert (cand.top1_min, cand.margin_min) == (0.42, 0.1)
    assert cand.has_thresholds is True


# ─── Le CLI — c'est lui qui a changé de forme, donc c'est lui qu'on exerce ───


class _StubEmbedder:
    def embed(self, image: Image.Image) -> np.ndarray:
        vec = np.asarray(image.resize((1, 1))).reshape(-1)[:3].astype(np.float32)
        return vec / (np.linalg.norm(vec) or 1.0)


@pytest.fixture()
def corpus(tmp_path: Path) -> ScanCorpusStore:
    store = ScanCorpusStore(db_path=tmp_path / "scan_corpus.db")
    store.frames_dir.mkdir(parents=True)
    for cid, color, gt, cond, bundle in (
        ("bb00000000000001", (255, 0, 0), "coin-red", "bright_plain", "pull_avril"),
        ("bb00000000000002", (0, 255, 0), "coin-green", "bright_plain", "pull_juin"),
    ):
        Image.new("RGB", (224, 224), color).save(store.frames_dir / f"{cid}.crop.png")
        store.upsert_capture(
            ScanCapture(
                capture_id=cid,
                eurio_id=gt,
                condition=cond,
                captured_at="2026-08-25T00:00:00",
                raw_path=f"frames/{cid}.raw.jpg",
                crop_path=f"frames/{cid}.crop.png",
                bundle_source=bundle,
            )
        )
    return store


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    import sys

    import training.eval.evaluate_real_photos as erp

    monkeypatch.setattr(erp, "load_embedder", lambda p: _StubEmbedder())
    monkeypatch.setattr(sys, "argv", ["replay_corpus", *argv])
    from scripts.replay_corpus import main

    main()


def test_cli_iteration_note_le_corpus_de_bout_en_bout(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "run"
    _run_main(
        monkeypatch,
        [
            "--iteration", "caf98145032c",
            "--lab-root", str(lab_root),
            "--db", str(corpus.db_path),
            "--no-eq",
            "--out", str(out),
        ],
    )
    sc = json.loads((out / "scorecard.json").read_text())
    assert sc["candidate"] == "caf98145032c"
    assert sc["n_frames"] == 2
    assert sc["corpus_version"]  # jamais vide : sinon la mesure est irreproductible
    assert sc["primary"]["r_at_1_eq"] == 1.0
    assert (out / "predictions.jsonl").read_text().count("\n") == 2


def test_cli_bundle_source_filtre_et_s_inscrit_dans_la_scorecard(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "run_juin"
    _run_main(
        monkeypatch,
        [
            "--iteration", "caf98145032c",
            "--lab-root", str(lab_root),
            "--db", str(corpus.db_path),
            "--bundle-source", "pull_juin",
            "--no-eq",
            "--out", str(out),
        ],
    )
    sc = json.loads((out / "scorecard.json").read_text())
    assert sc["n_frames"] == 1
    assert sc["filter"]["bundle_sources"] == ["pull_juin"]


def test_cli_source_iteration_id_filtre_le_corpus_et_non_le_candidat(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Les deux drapeaux portaient le même nom : ce test tient la frontière.

    ``--iteration`` choisit le modèle noté ; ``--source-iteration-id`` filtre
    les frames. Aucune capture ne porte cette provenance → corpus vide.
    """
    with pytest.raises(SystemExit, match="Corpus vide"):
        _run_main(
            monkeypatch,
            [
                "--iteration", "caf98145032c",
                "--lab-root", str(lab_root),
                "--db", str(corpus.db_path),
                "--source-iteration-id", "caf98145032c",
                "--no-eq",
                "--out", str(tmp_path / "vide"),
            ],
        )


def test_cli_source_iteration_id_est_inscrit_dans_la_scorecard(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Et quand il ne filtre rien, il vaut None dans la sortie — pas l'iid."""
    out = tmp_path / "run"
    _run_main(
        monkeypatch,
        [
            "--iteration", "caf98145032c",
            "--lab-root", str(lab_root),
            "--db", str(corpus.db_path),
            "--no-eq",
            "--out", str(out),
        ],
    )
    sc = json.loads((out / "scorecard.json").read_text())
    assert sc["filter"]["source_iteration_id"] is None


def test_cli_exige_une_source_de_candidat_et_une_seule(monkeypatch) -> None:
    import sys

    from scripts.replay_corpus import main

    monkeypatch.setattr(sys, "argv", ["replay_corpus"])
    with pytest.raises(SystemExit):
        main()
    monkeypatch.setattr(
        sys, "argv", ["replay_corpus", "--candidate", "/tmp/x", "--iteration", "abc"]
    )
    with pytest.raises(SystemExit):
        main()


# ─── La scorecard doit DIRE ses échecs, pas les fondre dans la couverture ────


def test_scorecard_distingue_echec_et_abstention(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Une frame illisible ne doit pas ressembler à une abstention.

    Sans le bloc ``errors``, un run où tout le raw échoue à se normaliser sort
    ``r@1 = 0.0`` / ``coverage = 0.0`` — exactement ce que sortirait un modèle
    prudent. C'est le silence que ce test tient.
    """
    (corpus.frames_dir / "bb00000000000002.crop.png").unlink()
    out = tmp_path / "run"
    _run_main(
        monkeypatch,
        [
            "--iteration", "caf98145032c",
            "--lab-root", str(lab_root),
            "--db", str(corpus.db_path),
            "--no-eq",
            "--out", str(out),
        ],
    )
    sc = json.loads((out / "scorecard.json").read_text())
    assert sc["errors"]["n"] == 1
    assert sc["errors"]["rate"] == 0.5
    assert sc["errors"]["by_kind"] == {"load_failed": 1}
    assert sc["abstention"]["coverage"] == 0.5


def test_scorecard_sans_echec_dit_zero_explicitement(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "run"
    _run_main(
        monkeypatch,
        [
            "--iteration", "caf98145032c",
            "--lab-root", str(lab_root),
            "--db", str(corpus.db_path),
            "--no-eq",
            "--out", str(out),
        ],
    )
    sc = json.loads((out / "scorecard.json").read_text())
    assert sc["errors"] == {"n": 0, "rate": 0.0, "by_kind": {}}


# ─── L'espace de labels — le r@1 global ne se lit jamais seul ────────────────


@pytest.fixture()
def corpus_avec_classe_absente(tmp_path: Path) -> ScanCorpusStore:
    """3 frames, dont une d'une classe que le candidat NE PORTE PAS.

    C'est la situation mesurée le 2026-08-25 : l'itération `caf98145032c`
    porte 3 centroïdes et le corpus de juin 17 classes. La frame de trop est
    fausse par construction — aucun modèle ne peut la réussir.
    """
    store = ScanCorpusStore(db_path=tmp_path / "scan_corpus.db")
    store.frames_dir.mkdir(parents=True)
    for cid, color, gt in (
        ("cc00000000000001", (255, 0, 0), "coin-red"),
        ("cc00000000000002", (0, 255, 0), "coin-green"),
        ("cc00000000000003", (0, 0, 255), "coin-absent-du-modele"),
    ):
        Image.new("RGB", (224, 224), color).save(store.frames_dir / f"{cid}.crop.png")
        store.upsert_capture(
            ScanCapture(
                capture_id=cid,
                eurio_id=gt,
                condition="bright_plain",
                captured_at="2026-08-25T00:00:00",
                raw_path=f"frames/{cid}.raw.jpg",
                crop_path=f"frames/{cid}.crop.png",
            )
        )
    return store


def test_is_coverable_suit_la_regle_de_compute_hits(lab_root: Path) -> None:
    """Parité stricte : couvrable ⇔ un centroïde PEUT être compté juste."""
    from training.eval.equivalence import EquivalenceMap
    from training.eval.evaluate_real_photos import load_centroids

    from scripts.replay_corpus import is_coverable

    cents = load_centroids(lab_root / "caf98145032c/embeddings/embeddings_v1.json")
    assert is_coverable("coin-red", cents, None) is True
    assert is_coverable("coin-absent-du-modele", cents, None) is False
    # …et l'équivalence design_group élargit la couvrabilité, comme elle
    # élargit la correction.
    eq = EquivalenceMap({"coin-red": "grp-1", "coin-jumeau": "grp-1"})
    assert is_coverable("coin-jumeau", cents, eq) is True
    assert is_coverable("coin-absent-du-modele", cents, eq) is False


def _run_on(corpus: ScanCorpusStore, lab_root: Path, out: Path, monkeypatch) -> dict:
    _run_main(
        monkeypatch,
        [
            "--iteration", "caf98145032c",
            "--lab-root", str(lab_root),
            "--db", str(corpus.db_path),
            "--no-eq",
            "--out", str(out),
        ],
    )
    return json.loads((out / "scorecard.json").read_text())


def test_label_space_compte_les_classes_hors_du_candidat(
    corpus_avec_classe_absente: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    sc = _run_on(corpus_avec_classe_absente, lab_root, tmp_path / "run", monkeypatch)
    assert sc["label_space"] == {
        "n_candidate_classes": 2,
        "n_ground_truth_classes": 3,
        "n_covered_classes": 2,
        "n_uncoverable_classes": 1,
        "uncoverable_classes": ["coin-absent-du-modele"],
        "n_frames_covered": 2,
        "n_frames_uncoverable": 1,
        "frame_coverage": round(2 / 3, 4),
        # L'espace de labels est GRAVÉ dans la scorecard, pas seulement
        # contrôlé par le garde `--baseline` : c'est ce qui rend deux runs
        # notés séparément vérifiables après coup.
        "mesh_basis": "eurio_id",
        "n_mesh_classes": 2,
        "mesh_digest": "2a4b506822b08fca",
    }


def test_r_at_1_on_covered_est_rendu_avec_son_n(
    corpus_avec_classe_absente: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Les deux, jamais l'un sans l'autre — et le global est bien le dilué."""
    sc = _run_on(corpus_avec_classe_absente, lab_root, tmp_path / "run", monkeypatch)
    assert sc["primary"]["r_at_1_eq"] == pytest.approx(2 / 3, abs=1e-4)  # dilué
    assert sc["primary"]["r_at_1_on_covered"] == 1.0  # la vraie valeur
    assert sc["primary"]["n_on_covered"] == 2
    # by_condition porte le même couple, à la maille fine.
    assert sc["by_condition"]["bright_plain"]["n"] == 3
    assert sc["by_condition"]["bright_plain"]["n_covered"] == 2
    assert sc["by_condition"]["bright_plain"]["r_at_1_on_covered"] == 1.0


def test_frame_non_couvrable_est_marquee_et_ne_peut_pas_etre_juste(
    corpus_avec_classe_absente: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "run"
    _run_on(corpus_avec_classe_absente, lab_root, out, monkeypatch)
    preds = {
        json.loads(line)["capture_id"]: json.loads(line)
        for line in (out / "predictions.jsonl").read_text().splitlines()
    }
    absente = preds["cc00000000000003"]
    assert absente["coverable"] is False
    assert absente["correct_eq_top1"] is False
    assert preds["cc00000000000001"]["coverable"] is True


def test_frame_illisible_garde_sa_couvrabilite(
    corpus_avec_classe_absente: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Échec de lecture et absence de classe sont DEUX causes, pas une.

    Une frame d'une classe connue qui ne se charge pas reste couvrable : c'est
    un défaut d'image, pas un défaut d'espace de labels.
    """
    (corpus_avec_classe_absente.frames_dir / "cc00000000000001.crop.png").unlink()
    out = tmp_path / "run"
    sc = _run_on(corpus_avec_classe_absente, lab_root, out, monkeypatch)
    preds = {
        json.loads(line)["capture_id"]: json.loads(line)
        for line in (out / "predictions.jsonl").read_text().splitlines()
    }
    assert preds["cc00000000000001"]["error"].startswith("load_failed")
    assert preds["cc00000000000001"]["coverable"] is True
    assert sc["errors"]["n"] == 1
    assert sc["label_space"]["n_frames_uncoverable"] == 1  # toujours la seule absente


# ─── Le refus de comparer deux espaces différents ───────────────────────────


def _candidate_dir(path: Path, coins: dict[str, list[float]]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _centroids_json(path / "embeddings_v1.json", coins)
    (path / "model.tflite").write_bytes(b"stub")
    return path


def test_meme_espace_passe(tmp_path: Path) -> None:
    from scripts.replay_corpus import assert_same_label_space

    a = load_candidate(_candidate_dir(tmp_path / "a", {"x": [1.0, 0.0, 0.0]}))
    b = load_candidate(_candidate_dir(tmp_path / "b", {"x": [0.0, 1.0, 0.0]}))
    assert_same_label_space(a, b, None) is None


def test_espace_different_refuse_avec_le_detail(tmp_path: Path) -> None:
    from scripts.replay_corpus import assert_same_label_space

    a = load_candidate(_candidate_dir(tmp_path / "a", {"x": [1.0, 0.0, 0.0]}))
    b = load_candidate(
        _candidate_dir(tmp_path / "b", {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0]})
    )
    with pytest.raises(SystemExit) as exc:
        assert_same_label_space(a, b, None)
    msg = str(exc.value)
    assert "Espaces de labels différents" in msg
    assert "1 seulement chez la baseline : y" in msg  # le détail, pas juste un refus


def test_meme_maille_design_group_ne_refuse_pas(tmp_path: Path) -> None:
    """Deux orthographes du même jeu ne sont PAS deux espaces différents.

    L'un entraîne en `eurio_id`, l'autre en `design_group` : la correction est
    jugée sur la maille, le garde aussi. Sinon il refuserait la comparaison la
    plus légitime du chantier.
    """
    from training.eval.equivalence import EquivalenceMap

    from scripts.replay_corpus import assert_same_label_space

    a = load_candidate(_candidate_dir(tmp_path / "a", {"be-2007": [1.0, 0.0, 0.0]}))
    b = load_candidate(_candidate_dir(tmp_path / "b", {"grp-1": [1.0, 0.0, 0.0]}))
    eq = EquivalenceMap({"be-2007": "grp-1"})
    assert_same_label_space(a, b, eq) is None
    # …et sans la maille, ils sont bien différents : le test ci-dessus mesure
    # l'effet de l'équivalence, pas une tautologie.
    with pytest.raises(SystemExit):
        assert_same_label_space(a, b, None)


def test_cli_baseline_espace_different_refuse_avant_toute_inference(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Et rien n'est écrit sur disque — pas de prédictions à mal relire."""
    baseline = _candidate_dir(tmp_path / "base", {"coin-red": [1.0, 0.0, 0.0]})
    out = tmp_path / "run"
    with pytest.raises(SystemExit, match="Espaces de labels différents"):
        _run_main(
            monkeypatch,
            [
                "--iteration", "caf98145032c",
                "--lab-root", str(lab_root),
                "--db", str(corpus.db_path),
                "--baseline", str(baseline),
                "--no-eq",
                "--out", str(out),
            ],
        )
    assert not out.exists()


def test_cli_baseline_meme_espace_produit_le_mcnemar(
    corpus: ScanCorpusStore, lab_root: Path, tmp_path: Path, monkeypatch
) -> None:
    baseline = _candidate_dir(
        tmp_path / "base", {"coin-red": [1.0, 0.0, 0.0], "coin-green": [0.0, 1.0, 0.0]}
    )
    out = tmp_path / "run"
    _run_main(
        monkeypatch,
        [
            "--iteration", "caf98145032c",
            "--lab-root", str(lab_root),
            "--db", str(corpus.db_path),
            "--baseline", str(baseline),
            "--no-eq",
            "--out", str(out),
        ],
    )
    sc = json.loads((out / "scorecard.json").read_text())
    assert sc["mcnemar"]["n_paired"] == 2
    assert sc["baseline_primary"]["r_at_1_on_covered"] == 1.0


# ─── La faille du garde : il se contournait en ne l'appelant pas ─────────────
#
# `assert_same_label_space` ne s'exécute que si `--baseline` est passé. Deux
# runs notés SÉPARÉMENT, puis comparés à la main, passaient sans un mot. Ce
# n'est pas un oubli qu'on corrige par de la discipline : une comparaison à la
# main N'A pas de garde, quelle que soit la bonne volonté de celui qui la fait.
# La fermeture a deux moitiés — l'empreinte dans l'artefact, et un chemin de
# comparaison qui, lui, passe par le garde.


def test_lempreinte_distingue_deux_espaces_de_meme_TAILLE():
    """LE test de ce lot.

    Un COMPTE de classes déclarerait comparables deux candidats à 60 classes
    chacun portant deux ensembles différents. C'est exactement la confusion qui
    rend un McNemar illisible, et elle est invisible à l'œil.
    """
    from scripts.replay_corpus import mesh_digest

    a = {f"c{i}" for i in range(60)}
    b = {f"c{i}" for i in range(1, 61)}
    assert len(a) == len(b) == 60
    assert mesh_digest(a) != mesh_digest(b)
    # Stable, et insensible à l'ordre d'insertion.
    assert mesh_digest(a) == mesh_digest(set(sorted(a, reverse=True)))


def test_lempreinte_suit_la_maille_pas_lorthographe():
    """Deux orthographes du même jeu ont la MÊME empreinte — sinon le garde
    refuserait la comparaison la plus légitime du chantier."""
    from training.eval.equivalence import EquivalenceMap

    from scripts.replay_corpus import label_mesh, mesh_digest

    eq = EquivalenceMap({"be-2007": "grp-1"})
    assert mesh_digest(label_mesh({"be-2007"}, eq)) == mesh_digest(
        label_mesh({"grp-1"}, eq)
    )
    # …et sans la maille, ils sont bien différents : la ligne ci-dessus mesure
    # l'effet de l'équivalence, pas une tautologie.
    assert mesh_digest(label_mesh({"be-2007"}, None)) != mesh_digest(
        label_mesh({"grp-1"}, None)
    )


def _card(digest, *, version="v1", filtre=None, n=60):
    return {
        "candidate": f"cand-{digest}",
        "corpus_version": version,
        "filter": filtre if filtre is not None else {"cohort_id": None},
        "label_space": {"mesh_digest": digest, "n_mesh_classes": n,
                        "mesh_basis": "eurio_id"},
        "primary": {"r_at_1_eq": 0.5},
    }


def test_deux_runs_notes_separement_sont_refuses_si_les_espaces_different():
    """Le cas que le garde laissait passer : aucun `--baseline` n'a été
    utilisé, donc `assert_same_label_space` n'a jamais tourné."""
    from scripts.replay_corpus import assert_comparable_runs

    with pytest.raises(SystemExit) as exc:
        assert_comparable_runs(_card("aaaa"), _card("bbbb"), a_nom="A", b_nom="B")
    msg = str(exc.value)
    assert "espaces de labels DIFFÉRENTS" in msg
    assert "aaaa" in msg and "bbbb" in msg


def test_un_corpus_ou_un_filtre_different_est_refuse_aussi():
    """Même modèle, deux jeux : le delta ne dit rien. `include_rejected` et les
    conditions sont les réglages qui CHANGENT le jeu noté."""
    from scripts.replay_corpus import assert_comparable_runs

    with pytest.raises(SystemExit, match="corpus DIFFÉRENTS"):
        assert_comparable_runs(_card("aaaa"), _card("aaaa", version="v2"),
                               a_nom="A", b_nom="B")
    with pytest.raises(SystemExit, match="filtres DIFFÉRENTS"):
        assert_comparable_runs(
            _card("aaaa"),
            _card("aaaa", filtre={"cohort_id": None, "include_rejected": True}),
            a_nom="A", b_nom="B")


def test_une_scorecard_sans_empreinte_est_refusee_pas_presumee_compatible():
    """Non vérifiable n'est pas compatible.

    Sans ce refus, la seule scorecard qu'on ne peut PAS contrôler — celle notée
    avant que le garde n'existe — serait la seule à passer.
    """
    from scripts.replay_corpus import assert_comparable_runs

    vieille = _card("aaaa")
    vieille["label_space"].pop("mesh_digest")
    with pytest.raises(SystemExit, match="ABSENTE"):
        assert_comparable_runs(vieille, _card("aaaa"), a_nom="vieille", b_nom="B")


def test_deux_runs_comparables_passent_et_rendent_le_mcnemar(tmp_path: Path):
    """Le pendant positif : le chemin gardé DOIT exister, sinon interdire la
    comparaison à la main revient à interdire la comparaison."""
    import json

    from scripts.replay_corpus import compare_runs

    def _run(nom, verdicts):
        d = tmp_path / nom
        d.mkdir()
        (d / "scorecard.json").write_text(json.dumps(_card("aaaa") | {
            "candidate": nom}), encoding="utf-8")
        with (d / "predictions.jsonl").open("w", encoding="utf-8") as fh:
            for i, ok in enumerate(verdicts):
                fh.write(json.dumps({
                    "capture_id": f"f{i}", "eurio_id": "x", "condition": "bright",
                    "top5": [["x", 0.9]], "abstained": False,
                    "correct_strict_top1": ok, "correct_eq_top1": ok,
                    "correct_eq_top5": ok, "error": None, "coverable": True,
                }) + "\n")
        return d

    a = _run("base", [True, True, False, False])
    b = _run("cand", [True, False, True, True])
    res = compare_runs(a, b)
    mc = res["mcnemar"]
    assert mc["n_paired"] == 4
    assert mc["contingency"] == {
        "both_correct": 1, "baseline_only": 1,
        "candidate_only": 2, "both_incorrect": 0,
    }
    assert (b / "comparison.json").exists(), "la comparaison doit laisser une trace"


def test_la_scorecard_grave_lempreinte_de_son_espace(tmp_path: Path):
    """Sans elle, l'écart n'est vérifiable qu'en relançant les deux runs — donc
    jamais, six mois plus tard."""
    from scripts.replay_corpus import FramePrediction, build_scorecard, load_candidate

    cand = load_candidate(_candidate_dir(tmp_path / "a", {"x": [1.0, 0.0, 0.0]}))
    preds = [FramePrediction(
        capture_id="f0", eurio_id="x", condition="bright", top5=[("x", 0.9)],
        abstained=False, correct_strict_top1=True, correct_eq_top1=True,
        correct_eq_top5=True,
    )]
    card = build_scorecard(cand, preds, None, {"cohort_id": None}, "v1", {"x"})
    ls = card["label_space"]
    assert ls["mesh_digest"] is not None
    assert ls["n_mesh_classes"] == 1
    assert ls["mesh_basis"] == "eurio_id"
