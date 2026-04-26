"""Pure functions that power the Lab's interpretation layer.

Split from ``iteration_runner.py`` so the logic is testable without spinning
up the store/runner plumbing. No I/O here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Thresholds in points of R@1 (0.0–1.0 scale).
SIGNIFICANT_DELTA = 0.02      # ±2pts = a real move
NOISE_BAND = 0.005            # ≤0.5pt = no_change
ZONE_REGRESSION_THRESHOLD = 0.03  # -3pts on any zone pollutes a "better" verdict


# ─── Verdict ────────────────────────────────────────────────────────────────


def compute_verdict(
    iteration_metrics: dict,
    parent_metrics: dict | None,
) -> str:
    """Return one of: baseline / better / worse / mixed / no_change.

    ``iteration_metrics`` / ``parent_metrics`` expect the shape persisted on
    ``benchmark_runs`` :
    ``{r_at_1, r_at_3, r_at_5, per_zone: {zone: {r_at_1, ...}, ...}}``.
    """
    if parent_metrics is None:
        return "baseline"
    r1 = iteration_metrics.get("r_at_1")
    r1_parent = parent_metrics.get("r_at_1")
    if r1 is None or r1_parent is None:
        return "pending"

    delta_global = r1 - r1_parent
    zone_deltas = _per_zone_delta_r1(iteration_metrics, parent_metrics)

    zone_values = list(zone_deltas.values())
    any_regression = any(d <= -ZONE_REGRESSION_THRESHOLD for d in zone_values)
    any_improvement = any(d >= SIGNIFICANT_DELTA for d in zone_values)

    if abs(delta_global) < NOISE_BAND and not any_regression and not any_improvement:
        return "no_change"

    if delta_global >= SIGNIFICANT_DELTA:
        if any_regression:
            return "mixed"
        return "better"

    if delta_global <= -SIGNIFICANT_DELTA:
        return "worse"

    # Middle band: 0.5pt < |Δ| < 2pts. If the zones disagree strongly, call it
    # mixed; otherwise no_change.
    if any_regression or any_improvement:
        return "mixed"
    return "no_change"


def _per_zone_delta_r1(iter_m: dict, parent_m: dict) -> dict[str, float]:
    iter_z = iter_m.get("per_zone", {}) or {}
    parent_z = parent_m.get("per_zone", {}) or {}
    common = set(iter_z) & set(parent_z)
    out: dict[str, float] = {}
    for z in common:
        a = (iter_z[z] or {}).get("r_at_1")
        b = (parent_z[z] or {}).get("r_at_1")
        if a is None or b is None:
            continue
        out[z] = float(a) - float(b)
    return out


# ─── Delta computation (full diff between two benchmark rows) ──────────────


def compute_delta(
    iter_metrics: dict,
    parent_metrics: dict | None,
) -> dict:
    """Return a rich diff for surfacing in the UI.

    Shape:
    ```
    {
      "r_at_1": 0.032,
      "r_at_3": 0.011,
      "r_at_5": 0.0,
      "per_zone": {"green": 0.02, "red": 0.05},
      "per_coin": {"fr-2007": 0.125, ...}
    }
    ```

    When ``parent_metrics`` is ``None``, returns ``{}`` — the baseline has
    nothing to compare against.
    """
    if parent_metrics is None:
        return {}
    out: dict[str, Any] = {}
    for key in ("r_at_1", "r_at_3", "r_at_5"):
        a = iter_metrics.get(key)
        b = parent_metrics.get(key)
        if a is not None and b is not None:
            out[key] = round(float(a) - float(b), 6)
    out["per_zone"] = {
        z: round(d, 6) for z, d in _per_zone_delta_r1(iter_metrics, parent_metrics).items()
    }
    iter_coins = {c["eurio_id"]: c for c in iter_metrics.get("per_coin", [])}
    parent_coins = {c["eurio_id"]: c for c in parent_metrics.get("per_coin", [])}
    common_coins = set(iter_coins) & set(parent_coins)
    out["per_coin"] = {
        eid: round(
            float(iter_coins[eid]["r_at_1"]) - float(parent_coins[eid]["r_at_1"]),
            6,
        )
        for eid in common_coins
    }
    return out


# ─── Input diff (what changed between two iterations' inputs) ──────────────


def compute_input_diff(iter_inputs: dict, parent_inputs: dict | None) -> dict:
    """Return the subset of input paths that changed, with before/after.

    Inputs shape (both iter and parent):
    ```
    {
      "recipe": {...config...},   # can be None
      "variant_count": 100,
      "training_config": {...},
    }
    ```

    Output shape:
    ```
    {
      "variant_count": { "before": 100, "after": 200 },
      "recipe.layers[0].max_tilt_degrees": { "before": 15, "after": 25 },
      "training_config.epochs": { "before": 40, "after": 60 }
    }
    ```

    Recipe is flattened using a simple path notation so the UI can display
    per-parameter deltas in the sensitivity panel.
    """
    if parent_inputs is None:
        return {}
    out: dict[str, dict] = {}

    # Scalar inputs
    for key in ("variant_count",):
        a = iter_inputs.get(key)
        b = parent_inputs.get(key)
        if a != b:
            out[key] = {"before": b, "after": a}

    # Training config (flat dict)
    for key in sorted(set(iter_inputs.get("training_config", {}) or {})
                      | set(parent_inputs.get("training_config", {}) or {})):
        a = (iter_inputs.get("training_config") or {}).get(key)
        b = (parent_inputs.get("training_config") or {}).get(key)
        if a != b:
            out[f"training_config.{key}"] = {"before": b, "after": a}

    # Recipe — compare layer-by-layer since layers are the unit of meaning.
    recipe_a = iter_inputs.get("recipe") or {}
    recipe_b = parent_inputs.get("recipe") or {}
    layers_a = {l.get("type"): l for l in (recipe_a.get("layers") or [])}
    layers_b = {l.get("type"): l for l in (recipe_b.get("layers") or [])}
    for layer_type in sorted(set(layers_a) | set(layers_b)):
        la = layers_a.get(layer_type) or {}
        lb = layers_b.get(layer_type) or {}
        for param in sorted(set(la) | set(lb)):
            if param == "type":
                continue
            a = la.get(param)
            b = lb.get(param)
            if a != b:
                out[f"recipe.{layer_type}.{param}"] = {"before": b, "after": a}

    return out


# ─── Sensitivity (aggregate across iterations) ─────────────────────────────


@dataclass
class SensitivityEntry:
    path: str
    observations: int       # nb of iterations where this param changed
    avg_delta_r1: float     # mean of (iter.r_at_1 - parent.r_at_1) across those
    direction: str          # "+" / "-" / "="

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "observations": self.observations,
            "avg_delta_r1": round(self.avg_delta_r1, 6),
            "direction": self.direction,
        }


def compute_sensitivity(
    iterations_with_parents: list[tuple[dict, dict | None, dict, dict | None]],
) -> list[SensitivityEntry]:
    """Aggregate parametric leverage across a cohort's iterations.

    Input: list of ``(iter_inputs, parent_inputs, iter_metrics, parent_metrics)``
    tuples. Only iterations with a parent AND a completed benchmark contribute.

    Returns entries sorted by |avg_delta_r1| descending.
    """
    bucket: dict[str, list[float]] = {}
    for iter_in, parent_in, iter_m, parent_m in iterations_with_parents:
        if parent_in is None or parent_m is None:
            continue
        r1 = iter_m.get("r_at_1")
        r1p = parent_m.get("r_at_1")
        if r1 is None or r1p is None:
            continue
        delta = float(r1) - float(r1p)
        diff = compute_input_diff(iter_in, parent_in)
        for path in diff:
            bucket.setdefault(path, []).append(delta)

    out: list[SensitivityEntry] = []
    for path, deltas in bucket.items():
        avg = sum(deltas) / len(deltas)
        direction = "+" if avg > NOISE_BAND else ("-" if avg < -NOISE_BAND else "=")
        out.append(
            SensitivityEntry(
                path=path,
                observations=len(deltas),
                avg_delta_r1=avg,
                direction=direction,
            )
        )
    out.sort(key=lambda e: abs(e.avg_delta_r1), reverse=True)
    return out
