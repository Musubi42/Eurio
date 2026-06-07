"""Entrée CLI détachée du pipeline d'entraînement (refacto-ml chunk 2b).

Lancé en subprocess détaché par `TrainingRunner.start_run` via le rail `jobs/`
(`start_new_session=True`) → **survit au `--reload`** du worker API. Tout le
stdout (les 6 étapes + les lignes du training) est capté dans le fichier de log
du job ; l'API lit l'état via la table `training_runs` + la row `jobs` + ce log.

Usage : `python training/run_pipeline.py --run-id <id> [--device auto] [--job-id <id>]`

La `RunRow` (status='queued') + les 6 steps 'pending' ont déjà été créés par
l'appelant. Ce process exécute le pipeline synchroniquement, puis clôt la row
`jobs` (`done`/`failed`) pour le reaper boot.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402
from training.pipeline import TrainingPipeline  # noqa: E402
import jobs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Detached ArcFace training pipeline")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--job-id", default=None)
    args = ap.parse_args()

    store = Store(ML_DIR / "state" / "eurio.db")
    conn = store._connection()  # noqa: SLF001
    pipeline = TrainingPipeline(store, args.run_id, device=args.device)

    try:
        pipeline.run()  # set le run en running→completed/failed + save_logs
    except Exception as exc:  # noqa: BLE001 — run() a déjà marqué le run 'failed'
        if args.job_id:
            jobs.job_finish(conn, args.job_id, status="failed", error=str(exc))
        print(f"PIPELINE FAILED ({args.run_id}): {exc}", file=sys.stderr, flush=True)
        return 1

    if args.job_id:
        jobs.job_finish(conn, args.job_id, status="done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
