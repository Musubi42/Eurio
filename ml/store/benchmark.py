"""Store — domaine benchmark (carvé de _domains.py, refacto ML chunk 5b)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .common import _optional_column


@dataclass
class BenchmarkRunRow:
    id: str
    model_path: str
    model_name: str
    training_run_id: str | None = None
    recipe_id: str | None = None
    eurio_ids: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    num_photos: int = 0
    num_coins: int = 0
    r_at_1: float | None = None
    r_at_3: float | None = None
    r_at_5: float | None = None
    mean_spread: float | None = None
    per_zone: dict = field(default_factory=dict)
    per_coin: list[dict] = field(default_factory=list)
    per_condition: dict = field(default_factory=dict)
    confusion: dict = field(default_factory=dict)
    top_confusions: list[dict] = field(default_factory=list)
    report_path: str = ""
    status: str = "running"
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "model_path": self.model_path,
            "model_name": self.model_name,
            "training_run_id": self.training_run_id,
            "recipe_id": self.recipe_id,
            "eurio_ids": self.eurio_ids,
            "zones": self.zones,
            "num_photos": self.num_photos,
            "num_coins": self.num_coins,
            "r_at_1": self.r_at_1,
            "r_at_3": self.r_at_3,
            "r_at_5": self.r_at_5,
            "mean_spread": self.mean_spread,
            "per_zone": self.per_zone,
            "per_coin": self.per_coin,
            "per_condition": self.per_condition,
            "confusion": self.confusion,
            "top_confusions": self.top_confusions,
            "report_path": self.report_path,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _row_to_benchmark_run(r: sqlite3.Row) -> BenchmarkRunRow:
    per_cond_raw = _optional_column(r, "per_condition_json")
    per_condition = json.loads(per_cond_raw) if isinstance(per_cond_raw, str) else {}
    return BenchmarkRunRow(
        id=r["id"],
        model_path=r["model_path"],
        model_name=r["model_name"],
        training_run_id=r["training_run_id"],
        recipe_id=r["recipe_id"],
        eurio_ids=json.loads(r["eurio_ids_json"]),
        zones=json.loads(r["zones_json"]),
        num_photos=r["num_photos"],
        num_coins=r["num_coins"],
        r_at_1=r["r_at_1"],
        r_at_3=r["r_at_3"],
        r_at_5=r["r_at_5"],
        mean_spread=r["mean_spread"],
        per_zone=json.loads(r["per_zone_json"]),
        per_coin=json.loads(r["per_coin_json"]),
        per_condition=per_condition,
        confusion=json.loads(r["confusion_json"]),
        top_confusions=json.loads(r["top_confusions_json"]),
        report_path=r["report_path"],
        status=r["status"],
        error=r["error"],
        started_at=r["started_at"],
        finished_at=r["finished_at"],
    )


class BenchmarkMixin:

    # ─── Benchmark runs ──────────────────────────────────────────────────

    def create_benchmark_run(self, run: BenchmarkRunRow) -> None:
        with self._writing() as c:
            c.execute(
                """
                INSERT INTO benchmark_runs (
                  id, model_path, model_name, training_run_id, recipe_id,
                  eurio_ids_json, zones_json, num_photos, num_coins,
                  r_at_1, r_at_3, r_at_5, mean_spread,
                  per_zone_json, per_coin_json, per_condition_json,
                  confusion_json, top_confusions_json,
                  report_path, status, error, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?)
                """,
                (
                    run.id,
                    run.model_path,
                    run.model_name,
                    run.training_run_id,
                    run.recipe_id,
                    json.dumps(run.eurio_ids),
                    json.dumps(run.zones),
                    run.num_photos,
                    run.num_coins,
                    run.r_at_1,
                    run.r_at_3,
                    run.r_at_5,
                    run.mean_spread,
                    json.dumps(run.per_zone),
                    json.dumps(run.per_coin),
                    json.dumps(run.per_condition),
                    json.dumps(run.confusion),
                    json.dumps(run.top_confusions),
                    run.report_path,
                    run.status,
                    run.error,
                    run.started_at,
                    run.finished_at,
                ),
            )

    def update_benchmark_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        training_run_id: str | None = None,
        num_photos: int | None = None,
        num_coins: int | None = None,
        r_at_1: float | None = None,
        r_at_3: float | None = None,
        r_at_5: float | None = None,
        mean_spread: float | None = None,
        per_zone: dict | None = None,
        per_coin: list[dict] | None = None,
        per_condition: dict | None = None,
        confusion: dict | None = None,
        top_confusions: list[dict] | None = None,
        report_path: str | None = None,
        error: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        fields_sql: list[str] = []
        params: list = []
        if status is not None:
            fields_sql.append("status = ?")
            params.append(status)
        if training_run_id is not None:
            fields_sql.append("training_run_id = ?")
            params.append(training_run_id)
        if num_photos is not None:
            fields_sql.append("num_photos = ?")
            params.append(num_photos)
        if num_coins is not None:
            fields_sql.append("num_coins = ?")
            params.append(num_coins)
        if r_at_1 is not None:
            fields_sql.append("r_at_1 = ?")
            params.append(r_at_1)
        if r_at_3 is not None:
            fields_sql.append("r_at_3 = ?")
            params.append(r_at_3)
        if r_at_5 is not None:
            fields_sql.append("r_at_5 = ?")
            params.append(r_at_5)
        if mean_spread is not None:
            fields_sql.append("mean_spread = ?")
            params.append(mean_spread)
        if per_zone is not None:
            fields_sql.append("per_zone_json = ?")
            params.append(json.dumps(per_zone))
        if per_coin is not None:
            fields_sql.append("per_coin_json = ?")
            params.append(json.dumps(per_coin))
        if per_condition is not None:
            fields_sql.append("per_condition_json = ?")
            params.append(json.dumps(per_condition))
        if confusion is not None:
            fields_sql.append("confusion_json = ?")
            params.append(json.dumps(confusion))
        if top_confusions is not None:
            fields_sql.append("top_confusions_json = ?")
            params.append(json.dumps(top_confusions))
        if report_path is not None:
            fields_sql.append("report_path = ?")
            params.append(report_path)
        if error is not None:
            fields_sql.append("error = ?")
            params.append(error)
        if finished_at is not None:
            fields_sql.append("finished_at = ?")
            params.append(finished_at)
        if not fields_sql:
            return
        params.append(run_id)
        with self._writing() as c:
            c.execute(
                f"UPDATE benchmark_runs SET {', '.join(fields_sql)} WHERE id = ?",
                params,
            )

    def get_benchmark_run(self, run_id: str) -> BenchmarkRunRow | None:
        row = self._connection().execute(
            "SELECT * FROM benchmark_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_benchmark_run(row) if row else None

    def list_benchmark_runs(
        self,
        *,
        model_name: str | None = None,
        recipe_id: str | None = None,
        zone: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BenchmarkRunRow]:
        clauses: list[str] = []
        params: list = []
        if model_name is not None:
            clauses.append("model_name = ?")
            params.append(model_name)
        if recipe_id is not None:
            clauses.append("recipe_id = ?")
            params.append(recipe_id)
        # `zone` filter matches runs whose zones_json contains the zone name;
        # SQLite JSON1 is not guaranteed — we do a LIKE on the serialized list.
        if zone is not None:
            clauses.append("zones_json LIKE ?")
            params.append(f'%"{zone}"%')
        q = "SELECT * FROM benchmark_runs"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [
            _row_to_benchmark_run(r)
            for r in self._connection().execute(q, params).fetchall()
        ]

    def count_benchmark_runs(self) -> int:
        row = self._connection().execute(
            "SELECT COUNT(*) AS n FROM benchmark_runs"
        ).fetchone()
        return int(row["n"])

    def delete_benchmark_run(self, run_id: str) -> BenchmarkRunRow | None:
        with self._writing() as c:
            row = c.execute(
                "SELECT * FROM benchmark_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            c.execute("DELETE FROM benchmark_runs WHERE id = ?", (run_id,))
            return _row_to_benchmark_run(row)
