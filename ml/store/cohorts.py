"""Store — domaine cohorts (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class ExperimentCohortRow:
    id: str
    name: str
    description: str | None = None
    zone: str | None = None
    eurio_ids: list[str] = field(default_factory=list)
    status: str = "draft"
    frozen_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "zone": self.zone,
            "eurio_ids": self.eurio_ids,
            "status": self.status,
            "frozen_at": self.frozen_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_cohort(r: sqlite3.Row) -> ExperimentCohortRow:
    return ExperimentCohortRow(
        id=r["id"],
        name=r["name"],
        description=r["description"],
        zone=r["zone"],
        eurio_ids=json.loads(r["eurio_ids_json"]),
        status=r["status"] or "draft",
        frozen_at=r["frozen_at"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


class CohortsMixin:

    # ─── Experiment cohorts ──────────────────────────────────────────────

    def create_cohort(self, cohort: ExperimentCohortRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO experiment_cohorts (
                  id, name, description, zone, eurio_ids_json, status, frozen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cohort.id,
                    cohort.name,
                    cohort.description,
                    cohort.zone,
                    json.dumps(cohort.eurio_ids),
                    cohort.status,
                    cohort.frozen_at,
                ),
            )

    def upsert_cohort(self, cohort: ExperimentCohortRow) -> None:
        """Écrit le snapshot COMPLET d'une cohorte (INSERT ou REMPLACE tout).

        Utilisé par le canonique (F09) : une machine de calcul pousse l'état de
        sa cohorte à chaque write lab local ; le canonique remplace la row
        entière (id uuid4 = propriété d'une seule machine → last-writer-wins
        sans conflit réel). Préserve ``created_at`` de la SOURCE quand fourni
        (miroir de ``upsert_iteration``) ; ``updated_at`` = valeur source ou
        ``datetime('now')`` à défaut.
        """
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO experiment_cohorts (
                  id, name, description, zone, eurio_ids_json, status,
                  frozen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?,
                          COALESCE(?, datetime('now')),
                          COALESCE(?, datetime('now')))
                ON CONFLICT(id) DO UPDATE SET
                  name           = excluded.name,
                  description    = excluded.description,
                  zone           = excluded.zone,
                  eurio_ids_json = excluded.eurio_ids_json,
                  status         = excluded.status,
                  frozen_at      = excluded.frozen_at,
                  created_at     = CASE WHEN ? IS NULL
                                        THEN experiment_cohorts.created_at
                                        ELSE excluded.created_at END,
                  updated_at     = excluded.updated_at
                """,
                (
                    cohort.id,
                    cohort.name,
                    cohort.description,
                    cohort.zone,
                    json.dumps(cohort.eurio_ids),
                    cohort.status,
                    cohort.frozen_at,
                    cohort.created_at,
                    cohort.updated_at,
                    cohort.created_at,
                ),
            )

    def update_cohort(
        self,
        cohort_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        zone: str | None = None,
        eurio_ids: list[str] | None = None,
        status: str | None = None,
        frozen_at: str | None = None,
    ) -> None:
        """Update mutable cohort fields.

        `eurio_ids` and `status` should only be touched while the cohort is
        ``draft``; the route layer enforces that — the store stays dumb.
        """
        fields_sql = ["updated_at = datetime('now')"]
        params: list = []
        if name is not None:
            fields_sql.append("name = ?")
            params.append(name)
        if description is not None:
            fields_sql.append("description = ?")
            params.append(description)
        if zone is not None:
            fields_sql.append("zone = ?")
            params.append(zone)
        if eurio_ids is not None:
            fields_sql.append("eurio_ids_json = ?")
            params.append(json.dumps(eurio_ids))
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if frozen_at is not None:
            fields_sql.append("frozen_at = ?")
            params.append(frozen_at)
        if len(fields_sql) == 1:
            return
        params.append(cohort_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE experiment_cohorts SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_cohort(self, id_or_name: str) -> ExperimentCohortRow | None:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM experiment_cohorts WHERE id = ?", (id_or_name,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM experiment_cohorts WHERE name = ?", (id_or_name,)
            ).fetchone()
        return _row_to_cohort(row) if row else None

    def list_cohorts(
        self,
        *,
        zone: str | None = None,
        status: str | None = None,
    ) -> list[ExperimentCohortRow]:
        q = "SELECT * FROM experiment_cohorts"
        clauses: list[str] = []
        params: list = []
        if zone is not None:
            clauses.append("zone = ?")
            params.append(zone)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_at DESC"
        return [
            _row_to_cohort(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def delete_cohort(self, cohort_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM experiment_cohorts WHERE id = ?", (cohort_id,)
            )
            return cur.rowcount > 0
