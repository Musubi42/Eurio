"""Lot 2 « juge et banc » — les trois fuites entre le juge et l'entraînement.

Chaque test de ce fichier garde un chemin RÉELLEMENT emprunté, pas un prédicat
isolé (cf. `.claude/skills/eurio-verify` : « un garde posé, testé, muté — et
jamais appelé »). Les quatre mutations qui les font rougir sont listées dans
`docs/work-in-progress/juge-et-banc/LOT2-FUITES.md`.

Ce qui est gardé ici :
  (a) `pipeline._compute_embeddings` passe TOUJOURS `--centroid-source` ;
  (b) `prepare_dataset` exige `--val-source` en mode lab, et `val/` doit être
      VIDE dès que la source n'est pas `device` (garde de contenu) ;
  (c) `iteration_runner` pose les deux valeurs explicitement dans la config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from store import RunRow, Store
from training.pipeline import TrainingPipeline


# ─── (a) La chaîne du centroïde ────────────────────────────────────────────


@pytest.fixture
def pipe_row(tmp_path):
    def _make(config: dict):
        store = Store(tmp_path / "pipe.db")
        run_id = "runjb01"
        store.create_run(RunRow(id=run_id, version=1, status="queued", config=config))
        pipe = TrainingPipeline(store, run_id)
        captured: list[list[str]] = []
        pipe._run_subprocess = lambda _rid, cmd, **kw: captured.append(list(cmd))  # type: ignore[method-assign]
        row = store.get_run(run_id)
        return pipe, row, captured

    return _make


def test_compute_embeddings_always_passes_centroid_source(pipe_row):
    """Sans `--centroid-source`, compute_embeddings retombe sur `auto` → val_mean
    → moyenne des photos du juge. C'est la fuite (a) du PROBLEME.md §1bis."""
    pipe, row, captured = pipe_row({"epochs": 1})

    pipe._compute_embeddings(row, "v42")

    assert len(captured) == 1
    cmd = captured[0]
    assert "--centroid-source" in cmd, (
        "compute_embeddings appelé sans --centroid-source → défaut 'auto' → "
        "le prototype d'une classe est la moyenne de ses photos de test"
    )
    assert cmd[cmd.index("--centroid-source") + 1] == "train_mean"


def test_compute_embeddings_centroid_source_comes_from_config(pipe_row):
    pipe, row, captured = pipe_row({"epochs": 1, "centroid_source": "arcface_w"})

    pipe._compute_embeddings(row, "v42")

    cmd = captured[0]
    assert cmd[cmd.index("--centroid-source") + 1] == "arcface_w"


def test_compute_embeddings_never_emits_auto(pipe_row):
    """`auto` ne doit jamais sortir du pipeline, même si quelqu'un l'y met."""
    pipe, row, captured = pipe_row({"epochs": 1})
    pipe._compute_embeddings(row, "v42")
    assert "auto" not in captured[0]


# ─── (b) La chaîne du split de validation ──────────────────────────────────


def test_prepare_passes_val_source_in_lab_mode(pipe_row, tmp_path):
    iter_dir = tmp_path / "iter"
    (iter_dir / "dataset").mkdir(parents=True)
    pipe, row, captured = pipe_row(
        {"epochs": 1, "iter_dir": str(iter_dir), "val_source": "none"}
    )

    pipe._prepare(row)

    cmd = captured[0]
    assert "--val-source" in cmd
    assert cmd[cmd.index("--val-source") + 1] == "none"
    assert "--skip-train-split" in cmd


def test_prepare_refuses_lab_mode_without_val_source(pipe_row, tmp_path):
    iter_dir = tmp_path / "iter"
    (iter_dir / "dataset").mkdir(parents=True)
    pipe, row, _captured = pipe_row({"epochs": 1, "iter_dir": str(iter_dir)})

    with pytest.raises(RuntimeError) as exc:
        pipe._prepare(row)
    assert "val_source" in str(exc.value)
    assert "device|ebay|none" in str(exc.value)


def test_cli_requires_val_source_in_lab_mode(monkeypatch, tmp_path):
    """Le point d'entrée RÉEL (`main()`), pas seulement le prédicat."""
    import training.prepare_dataset as pd

    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_dataset.py",
            "--skip-train-split",
            "--class-kind", "design_group",
            "--raw-dir", str(tmp_path / "raw"),
            "--output-dir", str(tmp_path / "out"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        pd.main()
    msg = str(exc.value)
    assert "--val-source" in msg
    assert "device|ebay|none" in msg


def test_val_holdout_guard_rejects_non_empty_val(tmp_path):
    """Garde de CONTENU — le seul posé sur le chemin réel de la fuite.

    `_override_val_with_eval_real` COPIE des fichiers : aucun chemin de hold-out
    n'apparaît dans une ligne de commande, donc le garde de chemin
    (`_assert_no_real_photos`) ne peut pas la voir.
    """
    import training.prepare_dataset as pd

    out = tmp_path / "out"
    val_cls = out / "val" / "fr-2euro-standard-t1"
    val_cls.mkdir(parents=True)
    (val_cls / "fr-2007-2eur__step3.jpg").write_bytes(b"x")

    with pytest.raises(SystemExit) as exc:
        pd._assert_val_holdout_free(out, "none")
    msg = str(exc.value)
    assert "Fuite de hold-out" in msg
    assert "fr-2007-2eur__step3.jpg" in msg


def test_val_holdout_guard_silent_when_val_empty(tmp_path):
    import training.prepare_dataset as pd

    out = tmp_path / "out"
    (out / "val").mkdir(parents=True)
    pd._assert_val_holdout_free(out, "none")  # ne doit pas lever


def test_val_holdout_guard_does_not_fire_for_device(tmp_path):
    """`device` est le mode legacy assumé : le garde le laisse passer (et
    `_override_val_with_eval_real` journalise alors le WARNING)."""
    import training.prepare_dataset as pd

    out = tmp_path / "out"
    val_cls = out / "val" / "fr-2euro-standard-t1"
    val_cls.mkdir(parents=True)
    (val_cls / "a.jpg").write_bytes(b"x")
    pd._assert_val_holdout_free(out, "device")  # ne doit pas lever


def test_ebay_val_source_is_explicitly_not_implemented():
    """Un `val/` vide en silence serait exactement le défaut qu'on corrige."""
    import training.prepare_dataset as pd

    with pytest.raises(SystemExit) as exc:
        pd._announce_no_device_val("ebay")
    assert "n'existe pas encore" in str(exc.value)


def test_device_val_source_warns_it_is_not_comparable(tmp_path, capsys):
    """Le mode legacy reste possible, mais il DIT qu'il n'est pas comparable."""
    import training.prepare_dataset as pd
    from training.eval.class_resolver import ClassDescriptor

    # `_override_val_with_eval_real` cherche <raw_dir>/../datasets/eval_real_norm.
    # On le fait pointer sur un faux corpus du tmpdir — sans ça, le test
    # retomberait sur le VRAI ml/datasets/eval_real_norm et deviendrait
    # dépendant de la machine.
    root = tmp_path / "root"
    (root / "datasets" / "eval_real_norm" / "fr-2007-2eur").mkdir(parents=True)
    (root / "datasets" / "eval_real_norm" / "fr-2007-2eur" / "s1.jpg").write_bytes(b"x")
    raw_dir = root / "raw"
    out = tmp_path / "out"
    out.mkdir()
    desc = ClassDescriptor(
        class_id="fr-2euro-standard-t1",
        class_kind="design_group",
        numista_ids=(),
        eurio_ids=("fr-2007-2eur",),
    )
    pd._override_val_with_eval_real(raw_dir, out, [desc], "design_group")
    captured = capsys.readouterr().out
    assert "WARNING [--val-source=device]" in captured
    assert "N'EST PAS comparable au juge" in captured


# ─── (c) L'amont : iteration_runner pose les deux valeurs ──────────────────


def test_iteration_runner_source_states_both_keys():
    """La chaîne doit être lisible d'un `grep` — pas reconstituée à la main."""
    src = Path(__file__).parent.parent / "serving" / "iteration_runner.py"
    text = src.read_text()
    assert 'config["val_source"]' in text
    assert 'config["centroid_source"]' in text


# ─── Le défaut `auto` conservé, mais jamais muet ───────────────────────────


def test_auto_centroid_source_names_val_mean_when_val_populated(tmp_path):
    from training.compute_embeddings import describe_auto_source

    (tmp_path / "val" / "cls").mkdir(parents=True)
    (tmp_path / "val" / "cls" / "a.jpg").write_bytes(b"x")
    msg = describe_auto_source(tmp_path)
    assert "WARNING" in msg
    assert "val_mean" in msg
    assert "1 fichier(s)" in msg


def test_auto_centroid_source_names_arcface_w_when_val_empty(tmp_path):
    from training.compute_embeddings import describe_auto_source

    msg = describe_auto_source(tmp_path)
    assert "WARNING" in msg
    assert "arcface_w" in msg
    assert "val_mean" not in msg


def test_auto_centroid_source_ne_dit_pas_absent_quand_il_a_ete_passe(tmp_path):
    """Le message accusait une cause fausse (LOT4-RESULTATS.md §6).

    `training/pipeline.py` passe `--centroid-source` explicitement depuis le
    lot 2 ; le WARNING annonçait quand même « --centroid-source absent ».
    """
    from training.compute_embeddings import describe_auto_source

    msg = describe_auto_source(tmp_path, explicit=True)
    assert "absent" not in msg
    assert "passé explicitement" in msg

    herite = describe_auto_source(tmp_path, explicit=False)
    assert "absent" in herite
