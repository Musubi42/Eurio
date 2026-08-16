"""Entrée CLI détachée de la chaîne d'itération Lab (refacto-ml chunk 2b-2).

Lancé en subprocess détaché par `IterationRunner.launch_training/launch_benchmark`
via le rail `jobs/` (`start_new_session=True`) → **tout le Lab survit au `--reload`**
du worker API : training (pipeline synchrone ici), export TFLite, benchmark studio,
verdict. Le stdout (toutes les phases) est capté dans le fichier de log du job ;
l'API lit l'avancement via les tables (`experiment_iterations`, `training_runs`,
`benchmark_runs`) + ce log (`IterationRunner.tail_logs`).

Usage :
  python training/run_iteration.py --iteration-id <id> --mode full|benchmark [--job-id <id>]

`mode=full`      → chaîne complète training+export → benchmark (`_run_full_chain`).
`mode=benchmark` → benchmark seul sur une itération déjà `completed` (`_run_benchmark_chain`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store, resolve_db_path  # noqa: E402
from serving.training_runner import TrainingRunner  # noqa: E402
from serving.iteration_runner import IterationRunner  # noqa: E402
import jobs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Detached Lab iteration chain")
    ap.add_argument("--iteration-id", required=True)
    ap.add_argument("--mode", choices=("full", "benchmark"), default="full")
    ap.add_argument("--job-id", default=None)
    args = ap.parse_args()

    store = Store(resolve_db_path(ML_DIR / "state" / "eurio.db"))
    # Le bookkeeping du job va dans la DB LOCALE, la même que celle où le
    # parent a ouvert le job — sinon la progression n'atteindrait jamais
    # l'écran, et sous le flip C5 l'écriture serait refusée (réplique ro).
    conn = jobs.connection()
    runner = IterationRunner(store, TrainingRunner(store))

    try:
        if args.mode == "full":
            runner._run_full_chain(args.iteration_id)  # noqa: SLF001
        else:
            runner._run_benchmark_chain(args.iteration_id)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 — la chaîne gère déjà ses échecs en DB
        if args.job_id:
            jobs.job_finish(conn, args.job_id, status="failed", error=str(exc))
        print(f"ITERATION CHAIN FAILED ({args.iteration_id}): {exc}", file=sys.stderr, flush=True)
        return 1

    # La chaîne s'est terminée proprement (le verdict de l'itération vit dans sa
    # row, indépendamment de l'issue) → le job est `done`. Un process tué en cours
    # (reload) laisse le job `running` → le reaper boot le clôt en `failed`.
    if args.job_id:
        jobs.job_finish(conn, args.job_id, status="done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
