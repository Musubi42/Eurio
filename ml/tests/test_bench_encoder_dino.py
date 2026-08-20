"""Tests du câblage du banc multi-encodeurs (D4, D5).

Ce que ces tests protègent, dans l'ordre :

1. **le banc ne définit plus son propre jeu d'évaluation** — il lit le gold
   figé et versionné, il ne rejoue aucune requête de sélection (D5) ;
2. **le blocage de calibration est visible dans le chemin exécutable** —
   bannière en tête ET en pied, seuil refusé, run marqué `provisional` (D4) ;
3. la distinction qui rend le banc utilisable : **P3 ne bloque pas la
   comparaison d'encodeurs**, il bloque la proposition de seuil. Un banc qu'on
   ne peut pas lancer nuit autant qu'un banc qui ment ;
4. un run qui ne monte pas au canonique ne disparaît pas en silence.

Aucun encodage réel ici : ``_bench_model`` est doublé. Le banc ré-encode des
milliers d'images, ce n'est pas ce qu'on teste.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from review.bench_gold import GoldCrop  # noqa: E402
from scripts import bench_encoder_dino as bench  # noqa: E402
from training.foundation import AnchorBank  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _crop(asset_id: str, truth: str, class_id: str | None = None) -> GoldCrop:
    return GoldCrop(
        asset_id=asset_id,
        truth_eurio_id=truth,
        class_id=class_id or truth,
        storage_path=f"{asset_id}.jpg",
        truth_country=truth[:2],
        face="obverse",
        decided_at="2026-08-01T00:00:00+00:00",
        decided_by="test",
        review_kind="ebay",
        training_eligible=1,
    )


GOLD_ROWS = [
    _crop("a1", "fr-2010-2eur-x"),
    _crop("a2", "de-2011-2eur-y"),
    _crop("a3", "it-2012-2eur-z", class_id="it-2012-2eur-rep"),
]


@pytest.fixture
def gold_file(tmp_path: Path) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(json.dumps(asdict(r), sort_keys=True) for r in GOLD_ROWS) + "\n",
        encoding="utf-8",
    )
    path.with_suffix(".meta.json").write_text(
        json.dumps({"gold_version": "deadbeef1234", "n_crops": len(GOLD_ROWS)}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Une base SANS les tables de traçabilité : le pire cas mesurable.

    ``calibration_blockers`` doit y voir deux bloqueurs (P3 non mesurable, P1
    non mesurable) — c'est l'état d'une machine sur laquelle personne n'a
    encore bâti la banque.
    """
    db = tmp_path / "vide.db"
    sqlite3.connect(db).close()
    return db


def _fake_result(model: str, **over) -> dict:
    preds = [
        bench.EncoderBenchPrediction(
            asset_id="a1", truth_class_id="fr-2010-2eur-x", correct=1, in_top5=1,
            top1_eurio_id="fr-2010-2eur-x", top1_sim=0.9, top2_sim=0.5, spread=0.40,
            country_top1_eurio_id="fr-2010-2eur-x", country_correct=1,
        ),
        bench.EncoderBenchPrediction(
            asset_id="a2", truth_class_id="de-2011-2eur-y", correct=0, in_top5=1,
            top1_eurio_id="fr-2010-2eur-x", top1_sim=0.6, top2_sim=0.59, spread=0.01,
            country_top1_eurio_id="de-2011-2eur-y", country_correct=1,
        ),
    ]
    base = {
        "model": model,
        "encoder_version": bench.encoder_version_of(model),
        "anchors": 12,
        "n_bank_classes": 9,
        "dim": 384,
        "params_m": 21.6,
        "input_px": 224,
        "device": "cpu",
        "preds": preds,
        "t_load": 0.1,
        "t_encode": 0.2,
        "ms_per_img": 12.0,
        "n_in_scope": 2,
        "n_out_of_scope": 1,
        "n_not_encoded": 0,
        "g1": 1, "g5": 2,
        "c_total": 2, "c1": 2, "c5": 2,
    }
    base.update(over)
    return base


@pytest.fixture
def wired(monkeypatch, gold_file):
    """Le banc, ses I/O lourdes doublées. Rend le journal des pushes."""
    monkeypatch.setattr(
        bench, "load_anchors",
        lambda kind: AnchorBank(
            eurio_ids=["fr-2010-2eur-x"],
            matrix=np.zeros((1, 4), dtype=np.float32),
            encoder_version="dinov2-vitl14",
            anchors_kind=kind,
            built_at="2026-08-19T00:28:21+00:00",
            source_paths=["/tmp/anchor-1.jpg"],
        ),
    )
    monkeypatch.setattr(
        bench, "resolve_local_paths",
        lambda rows: ([(r, Path(f"/tmp/{r.asset_id}.jpg")) for r in rows], []),
    )
    monkeypatch.setattr(
        bench, "_bench_model",
        lambda spec, eids, apaths, crops: _fake_result(spec),
    )
    pushed: list[dict] = []

    def _fake_push(run, predictions):
        pushed.append({"run": run, "predictions": predictions})
        return {"run_id": run["run_id"], "n_predictions": len(predictions)}

    monkeypatch.setattr("client.ingest.push_encoder_bench", _fake_push)
    return pushed


# ─── D5 : le jeu d'évaluation est le gold figé, et lui seul ──────────────────


def test_le_banc_ne_rejoue_plus_sa_propre_selection():
    """La repro du FINDINGS §8, retournée : le module doit citer le gold.

    Avant correctif, ``grep -n 'encoder_bench\\|bench_gold\\|calibration\\|
    provisional' ml/scripts/bench_encoder_dino.py`` ne rendait RIEN, et
    ``_load_labeled`` portait un ``SELECT … FROM review_queue`` concurrent de
    ``review.bench_gold.SELECTION_SQL``.
    """
    src = Path(bench.__file__).read_text(encoding="utf-8")
    assert "_load_labeled" not in src
    assert "review_queue" not in src, "le banc a de nouveau sa propre sélection"
    for attendu in ("bench_gold", "encoder_bench", "calibration", "provisional"):
        assert attendu in src, f"{attendu} absent du chemin exécutable"


def test_le_banc_lit_le_gold_et_trace_sa_version(wired, gold_file, empty_db, capsys):
    assert bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--no-push",
    ]) == 0
    out = capsys.readouterr()
    assert "deadbeef1234" in out.out
    assert "3 crops figés" in out.err


def test_le_run_pousse_porte_le_gold_et_ses_predictions(wired, gold_file, empty_db):
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14",
    ])
    assert len(wired) == 1
    run = wired[0]["run"]
    assert run["gold_version"] == "deadbeef1234"
    assert run["gold_n_crops"] == 3
    assert run["anchors_kind"] == "2eur_all"
    assert run["encoder_spec"] == "dinov2_vitl14"
    assert run["encoder_version"] == "dinov2-vitl14"
    assert run["n_in_scope"] == 2
    assert [p["asset_id"] for p in wired[0]["predictions"]] == ["a1", "a2"]


def test_encoder_version_traduit_la_spec_torch_hub():
    """``dinov2_vitl14`` (spec CLI) est stocké ``dinov2-vitl14``.

    Mesurer les bloqueurs sous la spec brute rendrait « aucun build tracé »
    pour l'encodeur servi lui-même — un faux bloqueur qui masque les vrais.
    """
    assert bench.encoder_version_of("dinov2_vitl14") == "dinov2-vitl14"
    assert bench.encoder_version_of("dinov2_vits14") == "dinov2-vits14"
    assert (
        bench.encoder_version_of("timm:vit_small_patch16_dinov3.lvd1689m")
        == "timm:vit_small_patch16_dinov3.lvd1689m"
    )


def test_echantillon_deterministe_et_trie():
    rows = [(_crop(f"a{i}", "fr-x"), Path(f"/tmp/a{i}.jpg")) for i in range(20)]
    a = bench.select_sample(rows, 5)
    b = bench.select_sample(list(reversed(rows)), 5)
    assert [c.asset_id for c, _ in a] == [c.asset_id for c, _ in b]
    assert [c.asset_id for c, _ in a] == sorted(c.asset_id for c, _ in a)
    assert bench.select_sample(rows, None) == sorted(rows, key=lambda t: t[0].asset_id)


def test_un_run_sur_echantillon_se_declare(wired, gold_file, empty_db):
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--limit", "2",
    ])
    run = wired[0]["run"]
    assert run["gold_sample_n"] == 2
    assert run["gold_n_crops"] == 3
    assert "echantillon" in run["provisional_reason"]


# ─── D4 : le blocage est visible, et le seuil ne sort pas ────────────────────


def test_la_banniere_est_en_tete_ET_en_pied(wired, gold_file, empty_db, capsys):
    """Avant correctif : aucune bannière nulle part, l'avertissement vivait
    dans le ``desc:`` de la tâche go-task, que go-task n'imprime pas."""
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--no-push",
    ])
    err = capsys.readouterr().err.strip().splitlines()
    titre = "⚠ CALIBRATION PROVISOIRE — NE PAS RECOPIER CES SEUILS DANS dino_thresholds"
    assert err.count(titre) == 2, "la bannière doit encadrer la sortie"
    # …et elle est dans le premier ET le dernier bloc, pas deux fois au même
    # endroit : la première occurrence ouvre la sortie, la dernière la ferme.
    premiere = err.index(titre)
    derniere = len(err) - 1 - err[::-1].index(titre)
    assert premiere < 5, err[:5]
    assert derniere > len(err) - len(bench.blocker_banner({"m": ["x"]})) - 1
    assert err[-1] == "=" * 78


def test_la_banniere_survit_a_la_redirection_du_rapport(
    wired, gold_file, empty_db, tmp_path
):
    """Le rapport Markdown la porte aussi : `--out` ne doit pas la perdre."""
    out = tmp_path / "bench.md"
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--no-push", "--out", str(out),
    ])
    assert "⚠ CALIBRATION PROVISOIRE" in out.read_text(encoding="utf-8")


def test_les_bloqueurs_mesures_sont_ceux_du_store(wired, gold_file, empty_db, capsys):
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--no-push",
    ])
    err = capsys.readouterr().err
    assert "P3: fraicheur non mesurable" in err
    assert "P1: couverture de la banque non mesurable" in err


def test_le_seuil_ne_sort_pas_tant_qu_un_bloqueur_tient(
    wired, gold_file, empty_db, capsys
):
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--no-push",
    ])
    report = capsys.readouterr().out
    assert "aucun seuil rendu" in report
    assert "Seuil non promouvable" in report


def test_allow_provisional_rend_le_chiffre_mais_le_marque(
    wired, gold_file, empty_db, capsys
):
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--no-push", "--allow-provisional",
    ])
    report = capsys.readouterr().out
    assert "aucun seuil rendu" not in report
    assert "(provisoire)" in report


def test_le_run_est_marque_provisional_meme_avec_allow(wired, gold_file, empty_db):
    """``--allow-provisional`` décide de ce que l'opérateur VOIT, jamais de ce
    qui est promouvable. La colonne suit les bloqueurs mesurés."""
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "--allow-provisional",
    ])
    run = wired[0]["run"]
    assert run["provisional"] == 1
    assert "P3" in run["provisional_reason"] and "P1" in run["provisional_reason"]


def test_sans_bloqueur_la_banniere_dit_promouvable(monkeypatch, wired, gold_file,
                                                   empty_db, capsys):
    monkeypatch.setattr(bench, "calibration_blockers", lambda *a, **k: [])
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14",
    ])
    assert "✔ CALIBRATION PROMOUVABLE" in capsys.readouterr().err
    assert wired[0]["run"]["provisional"] == 0


def test_p3_ne_bloque_pas_la_comparaison_des_encodeurs(
    wired, gold_file, empty_db, capsys
):
    """Le fait établi qui gouverne ce câblage : le banc ré-encode tout, il ne
    lit aucune prédiction stockée. Les recall restent donc mesurés et publiés
    malgré P3 — seul le seuil est bloqué. Un banc qu'on ne peut pas lancer
    nuit autant qu'un banc qui ment."""
    code = bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "dinov2_vits14", "--no-push",
    ])
    report = capsys.readouterr().out
    assert code == 0
    assert "| dinov2_vitl14 |" in report and "| dinov2_vits14 |" in report
    assert "50.0%" in report  # 1 correct sur 2 in-scope
    assert "Apparié McNemar" in report


def test_mcnemar_apparie_le_candidat_a_la_reference(wired, gold_file, empty_db):
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "dinov2_vits14",
    ])
    runs = {p["run"]["encoder_spec"]: p["run"] for p in wired}
    assert runs["dinov2_vitl14"]["baseline_run_id"] is None
    cand = runs["dinov2_vits14"]
    assert cand["baseline_run_id"] == runs["dinov2_vitl14"]["run_id"]
    assert cand["mcnemar_p"] == 1.0  # doublures identiques : aucun discordant
    assert cand["mcnemar_b"] == 0 and cand["mcnemar_c"] == 0


# ─── Le run ne se perd pas ───────────────────────────────────────────────────


def test_sync_desactivee_ne_perd_pas_le_run(monkeypatch, wired, gold_file,
                                            empty_db, tmp_path, capsys):
    """``push_encoder_bench`` rend ``None`` quand la sync est coupée. Deux
    heures de GPU ne doivent pas s'évaporer, et le code de sortie doit dire
    que le run n'est PAS tracé."""
    monkeypatch.setattr("client.ingest.push_encoder_bench", lambda run, preds: None)
    monkeypatch.setattr(bench, "PENDING_DIR", tmp_path / "pending")
    code = bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14",
    ])
    assert code == 1
    assert "sync désactivée" in capsys.readouterr().err
    dumps = list((tmp_path / "pending").glob("*.json"))
    assert len(dumps) == 1
    payload = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert payload["run"]["gold_version"] == "deadbeef1234"
    assert len(payload["predictions"]) == 2


def test_post_en_erreur_ne_perd_pas_le_run(monkeypatch, wired, gold_file,
                                           empty_db, tmp_path, capsys):
    def _boom(run, preds):
        raise RuntimeError("401 token expiré")

    monkeypatch.setattr("client.ingest.push_encoder_bench", _boom)
    monkeypatch.setattr(bench, "PENDING_DIR", tmp_path / "pending")
    assert bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14",
    ]) == 1
    err = capsys.readouterr().err
    assert "401 token expiré" in err
    assert len(list((tmp_path / "pending").glob("*.json"))) == 1


# ─── La vérité comparée est celle que la banque peut rendre ──────────────────


def test_score_crops_compare_au_class_id_pas_au_truth_eurio_id():
    """Une pièce représentée par un frère de ``design_group`` est indexée sous
    le représentant. Comparer au ``truth_eurio_id`` la compterait fausse à
    tous les coups — et ferait chuter le recall d'un encodeur sans qu'aucune
    erreur ne se voie."""
    bank = AnchorBank(
        eurio_ids=["it-2012-2eur-rep", "fr-2010-2eur-x"],
        matrix=np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        encoder_version="test", anchors_kind="2eur_all", built_at="test",
    )
    crop = _crop("a3", "it-2012-2eur-z", class_id="it-2012-2eur-rep")
    crops = [(crop, Path("/tmp/a3.jpg"))]
    matrix = np.array([[1.0, 0.0]], dtype=np.float32)
    preds, agg = bench.score_crops(bank, crops, {"/tmp/a3.jpg": 0}, matrix)
    assert agg["n_in_scope"] == 1
    assert agg["g1"] == 1
    assert preds[0].truth_class_id == "it-2012-2eur-rep"
    assert preds[0].top1_eurio_id == "it-2012-2eur-rep"
    assert preds[0].spread == pytest.approx(1.0)


def test_score_crops_compte_les_hors_perimetre_sans_les_noter():
    bank = AnchorBank(
        eurio_ids=["fr-2010-2eur-x"],
        matrix=np.array([[1.0, 0.0]], dtype=np.float32),
        encoder_version="test", anchors_kind="2eur_all", built_at="test",
    )
    crops = [(_crop("a2", "de-2011-2eur-y"), Path("/tmp/a2.jpg"))]
    preds, agg = bench.score_crops(
        bank, crops, {"/tmp/a2.jpg": 0}, np.array([[1.0, 0.0]], dtype=np.float32)
    )
    assert preds == []
    assert agg == {
        "n_in_scope": 0, "n_out_of_scope": 1, "n_not_encoded": 0,
        "g1": 0, "g5": 0, "c_total": 0, "c1": 0, "c5": 0,
    }


def test_la_bande_pays_vient_de_la_verite_tranchee():
    """``truth_country`` du gold, pas la cible du listing (D6). Un crop
    tranché ``de-…`` doit être cherché parmi les ancres allemandes."""
    bank = AnchorBank(
        eurio_ids=["de-2011-2eur-y", "fr-2010-2eur-x"],
        matrix=np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32),
        encoder_version="test", anchors_kind="2eur_all", built_at="test",
    )
    crop = _crop("a2", "de-2011-2eur-y")
    assert crop.truth_country == "de"
    preds, agg = bench.score_crops(
        bank, [(crop, Path("/tmp/a2.jpg"))], {"/tmp/a2.jpg": 0},
        np.array([[1.0, 0.0]], dtype=np.float32),
    )
    # top-1 global : la française (mauvaise) ; bande pays : l'allemande (bonne).
    assert preds[0].top1_eurio_id == "fr-2010-2eur-x"
    assert agg["g1"] == 0
    assert preds[0].country_top1_eurio_id == "de-2011-2eur-y"
    assert agg["c1"] == 1


# ─── N1 : les crops non encodés ne disparaissent pas ─────────────────────────


def test_les_crops_non_encodes_sont_comptes_imprimes_et_bloquent(
    monkeypatch, wired, gold_file, empty_db, capsys
):
    """Le jumeau du chemin « absent du cache », qui lui était déjà compté.

    Un crop présent sur disque mais rejeté par ``encode_paths`` (JPEG tronqué,
    EXIF cassé, OOM) sortait de ``score_crops`` dans ``n_not_encoded`` et
    n'était lu par PERSONNE : ni stdout, ni stderr, ni le rapport, ni
    ``gold_sample_n``. Le run se déclarait « gold entier » sur un sous-ensemble.
    """
    monkeypatch.setattr(
        bench, "_bench_model",
        lambda spec, eids, apaths, crops: _fake_result(spec, n_not_encoded=1),
    )
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14",
    ])
    cap = capsys.readouterr()
    run = wired[0]["run"]
    assert run["gold_sample_n"] == 2, (
        "3 crops soumis dont 1 non encodé → le run porte sur 2, pas sur le gold entier"
    )
    assert "echantillon" in (run["provisional_reason"] or "")
    # L'opérateur le voit passer…
    assert "NON ENCODÉS" in cap.err
    # …et le `.md` archivé le porte aussi : stderr n'est pas capturé par --out.
    assert "présents en cache et illisibles" in cap.out
    assert "`dinov2_vitl14` : 1 crops" in cap.out


def test_le_gold_entier_reste_le_gold_entier_sans_perte(wired, gold_file, empty_db):
    """Le garde ne doit pas transformer tout run en échantillon : sans perte,
    ``gold_sample_n`` reste ``None`` et aucun bloqueur « echantillon »."""
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14",
    ])
    run = wired[0]["run"]
    assert run["gold_sample_n"] is None
    assert "echantillon" not in (run["provisional_reason"] or "")


# ─── N2 : un encodeur tombé n'est pas un succès ──────────────────────────────


def test_un_encodeur_tombe_sort_en_erreur_et_le_rapport_le_dit(
    monkeypatch, wired, gold_file, empty_db, capsys
):
    """Avant correctif : ``RC=0``, une seule ligne de table, une seule ligne de
    traçabilité, et la bannière citait quand même l'encodeur tombé — le ``.md``
    archivé donnait à croire que les deux avaient été évalués."""
    def _bench(spec, eids, apaths, crops):
        if spec == "dinov2_vits14":
            raise RuntimeError("CUDA out of memory")
        return _fake_result(spec)

    monkeypatch.setattr(bench, "_bench_model", _bench)
    code = bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vits14", "dinov2_vitl14", "--no-push",
    ])
    cap = capsys.readouterr()
    assert code == 1, "un encodeur tombé doit faire sortir le banc en erreur"
    assert "CUDA out of memory" in cap.out, "l'échec doit vivre dans le RAPPORT"
    assert "dinov2_vits14" in cap.out
    assert "| dinov2_vits14 |" not in cap.out, "le tombé n'a pas de ligne de résultat"
    assert "| dinov2_vitl14 |" in cap.out


def test_la_banniere_finale_ne_credite_pas_l_encodeur_tombe(
    monkeypatch, wired, gold_file, empty_db, capsys
):
    """La bannière de pied est recalculée APRÈS le bench : elle ne peut plus
    nommer comme évalué un encodeur qui n'a pas tourné, et elle dit sa chute."""
    def _bench(spec, eids, apaths, crops):
        if spec == "dinov2_vits14":
            raise RuntimeError("CUDA out of memory")
        return _fake_result(spec)

    monkeypatch.setattr(bench, "_bench_model", _bench)
    monkeypatch.setattr(bench, "calibration_blockers", lambda *a, **k: [])
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vits14", "dinov2_vitl14", "--no-push",
    ])
    err = capsys.readouterr().err.strip().splitlines()
    pied = err[-len(bench.blocker_banner({}, failures=[("x", "y")])):]
    joint = "\n".join(pied)
    assert "dinov2_vits14" in joint, "le pied doit nommer l'encodeur tombé"
    assert "CUDA out of memory" in joint
    assert "✔ CALIBRATION PROMOUVABLE" not in joint, (
        "un banc amputé ne se déclare pas promouvable"
    )



# ─── N6 : le repli de base, quand EURIO_DB_PATH est absent ───────────────────


def test_le_repli_de_base_est_la_replique_pas_la_base_de_travail(monkeypatch):
    """Hors devShell, ``EURIO_DB_PATH`` est absent. Le repli doit être la
    RÉPLIQUE (12454 assets), pas ``state/eurio.db`` (6205, périmée) — même
    convention que ``build_scan_prescription`` (D12)."""
    monkeypatch.delenv("EURIO_DB_PATH", raising=False)
    assert bench.default_db().name == "eurio.replica.db"
    monkeypatch.setenv("EURIO_DB_PATH", "/tmp/ailleurs.db")
    assert bench.default_db() == Path("/tmp/ailleurs.db")


# ─── D16 : le garde apparié, ARMÉ sur le chemin réel ─────────────────────────


def _resultat_partiel(model: str) -> dict:
    """Un candidat qui n'a noté qu'un crop sur les deux du baseline."""
    r = _fake_result(model)
    r["preds"] = r["preds"][:1]
    return r


def test_le_recouvrement_apparie_est_trace_dans_le_run(
    monkeypatch, wired, gold_file, empty_db
):
    """``n_paired`` doit remonter jusqu'à la ligne poussée.

    Le garde ``_paired_blockers`` du store était testé, mais AUCUN appelant ne
    lui passait ``baseline_run_id`` / ``n_paired`` : il ne se déclenchait jamais
    en production. Un garde jamais armé est un garde absent.
    """
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "dinov2_vits14",
        "--baseline", "dinov2_vitl14",
    ])
    runs = {j["run"]["encoder_spec"]: j["run"] for j in wired}
    # Le baseline n'a pas de baseline : pas de recouvrement, NULL légitime.
    assert runs["dinov2_vitl14"]["baseline_run_id"] is None
    assert runs["dinov2_vitl14"]["n_paired"] is None
    # Le candidat, lui, dit sur combien de paires son McNemar porte.
    assert runs["dinov2_vits14"]["baseline_run_id"] is not None
    assert runs["dinov2_vits14"]["n_paired"] == 2


def test_un_recouvrement_partiel_bloque_le_candidat(
    monkeypatch, wired, gold_file, empty_db
):
    """2 crops côté baseline, 1 seul côté candidat → le McNemar ne porte que
    sur 1 paire, et rien dans b/c ne le dirait. Le bloqueur doit le dire."""
    def _bench(spec, eids, apaths, crops):
        return _fake_result(spec) if spec == "dinov2_vitl14" else _resultat_partiel(spec)

    monkeypatch.setattr(bench, "_bench_model", _bench)
    bench.main([
        "--db", str(empty_db), "--gold", str(gold_file),
        "--models", "dinov2_vitl14", "dinov2_vits14",
        "--baseline", "dinov2_vitl14",
    ])
    runs = {j["run"]["encoder_spec"]: j["run"] for j in wired}
    candidat = runs["dinov2_vits14"]
    assert candidat["n_paired"] == 1
    assert "apparie:" in (candidat["provisional_reason"] or ""), candidat
    assert candidat["provisional"] == 1
    # Le baseline, lui, n'est pas accusé d'un recouvrement qu'il ne déclare pas.
    assert "apparie:" not in (runs["dinov2_vitl14"]["provisional_reason"] or "")
