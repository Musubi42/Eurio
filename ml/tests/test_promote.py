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


# ─── D1 : le diff de perte doit dire la vérité, ou se taire bruyamment ───────
#
# `_diff_classes` comparait l'itération à `prod/current/embeddings/…` et, en
# l'absence de ce fichier, prenait `set()` comme référence : `absent_in_promotion`
# valait TOUJOURS `[]`. Sur une machine sans `ml/prod/` (le Mac, 2026-08-17), le
# dry-run annonçait « rien de perdu » alors que la comparaison à l'asset
# réellement embarqué donnait 16 pièces perdues sur 23.


def _args(iid, **over):
    import argparse
    base = dict(
        iteration_id=iid, force=False, dry_run=True, replace_all=False,
        no_supabase=True, allow_blind_diff=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _set_numista_ids(iter_dir: Path, mapping: dict[str, list[int]]) -> None:
    path = iter_dir / "embeddings" / "embeddings_v1.json"
    emb = json.loads(path.read_text())
    for cls, nids in mapping.items():
        emb["coins"][cls]["numista_ids"] = nids
    path.write_text(json.dumps(emb))


def _write_apk_asset(path: Path, numista_ids: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({nid: {"embedding": [0.0]} for nid in numista_ids}))
    return path


def test_diff_falls_back_to_the_apk_asset_when_prod_is_absent(
    isolated_prod, tmp_path, monkeypatch
):
    """Sans `prod/current`, la référence honnête est l'asset embarqué dans l'APK."""
    iter_dir = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-nofprod", ["a", "b"])
    # L'itération porte les numista_ids 1 et 2 ; l'APK en porte 2 et 3.
    emb = json.loads((iter_dir / "embeddings" / "embeddings_v1.json").read_text())
    emb["coins"]["a"]["numista_ids"] = [1]
    emb["coins"]["b"]["numista_ids"] = [2]
    (iter_dir / "embeddings" / "embeddings_v1.json").write_text(json.dumps(emb))
    monkeypatch.setattr(
        p, "APK_EMBEDDINGS", _write_apk_asset(tmp_path / "apk.json", ["2", "3"])
    )

    diff = p._diff_classes(iter_dir)
    assert diff["reference"] == "apk_asset"
    assert diff["id_space"] == "numista_id"
    assert diff["absent_in_promotion"] == ["3"]   # la pièce que l'APK perdrait
    assert diff["n_current"] == 2
    assert diff["blind"] is False


def test_diff_is_marked_blind_and_promotion_refuses_without_any_reference(
    isolated_prod, tmp_path, monkeypatch
):
    """Ni prod/current ni asset APK : le diff ne doit RIEN affirmer, et la
    promotion (même --dry-run) doit refuser sans drapeau explicite."""
    _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-blind", ["a"])
    store = _store_with_iteration(tmp_path, "iid-blind", training_run_id="run-1")
    monkeypatch.setattr(p, "STATE_DB", store.db_path)
    monkeypatch.setattr(p, "APK_EMBEDDINGS", tmp_path / "does-not-exist.json")

    diff = p._diff_classes(p.LAB_ITERATIONS_DIR / "iid-blind")
    assert diff["blind"] is True
    assert diff["absent_in_promotion"] is None    # pas [] : on ne sait pas
    assert diff["n_current"] is None

    with pytest.raises(SystemExit) as exc:
        p.promote(_args("iid-blind"))
    assert "--allow-blind-diff" in str(exc.value)

    # Le drapeau explicite débloque, en connaissance de cause.
    assert p.promote(_args("iid-blind", allow_blind_diff=True)) == 0


def test_diff_still_prefers_prod_current_when_it_exists(isolated_prod, tmp_path,
                                                        monkeypatch):
    iter_dir = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-pref", ["a", "b", "c"])
    (p.PROD_CURRENT / "embeddings").mkdir(parents=True)
    (p.PROD_CURRENT / "embeddings" / "embeddings_v1.json").write_text(
        json.dumps({"coins": {"a": {}, "b": {}, "x": {}}})
    )
    monkeypatch.setattr(
        p, "APK_EMBEDDINGS", _write_apk_asset(tmp_path / "apk.json", ["999"])
    )
    diff = p._diff_classes(iter_dir)
    assert diff["reference"] == "prod_current"
    assert diff["id_space"] == "class_id"
    assert diff["absent_in_promotion"] == ["x"]


# ─── D2 : la cible Supabase se vérifie AVANT le point de non-retour ──────────
#
# `promote()` remplaçait `prod/current` PUIS poussait Supabase. Or
# `model_classes` / `coin_embeddings` n'existent pas dans le projet ciblé
# (to_regclass → null, vérifié le 2026-08-17) : la promotion réussissait
# localement puis plantait, laissant un état à moitié promu.


def test_supabase_target_is_checked_before_prod_current_is_touched(
    isolated_prod, tmp_path, monkeypatch
):
    iter_dir = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-sb", ["a"])
    _set_numista_ids(iter_dir, {"a": [1]})
    store = _store_with_iteration(tmp_path, "iid-sb", training_run_id="run-1")
    monkeypatch.setattr(p, "STATE_DB", store.db_path)
    monkeypatch.setattr(
        p, "APK_EMBEDDINGS", _write_apk_asset(tmp_path / "apk.json", ["1"])
    )

    def _boom() -> None:
        raise SystemExit("Supabase: tables manquantes")

    monkeypatch.setattr(p, "_check_supabase_target", _boom)

    with pytest.raises(SystemExit, match="tables manquantes"):
        p.promote(_args("iid-sb", dry_run=False, no_supabase=False))
    # Point de non-retour jamais franchi.
    assert not p.PROD_CURRENT.exists()
    assert not p.PROD_ARCHIVE.exists()
    assert not p.PROD_LOCK.exists()


def test_supabase_check_names_the_missing_tables(monkeypatch):
    class _Resp:
        def __init__(self, code): self.status_code = code; self.text = "PGRST205"

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, **k):
            return _Resp(404 if "coin_embeddings" in url else 200)

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(
        p, "_supabase_credentials", lambda: ("https://x.supabase.co", "key")
    )
    with pytest.raises(SystemExit) as exc:
        p._check_supabase_target()
    assert "coin_embeddings" in str(exc.value)
    assert "model_classes" not in str(exc.value)


# ─── D3 : la garde de traçabilité ment, et --force est muet ──────────────────


def test_traceability_message_cites_the_real_mechanism(isolated_prod, tmp_path,
                                                       monkeypatch):
    _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-msg", ["a"])
    store = _store_with_iteration(tmp_path, "iid-msg", training_run_id=None)
    monkeypatch.setattr(p, "STATE_DB", store.db_path)
    with pytest.raises(SystemExit) as exc:
        p._validate_iteration("iid-msg", force=False)
    msg = str(exc.value)
    # FAUX : la réplique porte 34 training_runs. Le canonique annule le lien au
    # cas par cas (iteration_sync_routes.py:126-129).
    assert "n'a jamais reçu les tables de run" not in msg
    assert "iteration_sync_routes" in msg


def test_force_shouts_when_it_disarms_traceability(isolated_prod, tmp_path,
                                                   monkeypatch, capsys):
    _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-force", ["a"])
    store = _store_with_iteration(tmp_path, "iid-force", training_run_id=None)
    monkeypatch.setattr(p, "STATE_DB", store.db_path)

    meta = p._validate_iteration("iid-force", force=True)
    err = capsys.readouterr().err
    assert "traçabilité" in err.lower()
    assert "training_run_id" in err
    assert meta["force_overrides"] == ["traceability"]


def test_force_overrides_are_recorded_in_promoted_from(isolated_prod):
    iter_dir = _build_iter_dir(p.LAB_ITERATIONS_DIR, "iid-rec", ["a"])
    p._atomic_copy(iter_dir, p.PROD_CURRENT)
    p._write_promoted_from(
        {"id": "iid-rec", "name": "R", "cohort_id": "c", "verdict": "baseline",
         "training_run_id": None, "benchmark_run_id": None,
         "force_overrides": ["traceability"]},
        {},
    )
    payload = json.loads((p.PROD_CURRENT / "promoted_from.json").read_text())
    assert payload["force_overrides"] == ["traceability"]
