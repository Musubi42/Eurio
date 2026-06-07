"""Tests d'extraction du pipeline training (refacto-ml chunk 2a).

Vérifie le plomberie des hooks (`PipelineHooks`) qui relie le pipeline extrait à
l'état live du runner — sans lancer de vrai subprocess d'entraînement. Couvre :
buffer de logs + mirroir `on_log`, et le parsing d'epoch (`on_epoch` + écriture
`append_epoch`/`upsert_step` en Store).
"""

from __future__ import annotations

import pytest

from state import RunRow, Store
from training.pipeline import PipelineHooks, TrainingPipeline


@pytest.fixture
def store_run(tmp_path):
    store = Store(tmp_path / "pipe.db")
    run_id = "run0001"
    store.create_run(RunRow(id=run_id, version=1, status="queued", config={"epochs": 40}))
    return store, run_id


def test_emit_log_buffers_prints_and_mirrors(store_run, capsys):
    store, run_id = store_run
    seen: list[str] = []
    pipe = TrainingPipeline(store, run_id, hooks=PipelineHooks(on_log=seen.append))

    pipe._emit_log("hello world")

    assert pipe._log_lines == ["hello world"]      # bufferisé pour save_logs
    assert seen == ["hello world"]                 # mirroir live (sink iteration)
    assert "hello world" in capsys.readouterr().out  # stdout → fichier de log en détaché


def test_emit_log_sink_failure_never_propagates(store_run):
    store, run_id = store_run

    def boom(_line):
        raise RuntimeError("sink down")

    pipe = TrainingPipeline(store, run_id, hooks=PipelineHooks(on_log=boom))
    pipe._emit_log("still buffered")  # ne doit pas lever
    assert pipe._log_lines == ["still buffered"]


def test_parse_epoch_line_fires_hook_and_persists(store_run):
    store, run_id = store_run
    epochs_seen: list[int] = []
    pipe = TrainingPipeline(store, run_id, hooks=PipelineHooks(on_epoch=epochs_seen.append))

    pipe._parse_epoch_line(run_id, "Epoch 3 loss: 1.50 R@1: 80% R@3: 95%")

    assert epochs_seen == [3]
    epochs = store.list_epochs(run_id)
    assert len(epochs) == 1
    e = epochs[0]
    assert e.epoch == 3
    assert e.train_loss == pytest.approx(1.50)
    assert e.recall_at_1 == pytest.approx(0.80)
    assert e.recall_at_3 == pytest.approx(0.95)


def test_parse_epoch_line_ignores_non_epoch_lines(store_run):
    store, run_id = store_run
    pipe = TrainingPipeline(store, run_id)
    pipe._parse_epoch_line(run_id, "Preparing dataset…")
    pipe._parse_epoch_line(run_id, "Epoch 5 starting")  # pas de 'loss:' → ignoré
    assert store.list_epochs(run_id) == []


def test_parse_epoch_duration_uses_previous_timestamp(store_run):
    store, run_id = store_run
    pipe = TrainingPipeline(store, run_id)
    # 1re epoch : pas de ts précédent → duration None.
    pipe._parse_epoch_line(run_id, "Epoch 1 loss: 2.0")
    # 2e epoch : ts précédent posé → duration calculée (>= 0).
    pipe._parse_epoch_line(run_id, "Epoch 2 loss: 1.8")
    epochs = {e.epoch: e for e in store.list_epochs(run_id)}
    assert epochs[1].duration_sec is None
    assert epochs[2].duration_sec is not None and epochs[2].duration_sec >= 0


def test_hooks_optional_no_crash(store_run):
    """Sans hooks (mode détaché 2b), le pipeline ne doit jamais planter sur un hook None."""
    store, run_id = store_run
    pipe = TrainingPipeline(store, run_id)  # hooks par défaut = tous None
    pipe._emit_log("no hooks")
    pipe._parse_epoch_line(run_id, "Epoch 1 loss: 1.0 R@1: 50%")
    assert pipe._log_lines == ["no hooks"]
    assert len(store.list_epochs(run_id)) == 1
