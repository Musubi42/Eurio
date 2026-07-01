"""Tests du push best-effort des itérations vers le canonique (R3.2, Model B).

Vérifie le gating (`_canonical_push_enabled`), le snapshot poussé (origine +
summary), et la robustesse (aucune exception ne remonte, no-op si désactivé).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


def _runner_with_iteration(tmp_path: Path):
    from serving.iteration_runner import IterationRunner
    from store import (
        AugmentationRecipeRow,
        ExperimentCohortRow,
        ExperimentIterationRow,
        Store,
    )

    store = Store(tmp_path / "t.db")
    store.create_cohort(ExperimentCohortRow(id="c1", name="c1", eurio_ids=["x"]))
    store.create_recipe(
        AugmentationRecipeRow(id="r1", name="low-light-v1", zone="orange", config={"layers": []})
    )
    store.create_iteration(
        ExperimentIterationRow(id="it1", cohort_id="c1", name="iter", recipe_id="r1")
    )
    return IterationRunner(store, None), store


# ─── Gating ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"EURIO_ITERATION_PUSH": "1"}, True),
        ({"EURIO_ITERATION_PUSH": "0"}, False),
        ({"EURIO_API_URL": "https://eurio-api.musubi.dev"}, True),
        ({"EURIO_API_URL": "http://127.0.0.1:8042"}, False),
        ({"EURIO_API_URL": "http://localhost:8042"}, False),
        ({}, False),
    ],
)
def test_canonical_push_enabled(monkeypatch, env, expected):
    from serving.iteration_runner import _canonical_push_enabled

    monkeypatch.delenv("EURIO_ITERATION_PUSH", raising=False)
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert _canonical_push_enabled() is expected


# ─── Push ───────────────────────────────────────────────────────────────────


def test_sync_pushes_snapshot_with_origin_and_summary(tmp_path, monkeypatch):
    runner, _ = _runner_with_iteration(tmp_path)
    monkeypatch.setenv("EURIO_ITERATION_PUSH", "1")
    monkeypatch.setenv("EURIO_MACHINE_ORIGIN", "pc")

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "client.http.put_json",
        lambda path, payload, **kw: calls.append((path, payload)) or {},
    )

    runner._sync_canonical("it1")

    assert len(calls) == 1
    path, payload = calls[0]
    assert path == "/iterations/it1"
    assert payload["id"] == "it1"
    assert payload["created_on"] == "pc"
    # summary dénormalisé (recette résolue ; pas de run → bench/training None)
    assert payload["summary"]["recipe_name"] == "low-light-v1"
    assert payload["summary"]["benchmark_summary"] is None
    assert payload["summary"]["training_summary"] is None


def test_sync_is_noop_when_disabled(tmp_path, monkeypatch):
    runner, _ = _runner_with_iteration(tmp_path)
    monkeypatch.setenv("EURIO_ITERATION_PUSH", "0")
    called = []
    monkeypatch.setattr("client.http.put_json", lambda *a, **k: called.append(1) or {})
    runner._sync_canonical("it1")
    assert called == []


def test_sync_swallows_transport_errors(tmp_path, monkeypatch):
    runner, _ = _runner_with_iteration(tmp_path)
    monkeypatch.setenv("EURIO_ITERATION_PUSH", "1")

    def boom(*a, **k):
        raise RuntimeError("VPS injoignable")

    monkeypatch.setattr("client.http.put_json", boom)
    # Ne doit PAS lever : un run ne dépend pas de la joignabilité du canonique.
    runner._sync_canonical("it1")


def test_sync_noop_on_missing_iteration(tmp_path, monkeypatch):
    runner, _ = _runner_with_iteration(tmp_path)
    monkeypatch.setenv("EURIO_ITERATION_PUSH", "1")
    called = []
    monkeypatch.setattr("client.http.put_json", lambda *a, **k: called.append(1) or {})
    runner._sync_canonical("does-not-exist")
    assert called == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
