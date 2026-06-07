"""Store — domaine augmentation (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass
class AugmentationRecipeRow:
    id: str
    name: str
    zone: str | None
    config: dict
    based_on_recipe_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "zone": self.zone,
            "config": self.config,
            "based_on_recipe_id": self.based_on_recipe_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class AugmentationRunRow:
    id: str
    recipe_id: str | None
    eurio_id: str | None
    design_group_id: str | None
    count: int
    seed: int | None
    output_dir: str
    status: str
    duration_ms: int | None = None
    error: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recipe_id": self.recipe_id,
            "eurio_id": self.eurio_id,
            "design_group_id": self.design_group_id,
            "count": self.count,
            "seed": self.seed,
            "output_dir": self.output_dir,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "created_at": self.created_at,
        }


def _row_to_recipe(r: sqlite3.Row) -> AugmentationRecipeRow:
    return AugmentationRecipeRow(
        id=r["id"],
        name=r["name"],
        zone=r["zone"],
        config=json.loads(r["config_json"]),
        based_on_recipe_id=r["based_on_recipe_id"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_aug_run(r: sqlite3.Row) -> AugmentationRunRow:
    return AugmentationRunRow(
        id=r["id"],
        recipe_id=r["recipe_id"],
        eurio_id=r["eurio_id"],
        design_group_id=r["design_group_id"],
        count=r["count"],
        seed=r["seed"],
        output_dir=r["output_dir"],
        status=r["status"],
        duration_ms=r["duration_ms"],
        error=r["error"],
        created_at=r["created_at"],
    )


class AugmentationMixin:

    # ─── Augmentation recipes ────────────────────────────────────────────

    def create_recipe(self, recipe: AugmentationRecipeRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO augmentation_recipes (
                  id, name, zone, config_json, based_on_recipe_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    recipe.id,
                    recipe.name,
                    recipe.zone,
                    json.dumps(recipe.config),
                    recipe.based_on_recipe_id,
                ),
            )

    def update_recipe(
        self,
        recipe_id: str,
        *,
        name: str | None = None,
        zone: str | None = None,
        config: dict | None = None,
    ) -> None:
        fields_sql = ["updated_at = datetime('now')"]
        params: list = []
        if name is not None:
            fields_sql.append("name = ?")
            params.append(name)
        if zone is not None:
            fields_sql.append("zone = ?")
            params.append(zone)
        if config is not None:
            fields_sql.append("config_json = ?")
            params.append(json.dumps(config))
        if len(fields_sql) == 1:
            return
        params.append(recipe_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE augmentation_recipes SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_recipe(self, id_or_name: str) -> AugmentationRecipeRow | None:
        """Lookup by id first, then by name. Returns None if nothing matches."""
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM augmentation_recipes WHERE id = ?", (id_or_name,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM augmentation_recipes WHERE name = ?", (id_or_name,)
            ).fetchone()
        return _row_to_recipe(row) if row else None

    def list_recipes(self, *, zone: str | None = None) -> list[AugmentationRecipeRow]:
        q = "SELECT * FROM augmentation_recipes"
        params: list = []
        if zone is not None:
            q += " WHERE zone = ?"
            params.append(zone)
        q += " ORDER BY created_at DESC"
        return [
            _row_to_recipe(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def delete_recipe(self, recipe_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM augmentation_recipes WHERE id = ?", (recipe_id,)
            )
            return cur.rowcount > 0

    # ─── Augmentation runs (preview) ─────────────────────────────────────

    def create_aug_run(self, run: AugmentationRunRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO augmentation_runs (
                  id, recipe_id, eurio_id, design_group_id,
                  count, seed, output_dir, status, duration_ms, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.recipe_id,
                    run.eurio_id,
                    run.design_group_id,
                    run.count,
                    run.seed,
                    run.output_dir,
                    run.status,
                    run.duration_ms,
                    run.error,
                ),
            )

    def update_aug_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        fields_sql: list[str] = []
        params: list = []
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if duration_ms is not None:
            fields_sql.append("duration_ms = ?")
            params.append(duration_ms)
        if error is not None:
            fields_sql.append("error = ?")
            params.append(error)
        if not fields_sql:
            return
        params.append(run_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE augmentation_runs SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_aug_run(self, run_id: str) -> AugmentationRunRow | None:
        row = self._connection().execute(
            "SELECT * FROM augmentation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_aug_run(row) if row else None

    def prune_aug_runs_older_than(self, *, seconds: int) -> list[AugmentationRunRow]:
        """Return (and delete) aug_runs older than ``seconds`` — caller is
        responsible for deleting the on-disk output_dir.

        The comparison is inclusive (``<=``) so that ``seconds=0`` drains all
        existing rows, matching the "expire everything" intent.
        """
        cutoff_sql = f"datetime('now', '-{int(seconds)} seconds')"
        with self._writing() as c:
            rows = c.execute(
                f"SELECT * FROM augmentation_runs WHERE created_at <= {cutoff_sql}"
            ).fetchall()
            c.execute(
                f"DELETE FROM augmentation_runs WHERE created_at <= {cutoff_sql}"
            )
            return [_row_to_aug_run(r) for r in rows]
