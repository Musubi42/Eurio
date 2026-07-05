"""Tests Lot 4 — replay_corpus (corpus-spec §7/§8/§8bis).

McNemar exact, croisement apparié, scorecard, chargement candidat, et replay
fast-path complet avec un embedder stub (pas de modèle lourd en CI).
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts.replay_corpus import (
    Candidate,
    FramePrediction,
    build_scorecard,
    crossed_stats,
    load_candidate,
    mcnemar_exact,
    replay_candidate,
)
from store.scan_corpus import ScanCapture, ScanCorpusStore


# ─── McNemar §8bis ──────────────────────────────────────────────────────────


def test_mcnemar_no_discordant_is_1() -> None:
    assert mcnemar_exact(0, 0) == 1.0


def test_mcnemar_symmetric() -> None:
    assert mcnemar_exact(3, 9) == mcnemar_exact(9, 3)


def test_mcnemar_exact_value() -> None:
    # n=8 discordantes, k=1 : 2 * (C(8,0)+C(8,1))/2^8 = 18/256.
    assert mcnemar_exact(1, 7) == pytest.approx(18 / 256)


def test_mcnemar_one_pair_not_significant() -> None:
    # Le cas §8bis : +2 pts sur 48 ≈ 1 paire discordante → jamais significatif.
    assert mcnemar_exact(0, 1) == 1.0


# ─── Croisement apparié ─────────────────────────────────────────────────────


def _pred(cid: str, correct: bool, abstained: bool = False, cond: str = "bright") -> FramePrediction:
    return FramePrediction(
        capture_id=cid,
        eurio_id="gt",
        condition=cond,
        top5=[("pred", 0.9), ("other", 0.4)],
        abstained=abstained,
        correct_strict_top1=correct,
        correct_eq_top1=correct,
        correct_eq_top5=correct,
    )


def test_crossed_stats_contingency_and_flips() -> None:
    base = [_pred("a", True), _pred("b", True), _pred("c", False), _pred("d", False)]
    cand = [_pred("a", True), _pred("b", False), _pred("c", True), _pred("d", False)]
    stats = crossed_stats(base, cand)
    assert stats["n_paired"] == 4
    assert stats["contingency"] == {
        "both_correct": 1,
        "baseline_only": 1,
        "candidate_only": 1,
        "both_incorrect": 1,
    }
    assert stats["n_discordant"] == 2
    assert [f["capture_id"] for f in stats["confusions"]["gained"]] == ["c"]
    assert [f["capture_id"] for f in stats["confusions"]["lost"]] == ["b"]


def test_crossed_stats_abstention_counts_as_incorrect() -> None:
    base = [_pred("a", True)]
    cand = [_pred("a", True, abstained=True)]
    stats = crossed_stats(base, cand)
    assert stats["contingency"]["baseline_only"] == 1


# ─── Scorecard §8 ───────────────────────────────────────────────────────────


def test_build_scorecard_shape(tmp_path: Path) -> None:
    model = tmp_path / "m.tflite"
    model.write_bytes(b"\0" * (1024 * 1024))
    cand = Candidate(label="x", centroids_path=tmp_path / "e.json", model_path=model)
    preds = [
        _pred("a", True, cond="bright"),
        _pred("b", False, cond="dim"),
        _pred("c", True, abstained=True, cond="dim"),
    ]
    sc = build_scorecard(cand, preds, "base", {"cohort_id": None}, "deadbeef0123")
    assert sc["n_frames"] == 3
    assert sc["primary"]["r_at_1_eq"] == pytest.approx(2 / 3, abs=1e-4)
    assert sc["by_condition"]["dim"]["n"] == 2
    # Abstention : 2 réponses sur 3, toutes les répondues top-1 correct = 1/2.
    assert sc["abstention"]["coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert sc["abstention"]["precision_at_coverage"] == pytest.approx(0.5)
    assert sc["size"]["model_mb"] == 1.0
    assert sc["corpus_version"] == "deadbeef0123"


# ─── Candidat ───────────────────────────────────────────────────────────────


def test_load_candidate_with_thresholds(tmp_path: Path) -> None:
    d = tmp_path / "cand"
    (d / "sub").mkdir(parents=True)
    (d / "embeddings_v1.json").write_text("{}")
    (d / "sub" / "model.tflite").write_bytes(b"x")
    (d / "thresholds.json").write_text('{"top1_min": 0.4, "margin_min": 0.05}')
    c = load_candidate(d)
    assert c.label == "cand"
    assert c.model_path.name == "model.tflite"
    assert (c.top1_min, c.margin_min) == (0.4, 0.05)
    assert c.has_thresholds


def test_load_candidate_missing_model(tmp_path: Path) -> None:
    d = tmp_path / "cand"
    d.mkdir()
    (d / "embeddings_v1.json").write_text("{}")
    with pytest.raises(SystemExit):
        load_candidate(d)


# ─── Replay fast-path (embedder stub) ───────────────────────────────────────


class _StubEmbedder:
    """Embed déterministe : la couleur dominante du crop → un axe one-hot."""

    def embed(self, image: Image.Image) -> np.ndarray:
        r, g, b = np.asarray(image.resize((1, 1))).reshape(3)[:3]
        vec = np.array([float(r), float(g), float(b)], dtype=np.float32)
        return vec / (np.linalg.norm(vec) or 1.0)


@pytest.fixture()
def corpus(tmp_path: Path) -> ScanCorpusStore:
    store = ScanCorpusStore(db_path=tmp_path / "scan_corpus.db")
    store.frames_dir.mkdir(parents=True)
    # coin-red est rouge, coin-green est vert ; la 3e capture (bleue,
    # étiquetée coin-red) sera mal classée.
    for cid, color, gt, cond in (
        ("aa00000000000001", (255, 0, 0), "coin-red", "bright"),
        ("aa00000000000002", (0, 255, 0), "coin-green", "dim"),
        ("aa00000000000003", (0, 0, 255), "coin-red", "tilt"),
    ):
        Image.new("RGB", (224, 224), color).save(store.frames_dir / f"{cid}.crop.png")
        store.upsert_capture(
            ScanCapture(
                capture_id=cid,
                eurio_id=gt,
                condition=cond,
                captured_at="2026-07-04T00:00:00Z",
                raw_path=f"frames/{cid}.raw.jpg",
                crop_path=f"frames/{cid}.crop.png",
                cohort_id="c1",
            )
        )
    return store


def _stub_centroids_json(path: Path) -> None:
    coins = {
        "coin-red": [1.0, 0.0, 0.0],
        "coin-green": [0.0, 1.0, 0.0],
        "coin-blue": [0.0, 0.0, 1.0],
    }
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


def test_replay_fast_path_end_to_end(
    corpus: ScanCorpusStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import training.eval.evaluate_real_photos as erp

    monkeypatch.setattr(erp, "load_embedder", lambda p: _StubEmbedder())
    cand_dir = tmp_path / "cand"
    cand_dir.mkdir()
    _stub_centroids_json(cand_dir / "embeddings_v1.json")
    (cand_dir / "model.tflite").write_bytes(b"stub")

    candidate = load_candidate(cand_dir)
    captures = corpus.list_captures()
    preds = replay_candidate(candidate, captures, corpus.frames_root, equivalence=None)

    by_id = {p.capture_id: p for p in preds}
    assert by_id["aa00000000000001"].correct_eq_top1 is True
    assert by_id["aa00000000000002"].correct_eq_top1 is True
    # Capture bleue étiquetée coin-red → top-1 = coin-blue → incorrect.
    assert by_id["aa00000000000003"].correct_eq_top1 is False
    assert by_id["aa00000000000003"].top5[0][0] == "coin-blue"
    # top-5 contient coin-red → correct en R@5.
    assert by_id["aa00000000000003"].correct_eq_top5 is True
    assert all(not p.abstained for p in preds)  # pas de thresholds → répond toujours

    sc = build_scorecard(candidate, preds, None, {"cohort_id": "c1"}, "v")
    assert sc["primary"]["r_at_1_eq"] == pytest.approx(2 / 3, abs=1e-4)
    assert sc["primary"]["r_at_5_eq"] == 1.0


def test_replay_abstention_thresholds(
    corpus: ScanCorpusStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import training.eval.evaluate_real_photos as erp

    monkeypatch.setattr(erp, "load_embedder", lambda p: _StubEmbedder())
    cand_dir = tmp_path / "cand"
    cand_dir.mkdir()
    _stub_centroids_json(cand_dir / "embeddings_v1.json")
    (cand_dir / "model.tflite").write_bytes(b"stub")
    # Sim top-1 ≈ 1.0 sur les crops purs → un top1_min impossible force l'abstention.
    (cand_dir / "thresholds.json").write_text('{"top1_min": 1.01}')

    candidate = load_candidate(cand_dir)
    preds = replay_candidate(
        candidate, corpus.list_captures(), corpus.frames_root, equivalence=None
    )
    assert all(p.abstained for p in preds)
    sc = build_scorecard(candidate, preds, None, {}, "v")
    assert sc["abstention"]["coverage"] == 0.0
    assert sc["primary"]["r_at_1_eq"] == pytest.approx(2 / 3, abs=1e-4)


def test_replay_missing_crop_is_error_pred(
    corpus: ScanCorpusStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import training.eval.evaluate_real_photos as erp

    monkeypatch.setattr(erp, "load_embedder", lambda p: _StubEmbedder())
    (corpus.frames_dir / "aa00000000000002.crop.png").unlink()
    cand_dir = tmp_path / "cand"
    cand_dir.mkdir()
    _stub_centroids_json(cand_dir / "embeddings_v1.json")
    (cand_dir / "model.tflite").write_bytes(b"stub")

    preds = replay_candidate(
        load_candidate(cand_dir), corpus.list_captures(), corpus.frames_root, None
    )
    errored = [p for p in preds if p.error]
    assert len(errored) == 1
    assert errored[0].capture_id == "aa00000000000002"
    assert errored[0].abstained is True
