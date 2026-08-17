"""`GET /operations/cohorts` doit rendre le VRAI nombre de membres.

Le handler comptait `cohort_members`, une table normalisée que **seul**
`scripts/migrate_canonical_schema.py` backfille et qu'aucun writer ne
maintient. Les membres vivent dans `experiment_cohorts.eurio_ids_json` — c'est
ce que `/ingest/cohort` écrit et ce que le lab lit.

Résultat mesuré au canonique le 2026-08-17 : `cohort_members` contenait 0 ligne
pour 8 cohortes réellement peuplées (jusqu'à 27 pièces), et l'API annonçait
`n_members: 0` pour toutes. Le `COALESCE(…, 0)` transformait l'absence en zéro
plausible, et la page Operations du front affichait ce zéro sans un mot.

Famille du catalogue `eurio-verify` : *une valeur par défaut plausible là où il
fallait la vérité*.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from serving import operations_routes


@pytest.fixture()
def conn(monkeypatch) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute(
        """CREATE TABLE experiment_cohorts (
             id TEXT PRIMARY KEY, name TEXT, description TEXT, zone TEXT,
             eurio_ids_json TEXT, created_at TEXT, updated_at TEXT,
             status TEXT, frozen_at TEXT)"""
    )
    c.execute(
        """CREATE TABLE cohort_members (
             cohort_id TEXT NOT NULL, eurio_id TEXT NOT NULL,
             PRIMARY KEY (cohort_id, eurio_id))"""
    )
    monkeypatch.setattr(operations_routes, "_conn", lambda: c)
    return c


def _insert(c: sqlite3.Connection, cid: str, ids, status="frozen") -> None:
    c.execute(
        "INSERT INTO experiment_cohorts (id,name,zone,eurio_ids_json,created_at,status,frozen_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (cid, cid, None, json.dumps(ids), "2026-08-17 10:00:00", status, None),
    )


def test_n_members_reflects_eurio_ids_json_when_cohort_members_is_empty(conn):
    """Le cas réel du canonique : cohortes peuplées, table normalisée vide."""
    _insert(conn, "c-27", [f"x-{i}" for i in range(27)])
    _insert(conn, "c-3", ["a", "b", "c"])

    rows = {c.id: c.n_members for c in operations_routes.cohorts().cohorts}

    assert rows["c-27"] == 27, "une cohorte de 27 pièces ne doit pas être annoncée vide"
    assert rows["c-3"] == 3


def test_empty_and_null_cohorts_report_zero(conn):
    """Zéro reste zéro — on ne remplace pas un bug par un autre."""
    _insert(conn, "c-empty", [], status="draft")
    conn.execute(
        "INSERT INTO experiment_cohorts (id,name,eurio_ids_json,created_at,status)"
        " VALUES ('c-null','c-null',NULL,'2026-08-17 10:00:00','draft')"
    )

    rows = {c.id: c.n_members for c in operations_routes.cohorts().cohorts}

    assert rows["c-empty"] == 0
    assert rows["c-null"] == 0


def test_counts_are_not_read_from_cohort_members(conn):
    """Garde anti-régression : si quelqu'un re-branche la table normalisée,
    ce test tombe. `eurio_ids_json` fait foi — c'est la seule source qu'un
    writer alimente."""
    _insert(conn, "c-x", ["a", "b"])
    conn.executemany(
        "INSERT INTO cohort_members (cohort_id, eurio_id) VALUES (?,?)",
        [("c-x", f"stale-{i}") for i in range(9)],
    )

    rows = {c.id: c.n_members for c in operations_routes.cohorts().cohorts}

    assert rows["c-x"] == 2, "eurio_ids_json fait foi, pas cohort_members"
