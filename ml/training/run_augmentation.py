"""Entrée CLI détachée du bake d'augmentations d'une itération (refacto-ml chunk 4).

Lancé en subprocess détaché par les endpoints Lab « Générer / Régénérer » via le
rail `jobs/` → le bake (clear + génération de ~pièces×variants images) **ne bloque
plus la requête HTTP et survit au `--reload`**. L'API renvoie un `job_id` ; le front
poll le statut puis re-fetch la galerie d'augmentations une fois `done`.

Usage : python training/run_augmentation.py --iteration-id <id> --job-id <id> [--clear]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402
import jobs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Detached Lab augmentation bake")
    ap.add_argument("--iteration-id", required=True)
    ap.add_argument("--job-id", default=None)
    ap.add_argument("--clear", action="store_true", help="wipe existing samples first")
    args = ap.parse_args()

    store = Store(ML_DIR / "state" / "eurio.db")
    conn = store._connection()  # noqa: SLF001

    from training.iteration_augmentations import (
        clear_for_iteration,
        generate_for_iteration,
    )

    def _progress(done: int, total: int) -> None:
        # n_total fixé au 1er appel (avant la pièce 0) ; n_done suit.
        if args.job_id:
            conn.execute("UPDATE jobs SET n_total=? WHERE id=?", (total, args.job_id))
            jobs.job_progress(conn, args.job_id, n_done=done)
        print(f"[augment] {done}/{total} pièces", flush=True)

    try:
        if args.clear:
            clear_for_iteration(iteration_id=args.iteration_id, store=store)
        reports = generate_for_iteration(
            iteration_id=args.iteration_id, store=store, on_progress=_progress,
        )
    except Exception as exc:  # noqa: BLE001
        if args.job_id:
            jobs.job_finish(conn, args.job_id, status="failed", error=str(exc))
        print(f"AUGMENTATION BAKE FAILED ({args.iteration_id}): {exc}", file=sys.stderr, flush=True)
        return 1

    written = sum(r.written for r in reports)
    skipped = [r.eurio_id for r in reports if r.skipped_reason]
    note = f"{written} samples, {len(reports)} pièces"
    if skipped:
        note += f", {len(skipped)} skipped"
    if args.job_id:
        jobs.job_progress(conn, args.job_id, n_done=len(reports))
        jobs.job_finish(conn, args.job_id, status="done", note=note)
    print(f"[augment] done — {note}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
