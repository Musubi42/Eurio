"""C4c — le push au canonique VPS devient automatique dès qu'EURIO_API_URL
est configuré, quel que soit l'appelant de l'orchestrateur (CLI, routes
admin, script futur) — plus d'entrypoint silencieusement Modèle A.

Couvre `sources._base.orchestrator._maybe_push_run` (hook commun) via
`run_pipeline` : sync désactivée = comportement historique inchangé ; sync
activée = push automatique en fin de run ; `push=False` explicite = garde
Modèle A même sync activée (équivalent `--no-push` CLI).
"""
from __future__ import annotations

import logging

import pytest

from sources._base.adapter import SourceQuery
from sources._base.orchestrator import run_pipeline
from sources._mock import MockAdapter
from store import Store


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


def test_no_push_without_sync_enabled(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans EURIO_API_URL : comportement historique, aucun appel réseau."""
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    calls: list[str] = []
    import client.runbatch as runbatch_mod

    monkeypatch.setattr(
        runbatch_mod, "push_run", lambda *a, **k: calls.append("push") or {}
    )

    adapter = MockAdapter()
    run_id = run_pipeline(adapter, SourceQuery(source_id="mock"), store=store)

    row = store._connection().execute(
        "SELECT status FROM source_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row["status"] == "success"
    assert calls == []


def test_auto_push_when_sync_enabled(store: Store, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """EURIO_API_URL configuré : push_run(conn, run_id) est appelé automatiquement."""
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    calls: list[tuple] = []

    import client.runbatch as runbatch_mod

    def _fake_push_run(conn, run_id, **kwargs):
        calls.append((run_id,))
        return {"counts": {"source_runs": 1}}

    monkeypatch.setattr(runbatch_mod, "push_run", _fake_push_run)

    adapter = MockAdapter()
    run_id = run_pipeline(adapter, SourceQuery(source_id="mock"), store=store)

    assert calls == [(run_id,)]
    assert any("push run=" in r.message for r in caplog.records)


def test_no_push_override_wins_even_when_sync_enabled(
    store: Store, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """push=False (équivalent --no-push CLI) suppresse le push même si la
    sync est configurée — échappatoire explicite Modèle A."""
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    calls: list[str] = []
    import client.runbatch as runbatch_mod

    monkeypatch.setattr(
        runbatch_mod, "push_run", lambda *a, **k: calls.append("push") or {}
    )

    adapter = MockAdapter()
    run_pipeline(adapter, SourceQuery(source_id="mock"), store=store, push=False)

    assert calls == []


def test_push_error_is_best_effort_not_raised(
    store: Store, monkeypatch: pytest.MonkeyPatch, caplog,
) -> None:
    """Un push qui échoue (réseau down) ne casse pas le run local : erreur
    loguée, run_pipeline retourne quand même le run_id."""
    caplog.set_level(logging.ERROR)
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    import client.runbatch as runbatch_mod

    def _boom(conn, run_id, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(runbatch_mod, "push_run", _boom)

    adapter = MockAdapter()
    run_id = run_pipeline(adapter, SourceQuery(source_id="mock"), store=store)

    row = store._connection().execute(
        "SELECT status FROM source_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row["status"] == "success"  # le run local reste valide
    assert any("push run=" in r.message and "échoué" in r.message for r in caplog.records)


def test_alternative_entrypoint_also_pushes(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un entrypoint alternatif qui appelle run_pipeline directement (ex.
    serving.sources_routes, sans passer par sources.cli) déclenche aussi le
    push automatiquement — pas d'entrypoint silencieusement Modèle A."""
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    calls: list[str] = []
    import client.runbatch as runbatch_mod

    monkeypatch.setattr(
        runbatch_mod, "push_run", lambda *a, **k: calls.append("push") or {}
    )

    # Simule un appel "nu" tel que serving/sources_routes.py le fait, sans
    # jamais mentionner --push/push=... explicitement.
    adapter = MockAdapter()
    run_pipeline(adapter, SourceQuery(source_id="mock"), store=store, dry_run=False)

    assert calls == ["push"]
