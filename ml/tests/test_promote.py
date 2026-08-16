"""Smoke tests for promote_iteration — atomic copy, archive, hashing, lock.

Pas de Supabase ici (mockable via subprocess monkeypatch). On vérifie le
filesystem behavior (atomicité, idempotence du backup, lock fichier).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts import promote_iteration as p


def _build_iter_dir(root: Path, iid: str, classes: list[str]) -> Path:
    iter_dir = root / iid
    for sub in p.ARTIFACT_SUBDIRS:
        (iter_dir / sub).mkdir(parents=True)
    (iter_dir / "checkpoints" / "best_model.pth").write_bytes(b"\x00" * 1024)
    (iter_dir / "checkpoints" / "training_log.json").write_text("[]")
    (iter_dir / "embeddings" / "embeddings_v1.json").write_text(
        json.dumps({
            "version": "1.0",
            "model": "v1-arcface",
            "embedding_dim": 256,
            "coins": {c: {"name": c, "embedding": [0.1] * 256} for c in classes},
        })
    )
    (iter_dir / "tflite" / "eurio_embedder_v1.tflite").write_bytes(b"\xff" * 2048)
    (iter_dir / "tflite" / "model_meta.json").write_text("{}")
    return iter_dir


@pytest.fixture
def isolated_prod(tmp_path, monkeypatch):
    """Redirect promote_iteration's PROD_* paths into a tmp dir."""
    prod = tmp_path / "prod"
    monkeypatch.setattr(p, "PROD_DIR", prod)
    monkeypatch.setattr(p, "PROD_CURRENT", prod / "current")
    monkeypatch.setattr(p, "PROD_ARCHIVE", prod / "archive")
    monkeypatch.setattr(p, "PROD_LOCK", prod / ".promote.lock")
    monkeypatch.setattr(p, "LAB_ITERATIONS_DIR", tmp_path / "lab" / "iterations")
    yield prod


def test_atomic_copy_into_empty_prod(isolated_prod, tmp_path):
    iter_dir = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-001", ["a", "b"])
    p._atomic_copy(iter_dir, p.PROD_CURRENT)
    for sub in p.ARTIFACT_SUBDIRS:
        assert (p.PROD_CURRENT / sub).is_dir()
    assert (p.PROD_CURRENT / "embeddings" / "embeddings_v1.json").exists()
    # No staging dir leftover.
    assert not list(p.PROD_CURRENT.parent.glob("current.new-*"))


def test_archive_then_atomic_copy(isolated_prod):
    iter_a = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-A", ["a"])
    p._atomic_copy(iter_a, p.PROD_CURRENT)
    p._write_promoted_from(
        {"id": "iid-A", "name": "A", "cohort_id": "c", "verdict": "baseline",
         "training_run_id": None, "benchmark_run_id": None},
        {},
    )

    iter_b = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-B", ["a", "b"])
    archived = p._archive_current(p._read_prev_iid())
    assert archived is not None
    assert archived.name.startswith("iid-A-")
    assert (archived / "embeddings" / "embeddings_v1.json").exists()

    p._atomic_copy(iter_b, p.PROD_CURRENT)
    classes = json.loads(
        (p.PROD_CURRENT / "embeddings" / "embeddings_v1.json").read_text()
    )["coins"]
    assert set(classes) == {"a", "b"}


def test_lock_blocks_concurrent_promotion(isolated_prod):
    p.PROD_DIR.mkdir(parents=True, exist_ok=True)
    p.PROD_LOCK.write_text(str(os.getpid()))
    with pytest.raises(SystemExit, match="Promotion already in flight"):
        with p._promote_lock():
            pass


def test_lock_released_after_success(isolated_prod):
    with p._promote_lock():
        assert p.PROD_LOCK.exists()
    assert not p.PROD_LOCK.exists()


def test_lock_released_on_exception(isolated_prod):
    with pytest.raises(RuntimeError):
        with p._promote_lock():
            raise RuntimeError("boom")
    assert not p.PROD_LOCK.exists()


def test_diff_classes(isolated_prod):
    iter_dir = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-1", ["a", "b", "c"])
    # Seed prev prod with {a, b, x}
    (p.PROD_CURRENT / "embeddings").mkdir(parents=True)
    (p.PROD_CURRENT / "embeddings" / "embeddings_v1.json").write_text(
        json.dumps({"coins": {"a": {}, "b": {}, "x": {}}})
    )
    diff = p._diff_classes(iter_dir)
    assert diff["added"] == ["c"]
    assert diff["kept"] == ["a", "b"]
    assert diff["absent_in_promotion"] == ["x"]
    assert diff["n_new"] == 3
    assert diff["n_current"] == 3


def test_hash_tree_stable(isolated_prod):
    iter_dir = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-h", ["a"])
    h1 = p._hash_tree(iter_dir / "embeddings")
    h2 = p._hash_tree(iter_dir / "embeddings")
    assert h1 == h2
    # Touching the file changes the hash.
    (iter_dir / "embeddings" / "embeddings_v1.json").write_text("{}")
    h3 = p._hash_tree(iter_dir / "embeddings")
    assert h3 != h1


# ─── Garde de traçabilité (exercice #1 du parcours 4, 2026-08-16) ────────────
#
# La promotion résout sa base par EURIO_DB_PATH, que le devShell pointe sur la
# RÉPLIQUE du canonique. Or le canonique null les `*_run_id` (les tables de run
# ne lui sont jamais poussées) : l'itération y est `completed` avec `run=NULL`
# pendant que la base de calcul porte le vrai lien. Sans garde, la promotion
# réussit et écrit un `promoted_from.json` sans `training_run_id` — plus rien ne
# relie le modèle en prod à ce qui l'a produit.


def _store_with_iteration(tmp_path, iid, *, training_run_id):
    from store import ExperimentCohortRow, ExperimentIterationRow, Store

    store = Store(tmp_path / f"{iid}.db")
    if training_run_id is not None:
        # FK `training_run_id` → la ligne de run doit exister dans CETTE base.
        # C'est précisément la différence entre la base de calcul et la réplique.
        store._connection().execute(  # noqa: SLF001
            "INSERT INTO training_runs (id, version, status, config_json, "
            "classes_before_json, classes_after_json, classes_added_json, "
            "classes_removed_json) VALUES (?, 1, 'completed', '{}', '[]', '[]', "
            "'[]', '[]')",
            (training_run_id,),
        )
    store.upsert_cohort(ExperimentCohortRow(id="co", name="co", eurio_ids=["a"]))
    store.upsert_iteration(
        ExperimentIterationRow(
            id=iid, cohort_id="co", name=iid, status="completed",
            verdict="baseline", training_run_id=training_run_id,
        )
    )
    return store


def test_promotion_refuses_a_db_without_the_run(isolated_prod, tmp_path, monkeypatch):
    """Réplique : `completed` mais `training_run_id` NULL → refus explicite."""
    _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-repl", ["a"])
    store = _store_with_iteration(tmp_path, "iid-repl", training_run_id=None)
    monkeypatch.setattr(p, "STATE_DB", store.db_path)

    with pytest.raises(SystemExit) as exc:
        p._validate_iteration("iid-repl", force=False)
    msg = str(exc.value)
    assert "training_run_id" in msg
    assert "EURIO_DB_PATH" in msg          # la sortie nomme le geste réparateur

    # --force reste possible, en connaissance de cause.
    meta = p._validate_iteration("iid-repl", force=True)
    assert meta["training_run_id"] is None


def test_promotion_accepts_the_compute_db(isolated_prod, tmp_path, monkeypatch):
    """Base de calcul : le lien vers le run est là → la promotion passe."""
    _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-work", ["a"])
    store = _store_with_iteration(tmp_path, "iid-work", training_run_id="run-42")
    monkeypatch.setattr(p, "STATE_DB", store.db_path)

    meta = p._validate_iteration("iid-work", force=False)
    assert meta["training_run_id"] == "run-42"
