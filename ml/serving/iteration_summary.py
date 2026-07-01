"""Résumé compact d'une itération (recette + métriques) — source unique.

Dénormalise les « chiffres » d'une itération (nom de recette, benchmark, training)
en un dict autonome. Partagé par :
- ``lab_routes._iteration_with_run_metrics`` (réponse API locale), et
- ``iteration_runner._sync_canonical`` (poussé au canonique dans ``summary_json``,
  R3) — pour afficher les chiffres partout SANS transporter les tables lourdes
  ``training_runs`` / ``benchmark_runs``.

Léger : n'utilise que des getters Store (get_recipe / get_benchmark_run / get_run).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # imports type-only — pas de coût runtime
    from store import ExperimentIterationRow, Store


def build_iteration_summary(store: "Store", it: "ExperimentIterationRow") -> dict:
    """``{recipe_name, benchmark_summary, training_summary}`` pour une itération."""
    recipe_name: str | None = None
    if it.recipe_id:
        recipe = store.get_recipe(it.recipe_id)
        recipe_name = recipe.name if recipe else None

    benchmark_summary: dict | None = None
    if it.benchmark_run_id:
        bench = store.get_benchmark_run(it.benchmark_run_id)
        if bench is not None:
            benchmark_summary = {
                "id": bench.id,
                "status": bench.status,
                "r_at_1": bench.r_at_1,
                "r_at_3": bench.r_at_3,
                "r_at_5": bench.r_at_5,
                "mean_spread": bench.mean_spread,
                "num_photos": bench.num_photos,
                "num_coins": bench.num_coins,
                "per_zone": bench.per_zone,
            }

    training_summary: dict | None = None
    if it.training_run_id:
        run = store.get_run(it.training_run_id)
        if run is not None:
            training_summary = {
                "id": run.id,
                "version": run.version,
                "status": run.status,
                "recall_at_1": run.recall_at_1,
                "error": run.error,
            }

    return {
        "recipe_name": recipe_name,
        "benchmark_summary": benchmark_summary,
        "training_summary": training_summary,
    }
