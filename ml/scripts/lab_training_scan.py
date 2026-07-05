"""lab_training_scan.py — scan Dino du Jeu d'entraînement d'une cohorte (P1+P2).

Driver CLI de ``training/training_set_scan.py`` : intrus closed-set + passe de
face sur les crops éligibles. Deux modes :

- **Détaché** (appelé par ``POST /lab/cohorts/{id}/training-scan``) : l'endpoint
  a déjà ouvert la row ``cohort_training_scans`` (--scan-id) ; ici on déroule la
  boucle et on clôt (done/failed) — l'état se lit au poll, survit au --reload.
- **Standalone** (opérateur) : sans ``--scan-id``, ouvre lui-même le scan.
  ``--stats`` imprime la distribution des marges à la fin (calibration du seuil).

Écritures : ``image_assets.face`` (NULL/'unknown' seulement, P2) + les tables de
scan. AUCUNE écriture sur ``training_eligible`` / ``eurio_id`` — le verdict
intrus est une SUGGESTION, l'humain tranche dans le Jeu d'entraînement.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/lab_training_scan.py --cohort b0299ca0252b --stats
  .venv/bin/python scripts/lab_training_scan.py --cohort <id> --scan-id <sid>  # mode endpoint
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cohort", required=True, help="id de la cohorte")
    p.add_argument("--scan-id", default=None,
                   help="scan déjà ouvert par l'endpoint (mode détaché)")
    p.add_argument("--margin", type=float, default=None,
                   help="seuil de marge intrus (défaut: DEFAULT_INTRUDER_MARGIN)")
    p.add_argument("--stats", action="store_true",
                   help="imprime la distribution des marges (calibration)")
    args = p.parse_args()

    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from store import (
        Store,
        latest_training_scan,
        local_state_store,
        resolve_db_path,
        training_scan_finish,
        training_scan_start,
    )
    from training.training_set_scan import (
        DEFAULT_INTRUDER_MARGIN,
        run_training_set_scan,
        scan_scope_count,
    )
    from training.foundation import (
        SUGGESTIONS_ANCHORS_KIND,
        SUGGESTIONS_ENCODER_VERSION,
    )

    store = Store(resolve_db_path(ML_DIR / "state" / "eurio.db"))
    conn = store._connection()  # noqa: SLF001 — canonique (scan work via run_training_set_scan)
    lconn = local_state_store()._connection()  # noqa: SLF001 — cohort_training_scans = local
    margin = args.margin if args.margin is not None else DEFAULT_INTRUDER_MARGIN

    scan_id = args.scan_id
    if scan_id is None:
        cohort = store.get_cohort(args.cohort)
        if cohort is None:
            print(f"Cohort introuvable : {args.cohort}", file=sys.stderr)
            return 1
        scan_id = training_scan_start(
            lconn,
            cohort_id=args.cohort,
            anchors_kind=SUGGESTIONS_ANCHORS_KIND,
            encoder_version=SUGGESTIONS_ENCODER_VERSION,
            intruder_margin=margin,
            n_total=scan_scope_count(store, cohort),
        )
        print(f"scan ouvert : {scan_id}")

    try:
        summary = run_training_set_scan(
            store, args.cohort, scan_id, intruder_margin=margin,
        )
    except Exception as exc:  # noqa: BLE001 — clôture failed visible in-row
        training_scan_finish(lconn, scan_id, status="failed", error=str(exc))
        raise

    print(
        f"scan {scan_id}: {summary.n_done} crops · "
        f"{summary.n_intruders} intrus (marge ≥ {margin}) · "
        f"{summary.n_faces_written} faces écrites · {summary.n_skipped} skips"
    )

    if args.stats:
        rows = lconn.execute(
            "SELECT assigned_class, top1_class, margin, is_intruder "
            "FROM cohort_training_scan_results WHERE scan_id=? "
            "AND margin IS NOT NULL ORDER BY margin DESC",
            (scan_id,),
        ).fetchall()
        disagree = [r for r in rows if r["top1_class"] != r["assigned_class"]]
        print(f"\n{len(rows)} jugés · {len(disagree)} en désaccord top-1 :")
        for r in disagree[:30]:
            flag = " ⟵ INTRUS" if r["is_intruder"] else ""
            print(f"  {r['assigned_class']:>40} → {r['top1_class']:<40} "
                  f"marge {r['margin']:+.4f}{flag}")
        row = latest_training_scan(lconn, args.cohort)
        if row is not None:
            print(f"\nstatus final : {row['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
