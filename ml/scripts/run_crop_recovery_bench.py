"""CLI du banc crop-recovery. Cf. docs/work-in-progress/crop-recovery/BENCHMARK.md.

  # 1. construire les jeux (une fois, coûteux)
  .venv/bin/python -m scripts.run_crop_recovery_bench --build --datasets D1,D2,D3a,D3b

  # 2. lancer une stratégie (baseline / ref / la tienne via --import)
  .venv/bin/python -m scripts.run_crop_recovery_bench --strategy baseline
  .venv/bin/python -m scripts.run_crop_recovery_bench --strategy ref:radius_sweep
  .venv/bin/python -m scripts.run_crop_recovery_bench --import strategy_a --strategy "A:score_search"

  # 3. évaluer un hybride sur des runs déjà écrits (sans re-run)
  .venv/bin/python -m scripts.run_crop_recovery_bench --hybrid state/crop_recovery/run_A.json,state/crop_recovery/run_B.json
"""

from __future__ import annotations

import argparse
import importlib


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="construire les jeux")
    ap.add_argument("--datasets", default="D1,D2,D3a,D3b")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--limit-per", type=int, default=None, help="(build) cas max par jeu")
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--import", dest="imports", action="append", default=[],
                    help="module(s) à importer pour enregistrer des stratégies (repeatable)")
    ap.add_argument("--hybrid", default=None, help="chemins JSON de runs, séparés par ,")
    ap.add_argument("--policy", default="argmax")
    args = ap.parse_args()

    # toujours charger les stratégies de référence (baseline, ref:radius_sweep)
    importlib.import_module("bench.crop_recovery.strategies_ref")
    for m in args.imports:
        importlib.import_module(m)

    if args.build:
        from bench.crop_recovery import datasets
        import sys
        sys.argv = ["datasets", "--datasets", args.datasets]
        if args.limit_per:
            sys.argv += ["--limit-per", str(args.limit_per)]
        return datasets.main()

    if args.hybrid:
        from bench.crop_recovery.hybrid import evaluate
        evaluate(args.hybrid.split(","), policy=args.policy)
        return 0

    if args.strategy:
        from bench.crop_recovery.harness import run
        run(args.strategy, args.datasets.split(","), limit=args.limit)
        return 0

    ap.error("rien à faire : --build, --strategy ou --hybrid")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
