"""Rerouting des écritures de dimensions lab (Direction A, C5).

Le devShell Mac/PC pose ``EURIO_DB_READONLY=1`` : le SQLite local est une
réplique read-only. Avant ce rerouting, créer une cohorte levait
``attempt to write a readonly database`` → 503 « Route non encore reroutée ».

Ce qui compte ici n'est pas seulement que l'écriture parte au canonique, mais
qu'elle n'ait JAMAIS l'air d'avoir réussi quand elle n'y est pas arrivée.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from serving import lab_writes  # noqa: E402
from store import ExperimentCohortRow, Store  # noqa: E402
from store.iterations import ExperimentIterationRow  # noqa: E402


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


@pytest.fixture()
def flip(monkeypatch):
    """Simule le flip C5 : le store local est une réplique read-only."""
    monkeypatch.setattr(lab_writes, "local_is_replica", lambda: True)
    monkeypatch.setattr(lab_writes, "_remote_configured", lambda: True)
    monkeypatch.setattr(lab_writes, "refresh_replica", lambda: None)


def _cohort(cid="c1", **kw) -> ExperimentCohortRow:
    return ExperimentCohortRow(id=cid, name=kw.pop("name", "coh"), eurio_ids=["a"], **kw)


def _iteration(iid="i1", cohort_id="c1") -> ExperimentIterationRow:
    return ExperimentIterationRow(id=iid, cohort_id=cohort_id, name="it")


# ─── Sous le flip : le canonique fait autorité ─────────────────────────────


def test_cohort_write_goes_to_canonical_and_not_to_the_replica(store, flip, monkeypatch):
    pushed: list[dict] = []
    import client.ingest as ingest

    monkeypatch.setattr(ingest, "push_cohort", lambda d: pushed.append(d))

    row = _cohort()
    lab_writes.write_cohort(store, row)

    assert pushed and pushed[0]["id"] == "c1"
    # La réplique n'est PAS écrite : c'est tout l'objet du flip.
    assert store.get_cohort("c1") is None


def test_cohort_write_failure_is_never_a_silent_success(store, flip, monkeypatch):
    import client.ingest as ingest

    def _boom(_d):
        raise RuntimeError("VPS injoignable")

    monkeypatch.setattr(ingest, "push_cohort", _boom)

    with pytest.raises(HTTPException) as exc:
        lab_writes.write_cohort(store, _cohort())
    assert exc.value.status_code == 502
    assert "canonique" in str(exc.value.detail)


def test_flip_without_a_canonical_refuses_instead_of_no_oping(store, monkeypatch):
    """Le cas qui ferait le plus de dégâts : `push_cohort` est un no-op
    documenté quand aucun canonique n'est configuré. Sous le flip, cela
    répondrait 200 sans que rien ne soit écrit NULLE PART."""
    monkeypatch.setattr(lab_writes, "local_is_replica", lambda: True)
    monkeypatch.setattr(lab_writes, "_remote_configured", lambda: False)

    with pytest.raises(HTTPException) as exc:
        lab_writes.write_cohort(store, _cohort())
    assert exc.value.status_code == 503
    assert "nulle part" in str(exc.value.detail)


def test_iteration_write_pushes_the_parent_cohort_first(store, flip, monkeypatch):
    """Le canonique refuse (409) une itération dont la cohorte lui est inconnue."""
    store.create_cohort(_cohort())
    order: list[str] = []
    import client.http as http
    import client.ingest as ingest

    monkeypatch.setattr(ingest, "push_cohort", lambda d: order.append("cohort"))
    monkeypatch.setattr(http, "put_json", lambda p, d, **kw: order.append("iteration"))

    lab_writes.write_iteration(store, _iteration())
    assert order == ["cohort", "iteration"]


def test_cohort_delete_reports_absent_without_calling_canonical(store, flip, monkeypatch):
    calls: list[str] = []
    import client.ingest as ingest

    monkeypatch.setattr(ingest, "push_cohort_delete", lambda i: calls.append(i))

    assert lab_writes.delete_cohort(store, "inconnue") is False
    assert calls == []


# ─── Hors flip : comportement d'origine préservé ───────────────────────────


def test_without_flip_the_write_stays_local(store, monkeypatch):
    monkeypatch.setattr(lab_writes, "local_is_replica", lambda: False)
    import client.ingest as ingest

    monkeypatch.setattr(ingest, "push_cohort", lambda d: None)

    lab_writes.write_cohort(store, _cohort())
    saved = store.get_cohort("c1")
    assert saved is not None and saved.name == "coh"


def test_without_flip_a_canonical_failure_stays_best_effort(store, monkeypatch):
    """Hors flip le local fait foi : le VPS injoignable ne doit pas faire échouer
    l'action — le backfill `ml:lab:push-dimensions` rattrape."""
    monkeypatch.setattr(lab_writes, "local_is_replica", lambda: False)
    import client.ingest as ingest

    def _boom(_d):
        raise RuntimeError("VPS injoignable")

    monkeypatch.setattr(ingest, "push_cohort", _boom)

    lab_writes.write_cohort(store, _cohort())   # ne doit pas lever
    assert store.get_cohort("c1") is not None


# ─── Rafraîchissement de la réplique ───────────────────────────────────────


def test_refresh_is_skipped_when_only_the_expensive_transport_is_available(monkeypatch):
    """Sans `sqlite3_rsync`, le repli est un snapshot complet (~156 Mo, ~20 s) :
    l'imposer à chaque clic serait pire que le retard d'un pull."""
    import client.replica as replica

    pulled: list[str] = []
    monkeypatch.setattr(replica, "rsync_available", lambda: False)
    monkeypatch.setattr(replica, "pull_replica_auto", lambda *a, **k: pulled.append("x"))

    lab_writes.refresh_replica()
    assert pulled == []


def test_refresh_failure_never_turns_a_successful_write_into_an_error(monkeypatch):
    import client.replica as replica

    monkeypatch.setattr(replica, "rsync_available", lambda: True)

    def _boom(*_a, **_k):
        raise RuntimeError("ssh down")

    monkeypatch.setattr(replica, "pull_replica_auto", _boom)
    lab_writes.refresh_replica()   # ne doit pas lever : le canonique a déjà accepté


# ─── Robustesse du canonique face à une row jamais persistée localement ────


def test_upsert_iteration_defaults_created_at(tmp_path):
    """Le canonique doit accepter une row fraîche.

    Sous Direction A, une itération peut naître **directement** au canonique :
    elle n'a alors jamais traversé l'INSERT local qui stampe `created_at`, et la
    colonne est `NOT NULL` sans défaut. Constaté en vrai — le premier essai de
    création d'itération sous le flip a rendu
    `NOT NULL constraint failed: experiment_iterations.created_at`.
    `upsert_cohort` se protégeait déjà ainsi ; son miroir ne le faisait pas.
    """
    store = Store(tmp_path / "canon.db")
    store.create_cohort(_cohort())
    store.upsert_iteration(_iteration())        # created_at = None

    saved = store.get_iteration("i1")
    assert saved is not None
    assert saved.created_at, "created_at doit être stampé par défaut"


def test_upsert_iteration_preserves_a_provided_created_at(tmp_path):
    """Le défaut ne doit pas écraser l'horodatage de la machine d'origine."""
    store = Store(tmp_path / "canon.db")
    store.create_cohort(_cohort())
    row = _iteration()
    row.created_at = "2026-01-02 03:04:05"
    store.upsert_iteration(row)

    assert store.get_iteration("i1").created_at == "2026-01-02 03:04:05"
