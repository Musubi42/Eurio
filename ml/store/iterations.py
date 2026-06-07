"""Store — domaine iterations (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .common import _optional_column


@dataclass
class ExperimentIterationRow:
    id: str
    cohort_id: str
    name: str
    status: str = "pending"
    parent_iteration_id: str | None = None
    hypothesis: str | None = None
    recipe_id: str | None = None
    variant_count: int = 100
    training_config: dict = field(default_factory=dict)
    training_run_id: str | None = None
    benchmark_run_id: str | None = None
    verdict: str | None = None
    verdict_override: str | None = None
    delta_vs_parent: dict = field(default_factory=dict)
    diff_from_parent: dict = field(default_factory=dict)
    notes: str | None = None
    error: str | None = None
    augmentations_seed: int | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cohort_id": self.cohort_id,
            "parent_iteration_id": self.parent_iteration_id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "recipe_id": self.recipe_id,
            "variant_count": self.variant_count,
            "training_config": self.training_config,
            "status": self.status,
            "training_run_id": self.training_run_id,
            "benchmark_run_id": self.benchmark_run_id,
            "verdict": self.verdict,
            "verdict_override": self.verdict_override,
            "delta_vs_parent": self.delta_vs_parent,
            "diff_from_parent": self.diff_from_parent,
            "notes": self.notes,
            "error": self.error,
            "augmentations_seed": self.augmentations_seed,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class AugVsRealRow:
    iteration_id: str
    eurio_id: str
    num_real: int
    num_aug: int
    cosine: float
    dino_version: str
    computed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "iteration_id": self.iteration_id,
            "eurio_id": self.eurio_id,
            "num_real": self.num_real,
            "num_aug": self.num_aug,
            "cosine": self.cosine,
            "distance": 1.0 - self.cosine,
            "dino_version": self.dino_version,
            "computed_at": self.computed_at,
        }


@dataclass
class IterationLiveTestRow:
    iteration_id: str
    test_idx: int
    expected_eurio_id: str
    condition: str
    predicted_top3: list[dict]
    predicted_top1: str | None
    similarity_top1: float | None
    is_correct: bool
    error: str | None
    ts: str
    synced_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "iteration_id": self.iteration_id,
            "test_idx": self.test_idx,
            "expected_eurio_id": self.expected_eurio_id,
            "condition": self.condition,
            "predicted_top3": self.predicted_top3,
            "predicted_top1": self.predicted_top1,
            "similarity_top1": self.similarity_top1,
            "is_correct": self.is_correct,
            "error": self.error,
            "ts": self.ts,
            "synced_at": self.synced_at,
        }


def _row_to_iteration(r: sqlite3.Row) -> ExperimentIterationRow:
    seed_raw = _optional_column(r, "augmentations_seed")
    seed = int(seed_raw) if seed_raw is not None else None
    return ExperimentIterationRow(
        id=r["id"],
        cohort_id=r["cohort_id"],
        parent_iteration_id=r["parent_iteration_id"],
        name=r["name"],
        hypothesis=r["hypothesis"],
        recipe_id=r["recipe_id"],
        variant_count=r["variant_count"],
        training_config=json.loads(r["training_config_json"]),
        status=r["status"],
        training_run_id=r["training_run_id"],
        benchmark_run_id=r["benchmark_run_id"],
        verdict=r["verdict"],
        verdict_override=r["verdict_override"],
        delta_vs_parent=json.loads(r["delta_vs_parent_json"]),
        diff_from_parent=json.loads(r["diff_from_parent_json"]),
        notes=r["notes"],
        error=r["error"],
        augmentations_seed=seed,
        created_at=r["created_at"],
        started_at=r["started_at"],
        finished_at=r["finished_at"],
    )


class IterationsMixin:

    # ─── Experiment iterations ───────────────────────────────────────────

    def create_iteration(self, iteration: ExperimentIterationRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO experiment_iterations (
                  id, cohort_id, parent_iteration_id, name, hypothesis,
                  recipe_id, variant_count, training_config_json,
                  status, training_run_id, benchmark_run_id,
                  verdict, verdict_override,
                  delta_vs_parent_json, diff_from_parent_json,
                  notes, error, augmentations_seed, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iteration.id,
                    iteration.cohort_id,
                    iteration.parent_iteration_id,
                    iteration.name,
                    iteration.hypothesis,
                    iteration.recipe_id,
                    iteration.variant_count,
                    json.dumps(iteration.training_config),
                    iteration.status,
                    iteration.training_run_id,
                    iteration.benchmark_run_id,
                    iteration.verdict,
                    iteration.verdict_override,
                    json.dumps(iteration.delta_vs_parent),
                    json.dumps(iteration.diff_from_parent),
                    iteration.notes,
                    iteration.error,
                    iteration.augmentations_seed,
                    iteration.started_at,
                    iteration.finished_at,
                ),
            )

    def update_iteration(
        self,
        iteration_id: str,
        *,
        status: str | None = None,
        training_run_id: str | None = None,
        benchmark_run_id: str | None = None,
        verdict: str | None = None,
        verdict_override: str | None = None,
        delta_vs_parent: dict | None = None,
        diff_from_parent: dict | None = None,
        notes: str | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        recipe_id: str | None = None,
        variant_count: int | None = None,
    ) -> None:
        fields_sql: list[str] = []
        params: list = []
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if training_run_id is not None:
            fields_sql.append("training_run_id = ?")
            params.append(training_run_id)
        if benchmark_run_id is not None:
            fields_sql.append("benchmark_run_id = ?")
            params.append(benchmark_run_id)
        if verdict is not None:
            fields_sql.append("verdict = ?")
            params.append(verdict)
        if verdict_override is not None:
            fields_sql.append("verdict_override = ?")
            params.append(verdict_override)
        if delta_vs_parent is not None:
            fields_sql.append("delta_vs_parent_json = ?")
            params.append(json.dumps(delta_vs_parent))
        if diff_from_parent is not None:
            fields_sql.append("diff_from_parent_json = ?")
            params.append(json.dumps(diff_from_parent))
        if notes is not None:
            fields_sql.append("notes = ?")
            params.append(notes)
        if error is not None:
            fields_sql.append("error = ?")
            params.append(error)
        if started_at is not None:
            fields_sql.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            fields_sql.append("finished_at = ?")
            params.append(finished_at)
        if recipe_id is not None:
            fields_sql.append("recipe_id = ?")
            params.append(recipe_id or None)
        if variant_count is not None:
            fields_sql.append("variant_count = ?")
            params.append(variant_count)
        if not fields_sql:
            return
        params.append(iteration_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE experiment_iterations SET {', '.join(fields_sql)} "
                f"WHERE id = ?",
                params,
            )

    def get_iteration(self, iteration_id: str) -> ExperimentIterationRow | None:
        row = self._connection().execute(
            "SELECT * FROM experiment_iterations WHERE id = ?", (iteration_id,)
        ).fetchone()
        return _row_to_iteration(row) if row else None

    def list_iterations(
        self,
        *,
        cohort_id: str | None = None,
        status: str | None = None,
    ) -> list[ExperimentIterationRow]:
        clauses: list[str] = []
        params: list = []
        if cohort_id is not None:
            clauses.append("cohort_id = ?")
            params.append(cohort_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        q = "SELECT * FROM experiment_iterations"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_at ASC"
        return [
            _row_to_iteration(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def delete_iteration(self, iteration_id: str) -> bool:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM experiment_iterations WHERE id = ?", (iteration_id,)
            )
            return cur.rowcount > 0

    # ─── Aug ↔ réelles cache (Sprint 2) ──────────────────────────────────

    def upsert_aug_vs_real(self, rows: list[AugVsRealRow]) -> None:
        if not rows:
            return
        with self._writing() as c:
            c.executemany(
                """
                INSERT INTO iteration_aug_vs_real (
                  iteration_id, eurio_id, num_real, num_aug, cosine,
                  dino_version, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(iteration_id, eurio_id) DO UPDATE SET
                  num_real = excluded.num_real,
                  num_aug = excluded.num_aug,
                  cosine = excluded.cosine,
                  dino_version = excluded.dino_version,
                  computed_at = datetime('now')
                """,
                [
                    (
                        r.iteration_id,
                        r.eurio_id,
                        r.num_real,
                        r.num_aug,
                        r.cosine,
                        r.dino_version,
                    )
                    for r in rows
                ],
            )

    def list_aug_vs_real(self, iteration_id: str) -> list[AugVsRealRow]:
        rows = self._connection().execute(
            "SELECT * FROM iteration_aug_vs_real WHERE iteration_id = ? "
            "ORDER BY eurio_id",
            (iteration_id,),
        ).fetchall()
        return [
            AugVsRealRow(
                iteration_id=r["iteration_id"],
                eurio_id=r["eurio_id"],
                num_real=r["num_real"],
                num_aug=r["num_aug"],
                cosine=r["cosine"],
                dino_version=r["dino_version"],
                computed_at=r["computed_at"],
            )
            for r in rows
        ]

    def clear_aug_vs_real(self, iteration_id: str) -> int:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM iteration_aug_vs_real WHERE iteration_id = ?",
                (iteration_id,),
            )
            return cur.rowcount

    # ─── Live tests (Sprint 4) ───────────────────────────────────────────

    def upsert_live_test(self, row: IterationLiveTestRow) -> bool:
        """Insert one parsed JSONL line, return True if inserted, False on dupe.

        Dupe detection is structural: a row already exists for
        ``(iteration_id, test_idx)``. The route uses the boolean to count
        ``inserted`` vs ``skipped_dupe`` for resync idempotency.
        """
        with self._writing() as c:
            existing = c.execute(
                "SELECT 1 FROM iteration_live_tests "
                "WHERE iteration_id = ? AND test_idx = ?",
                (row.iteration_id, row.test_idx),
            ).fetchone()
            if existing is not None:
                return False
            c.execute(
                """
                INSERT INTO iteration_live_tests (
                  iteration_id, test_idx, expected_eurio_id, condition,
                  predicted_top3_json, predicted_top1, similarity_top1,
                  is_correct, error, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.iteration_id,
                    row.test_idx,
                    row.expected_eurio_id,
                    row.condition,
                    json.dumps(row.predicted_top3),
                    row.predicted_top1,
                    row.similarity_top1,
                    1 if row.is_correct else 0,
                    row.error,
                    row.ts,
                ),
            )
            return True

    def list_live_tests(self, iteration_id: str) -> list[IterationLiveTestRow]:
        rows = self._connection().execute(
            "SELECT * FROM iteration_live_tests WHERE iteration_id = ? "
            "ORDER BY test_idx",
            (iteration_id,),
        ).fetchall()
        return [
            IterationLiveTestRow(
                iteration_id=r["iteration_id"],
                test_idx=r["test_idx"],
                expected_eurio_id=r["expected_eurio_id"],
                condition=r["condition"],
                predicted_top3=json.loads(r["predicted_top3_json"]),
                predicted_top1=r["predicted_top1"],
                similarity_top1=r["similarity_top1"],
                is_correct=bool(r["is_correct"]),
                error=r["error"],
                ts=r["ts"],
                synced_at=r["synced_at"],
            )
            for r in rows
        ]

    def clear_live_tests(self, iteration_id: str) -> int:
        with self._writing() as c:
            cur = c.execute(
                "DELETE FROM iteration_live_tests WHERE iteration_id = ?",
                (iteration_id,),
            )
            return cur.rowcount
