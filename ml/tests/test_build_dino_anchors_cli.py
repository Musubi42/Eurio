"""A4 — `build_dino_anchors --db` ne doit plus être un leurre.

Le drapeau laisse croire qu'on choisit la base ; ``Store(path)`` hérite du
``read_only`` de l'environnement (``EURIO_DB_READONLY``, posé par le devShell).
Résultat mesuré : l'écriture de ``dino_class_references`` échoue **après** les
~4 minutes d'encodage, et la table est vide dans les 6 bases de la machine.

Le piège précis : ``BEGIN IMMEDIATE`` **réussit** sur une connexion ``mode=ro``
(cf. test ci-dessous) — rien ne prévient à l'ouverture de la transaction. Seule
une vraie écriture révèle le problème. D'où le probe.
"""

from __future__ import annotations

import pytest

import scripts.build_dino_anchors as bda
from scripts.build_dino_anchors import (
    WRITING_KINDS,
    ReadOnlyTraceabilityError,
    preflight_db_traceability,
)
from store import Store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.delenv("EURIO_DB_READONLY", raising=False)
    path = tmp_path / "eurio.test.db"
    Store(path, read_only=False)  # bootstrap du schéma
    return path


def test_begin_immediate_is_silent_on_a_readonly_store(db, monkeypatch):
    """Le fait qui rend le bug tardif — documenté par un test, pas par un commentaire."""
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    store = Store(db)
    assert store.read_only is True
    with pytest.raises(Exception) as exc:
        with store._writing() as conn:  # noqa: SLF001
            # BEGIN IMMEDIATE est déjà passé ici : rien n'a prévenu.
            conn.execute("CREATE TABLE _late_boom (x)")
    assert "readonly" in str(exc.value).lower()


def test_preflight_raises_early_when_db_is_readonly(db, monkeypatch):
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    store = Store(db)
    with pytest.raises(ReadOnlyTraceabilityError) as exc:
        preflight_db_traceability(store, "2eur_all", skip_references=False)
    msg = str(exc.value)
    assert "EURIO_DB_READONLY" in msg, "le message doit nommer la variable coupable"
    assert "--skip-references" in msg, "le message doit nommer l'échappatoire"
    assert str(db) in msg, "le message doit nommer la base réellement ouverte"


def test_preflight_returns_true_on_a_writable_db(db):
    assert preflight_db_traceability(store := Store(db), "2eur_all",
                                     skip_references=False) is True
    assert store.read_only is False


def test_preflight_probe_leaves_no_residue(db):
    store = Store(db)
    preflight_db_traceability(store, "2eur_all", skip_references=False)
    rows = store._connection().execute(  # noqa: SLF001
        "SELECT name FROM sqlite_master WHERE name LIKE '%probe%'"
    ).fetchall()
    assert rows == []


def test_skip_references_tolerates_a_readonly_db(db, monkeypatch):
    """Échappatoire explicite : on renonce à la traçabilité, le .npz reste écrit."""
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    store = Store(db)
    assert preflight_db_traceability(store, "2eur_all", skip_references=True) is False


def test_dispatcher_propagates_write_references_and_avoids_the_write_txn(
    db, monkeypatch
):
    """Le câblage : --skip-references doit atteindre le builder ET éviter
    d'ouvrir une transaction d'écriture sur une base read-only."""
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    store = Store(db)
    seen = {}

    def _fake_builder(*, conn, datasets_dir, force_recompute,
                      write_references=None, write_legacy=None):
        seen["write_references"] = write_references
        seen["in_transaction"] = conn.in_transaction
        return object()

    monkeypatch.setitem(bda._BUILDERS, "2eur_all", _fake_builder)
    bda._build_dispatcher("2eur_all", store, False, write_references=False)
    assert seen["write_references"] is False
    # `_writing()` ouvre un BEGIN IMMEDIATE ; il ne doit PAS avoir eu lieu.
    # (`in_transaction` est le seul témoin : sur une conn mode=ro le BEGIN
    # IMMEDIATE réussit en silence — cf. test_begin_immediate_is_silent.)
    assert seen["in_transaction"] is False


def test_dispatcher_opens_the_write_txn_when_tracing(db, monkeypatch):
    monkeypatch.delenv("EURIO_DB_READONLY", raising=False)
    store = Store(db)
    seen = {}

    def _fake_builder(*, conn, datasets_dir, force_recompute,
                      write_references=None, write_legacy=None):
        seen["in_transaction"] = conn.in_transaction
        return object()

    monkeypatch.setitem(bda._BUILDERS, "2eur_all", _fake_builder)
    bda._build_dispatcher("2eur_all", store, False, write_references=True)
    assert seen["in_transaction"] is True


@pytest.mark.parametrize("kind", ["2eur_commemo", "2eur_standard", "reverse_2eur"])
def test_readonly_db_is_fine_for_non_writing_kinds(db, monkeypatch, kind):
    """Les banques qui ne tracent rien n'ont aucune raison d'exiger l'écriture."""
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    store = Store(db)
    assert kind not in WRITING_KINDS
    assert preflight_db_traceability(store, kind, skip_references=False) is False


def test_db_path_defaut_honore_eurio_db_path(monkeypatch, tmp_path):
    """Le défaut de `--db` suit `EURIO_DB_PATH`, pas `state/eurio.db` en dur.

    Régression du 2026-08-19 : la banque `2eur_all` servie avait été bâtie sur
    `ml/state/eurio.db` (base de travail périmée, 6205 `image_assets`) alors
    que la review lit la réplique (12454). Conséquence mesurée : 125 classes
    avec exemplaires FPS au lieu des 182 qui en ont des candidats — 57 classes
    de review déjà tranchée absentes de la banque.
    """
    import importlib

    replique = tmp_path / "eurio.replica.db"
    monkeypatch.setenv("EURIO_DB_PATH", str(replique))
    module = importlib.reload(bda)
    try:
        assert module.DB_PATH == replique
    finally:
        monkeypatch.delenv("EURIO_DB_PATH", raising=False)
        importlib.reload(bda)
