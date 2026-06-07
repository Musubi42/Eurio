"""enqueue_orphan_crops.py — fix T1 : injecte les crops ORPHELINS en review.

Un crop "orphelin" = ``image_state_current.current_state='orphaned'`` = créé
(recrop-zero / run échoué) mais jamais passé par resolve()+enqueue() → resté en
``pending_match``/``needs_review`` SANS ligne ``review_queue`` → invisible à toute
vue de review. Ce script clôture leur pipeline en réutilisant les steps canoniques
``run_resolve`` puis ``run_enqueue`` (mêmes lane/priorité/kind que le pipeline
normal). L'event ``orphaned → queued`` est journalisé par l'emit câblé dans
``run_enqueue``. ADDITIF : ne touche pas les crops déjà résolus/rejetés.

Dry-run par défaut. ``--commit`` écrit. Scopé cohorte par défaut (mix-zone-17),
``--all`` pour tous les orphelins.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/enqueue_orphan_crops.py            # dry-run cohorte
  .venv/bin/python scripts/enqueue_orphan_crops.py --commit   # écrit
  .venv/bin/python scripts/enqueue_orphan_crops.py --all --commit
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="écrit (défaut = dry-run)")
    ap.add_argument("--cohort", default="b0299ca0252b", help="cohorte à scoper")
    ap.add_argument("--all", action="store_true", help="tous les orphelins (ignore --cohort)")
    args = ap.parse_args()

    from store import Store, _register_phash_udfs
    from sources._base.run_logger import start_run
    from sources._base.steps.enqueue import run_enqueue
    from sources._base.steps.resolve import run_resolve

    Store(DB_PATH)  # applique schema.sql
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _register_phash_udfs(conn)

    where, params = "isc.current_state='orphaned'", []
    if not args.all:
        cohort = conn.execute(
            "SELECT eurio_ids_json FROM experiment_cohorts WHERE id=?", (args.cohort,)
        ).fetchone()
        if not cohort:
            print(f"cohorte {args.cohort} introuvable")
            return 1
        import json
        ids = list(json.loads(cohort["eurio_ids_json"]))
        ph = ",".join("?" for _ in ids)
        where += f" AND si.target_eurio_id IN ({ph})"
        params = ids

    rows = conn.execute(
        f"""SELECT DISTINCT si.source_ref AS source_ref, si.id AS sid
              FROM image_state_current isc
              JOIN image_assets ia ON ia.id = isc.asset_id
              JOIN source_images si ON si.id = ia.source_image_id
             WHERE {where}""",
        params,
    ).fetchall()
    n_orphan_crops = conn.execute(
        f"""SELECT COUNT(*) FROM image_state_current isc
              JOIN image_assets ia ON ia.id = isc.asset_id
              JOIN source_images si ON si.id = ia.source_image_id
             WHERE {where}""",
        params,
    ).fetchone()[0]

    sids = {r["source_ref"]: r["sid"] for r in rows}
    scope = "TOUS" if args.all else f"cohorte {args.cohort}"
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[{mode}] fix orphelins ({scope}) : {n_orphan_crops} crops orphelins "
          f"sur {len(sids)} listings → resolve + enqueue")

    if not args.commit:
        print("[DRY-RUN — rien écrit]")
        conn.close()
        return 0

    with start_run(conn, source="ebay", kind="run", force=True,
                   filters={"op": "enqueue_orphans", "cohort": None if args.all else args.cohort}) as run:
        conn.execute("BEGIN")
        try:
            res = run_resolve(conn=conn, run=run, source_id="ebay", source_image_ids=sids)
            enq = run_enqueue(conn=conn, run=run, source_id="ebay", source_image_ids=sids)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            run.end("failed", error_summary="enqueue_orphans")
            raise
        run.end("success")

    print(f"[COMMITTÉ] resolve: {res.n_marked_review} marqués needs_review · "
          f"enqueue: {enq.n_enqueued} review_queue créés ({enq.n_kind_lot} lots)")
    dist = {r["current_state"]: r["n"] for r in conn.execute(
        "SELECT current_state, COUNT(*) n FROM image_state_current GROUP BY 1")}
    print(f"  current global : orphaned={dist.get('orphaned',0)} "
          f"queued={dist.get('queued',0)} (était orphaned≈544)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
