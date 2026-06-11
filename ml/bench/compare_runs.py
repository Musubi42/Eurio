"""Rapport comparatif de N configs trigger/seuils sur le même set de sessions.

Usage (depuis ml/) :

    .venv/bin/python -m bench.compare_runs --device Pixel9a \\
        --run original \\
        --run yoloconf:trigger_mode=yolo_confidence,yolo_conf_min=0.45 \\
        --output bench/reports/2026-06-11-trigger-bake-off.md

Chaque ``--run`` est ``nom`` (config enregistrée telle quelle) ou
``nom:clé=val,clé=val`` (overrides BenchConfig rejoués offline). Métriques
par run :

  - latence end-to-end p50/p95 (state_transition FirstDetection → Accepted,
    enregistrée — identique pour tous les runs, rappelée pour contexte) ;
  - latence trigger (t du premier fire − t de la première frame, rejouée) ;
  - best-frame agreement vs ``ground_truth.json`` (sessions annotées) ;
  - gates pass rate moyen ;
  - lock success rate + top-1 accuracy (enregistrés, contexte).

Sortie : tableau Markdown + plots PNG (latences, aggregates retenus) à côté
du rapport.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bench.replay import ReplayResult, replay
from bench.session_io import (
    ML_DIR,
    SESSIONS_ROOT,
    Session,
    iter_session_dirs,
    load_ground_truth,
    load_session,
)


@dataclass
class RunSpec:
    name: str
    overrides: dict[str, Any]


def _parse_run(raw: str) -> RunSpec:
    if ":" not in raw:
        return RunSpec(name=raw, overrides={})
    name, items = raw.split(":", 1)
    overrides: dict[str, Any] = {}
    for item in items.split(","):
        if not item:
            continue
        key, value = item.split("=", 1)
        for cast in (int, float):
            try:
                overrides[key] = cast(value)
                break
            except ValueError:
                continue
        else:
            overrides[key] = (
                value.lower() == "true" if value.lower() in ("true", "false") else value
            )
    return RunSpec(name=name, overrides=overrides)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(int(round(pct / 100 * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def recorded_e2e_latencies(sessions: list[Session]) -> list[float]:
    """FirstDetection → Accepted, en secondes, sur les transitions enregistrées."""
    out = []
    for s in sessions:
        first = next(
            (e["t"] for e in s.state_transitions()
             if e.get("via_event") == "FirstDetection"),
            None,
        )
        accepted = next(
            (e["t"] for e in s.state_transitions() if e.get("to") == "Accepted"),
            None,
        )
        if first is not None and accepted is not None and accepted >= first:
            out.append(accepted - first)
    return out


def lock_success_rate(sessions: list[Session]) -> float | None:
    attempted = [s for s in sessions if s.events_of("lock_state")]
    if not attempted:
        return None
    locked = sum(
        1
        for s in attempted
        if any(e.get("state") == "Locked" for e in s.events_of("lock_state"))
    )
    return locked / len(attempted)


def top1_accuracy(sessions: list[Session]) -> tuple[float | None, int]:
    judged = []
    for s in sessions:
        gt = load_ground_truth(s.path)
        if gt is None or gt.model_top1_correct is None:
            continue
        judged.append(gt.model_top1_correct)
    if not judged:
        return None, 0
    return sum(judged) / len(judged), len(judged)


@dataclass
class RunMetrics:
    spec: RunSpec
    trigger_latencies_s: list[float]
    agreements: list[bool]
    gates_rates: list[float]
    selected_aggregates: list[float]
    n_no_fire: int

    def row(self) -> dict[str, str]:
        def fmt_lat(p):
            v = _percentile(self.trigger_latencies_s, p)
            return f"{v:.2f}s" if v is not None else "n/a"

        agree = (
            f"{sum(self.agreements) / len(self.agreements):.0%}"
            if self.agreements
            else "n/a"
        )
        gates = (
            f"{statistics.mean(self.gates_rates):.0%}" if self.gates_rates else "n/a"
        )
        return {
            "trigger latency (p50)": fmt_lat(50),
            "trigger latency (p95)": fmt_lat(95),
            "best-frame agreement": agree,
            "gates pass rate (moy)": gates,
            "sessions sans fire": str(self.n_no_fire),
        }


def evaluate_run(spec: RunSpec, sessions: list[Session]) -> RunMetrics:
    latencies: list[float] = []
    agreements: list[bool] = []
    gates: list[float] = []
    aggregates: list[float] = []
    no_fire = 0
    for session in sessions:
        if session.config is None:
            continue
        config = session.config.with_overrides(spec.overrides)
        result: ReplayResult = replay(session, config)
        rate = result.gates_pass_rate()
        if rate is not None:
            gates.append(rate)
        if result.fires:
            first_frame_t = session.frames[0].t if session.frames else None
            if first_frame_t is not None:
                latencies.append(result.fires[0]["t"] - first_frame_t)
            sel = result.fires[0].get("selection")
            if sel:
                aggregates.append(sel["aggregate"])
                gt = load_ground_truth(session.path)
                if gt is not None and gt.human_best_frame_id is not None:
                    agreements.append(sel["frame_id"] == gt.human_best_frame_id)
        else:
            no_fire += 1
    return RunMetrics(
        spec=spec,
        trigger_latencies_s=latencies,
        agreements=agreements,
        gates_rates=gates,
        selected_aggregates=aggregates,
        n_no_fire=no_fire,
    )


def render_markdown(
    runs: list[RunMetrics], sessions: list[Session], plots: list[Path]
) -> str:
    e2e = recorded_e2e_latencies(sessions)
    lock = lock_success_rate(sessions)
    top1, top1_n = top1_accuracy(sessions)

    metric_names = list(runs[0].row().keys()) if runs else []
    lines = [
        "# Bench compare — best-frame-capture",
        "",
        f"Sessions : {len(sessions)} · annotées top-1 : {top1_n}",
        "",
        "## Contexte enregistré (indépendant des runs)",
        "",
        f"- latence end-to-end p50 : "
        + (f"{_percentile(e2e, 50):.2f}s" if e2e else "n/a (aucun Accepted)"),
        f"- latence end-to-end p95 : "
        + (f"{_percentile(e2e, 95):.2f}s" if e2e else "n/a"),
        f"- lock success rate : " + (f"{lock:.0%}" if lock is not None else "n/a"),
        f"- recognition top-1 : " + (f"{top1:.0%}" if top1 is not None else "n/a"),
        "",
        "## Runs rejoués",
        "",
        "| metric | " + " | ".join(r.spec.name for r in runs) + " |",
        "| --- |" + " --- |" * len(runs),
    ]
    for metric in metric_names:
        cells = " | ".join(r.row()[metric] for r in runs)
        lines.append(f"| {metric} | {cells} |")
    lines.append("")
    for run in runs:
        if run.spec.overrides:
            lines.append(f"- `{run.spec.name}` : overrides `{run.spec.overrides}`")
        else:
            lines.append(f"- `{run.spec.name}` : config enregistrée")
    if plots:
        lines.append("")
        lines.append("## Plots")
        lines.append("")
        for p in plots:
            lines.append(f"![{p.stem}]({p.name})")
    lines.append("")
    return "\n".join(lines)


def render_plots(runs: list[RunMetrics], out_dir: Path) -> list[Path]:
    out: list[Path] = []
    latency_data = [
        (r.spec.name, r.trigger_latencies_s) for r in runs if r.trigger_latencies_s
    ]
    if latency_data:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.boxplot(
            [d for _, d in latency_data], tick_labels=[n for n, _ in latency_data]
        )
        ax.set_ylabel("trigger latency (s)")
        ax.set_title("Latence premier fire par run")
        path = out_dir / "latency_box.png"
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        out.append(path)

    agg_data = [
        (r.spec.name, r.selected_aggregates) for r in runs if r.selected_aggregates
    ]
    if agg_data:
        fig, ax = plt.subplots(figsize=(6, 4))
        for name, values in agg_data:
            ax.hist(values, bins=10, alpha=0.5, label=name, range=(0, 1))
        ax.set_xlabel("aggregate de la frame retenue")
        ax.legend()
        ax.set_title("Qualité des frames sélectionnées")
        path = out_dir / "selected_aggregates.png"
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="filtrer par device")
    parser.add_argument("--root", default=str(SESSIONS_ROOT))
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        type=_parse_run,
        metavar="NOM[:clé=val,…]",
    )
    parser.add_argument(
        "--output",
        default=str(ML_DIR / "bench" / "reports" / "compare_runs.md"),
    )
    args = parser.parse_args(argv)

    sessions = [
        load_session(path, device=dev)
        for dev, path in iter_session_dirs(Path(args.root), args.device)
    ]
    if not sessions:
        print("error: aucune session sous "
              f"{args.root}" + (f" (device {args.device})" if args.device else ""),
              file=sys.stderr)
        return 2

    runs = [evaluate_run(spec, sessions) for spec in args.run]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    plots = render_plots(runs, output.parent)
    output.write_text(render_markdown(runs, sessions, plots))

    print(f"OK · rapport {output} (+{len(plots)} plot(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
