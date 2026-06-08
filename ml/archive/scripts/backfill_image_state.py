"""backfill_image_state.py — amorce le modèle d'état explicite des crops.

Chunk C1 du rebuild cockpit (docs/cohort-pipeline/REBUILD-ANALYSIS.md). Peuple
``image_state_current`` (1 ligne/crop) + un event synthétique ``backfill`` dans
``image_state_events`` pour CHAQUE image_assets existant, en dérivant l'état
canonique (9 états) depuis l'existant via un CASE — exactement le mapping de
réconciliation du design. ADDITIF & SÛR (R0) :
- ne touche AUCUNE table cœur (source_images/image_assets/review_queue) ;
- idempotent : ``WHERE NOT EXISTS`` → un 2e run ne re-backfille pas ;
- réversible : ``DELETE FROM image_state_events; DELETE FROM image_state_current``.

Le scoping cockpit se fait par ``target_eurio_id`` (clé de découverte stable),
pas par cohort_id. L'état courant n'est PAS encore alimenté en live par le
pipeline (c'est le chunk C2 : emit_state_event aux call-sites) — ce script ne
fait qu'amorcer la photo de l'état actuel.

Dry-run par défaut (montre la répartition globale + cohorte). ``--commit`` écrit.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/backfill_image_state.py                    # dry-run
  .venv/bin/python scripts/backfill_image_state.py --commit           # écrit
  .venv/bin/python scripts/backfill_image_state.py --cohort b0299ca0252b
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"

# Mapping de réconciliation crop_status × resolution_status × rq.status → état
# canonique. Ordre des WHEN significatif (premier vrai gagne). Identique pour le
# dry-run (agrégat) et le commit (INSERT) → une seule source de vérité.
STATE_CASE = """
  CASE
    WHEN ia.resolution_status = 'rejected'                       THEN 'rejected'
    WHEN ia.resolution_status = 'manual'                         THEN 'resolved'
    WHEN ia.resolution_status IN ('auto_phash','auto_name')      THEN 'auto_matched'
    WHEN rq.status = 'open' AND rq.decision_notes = 'skipped'    THEN 'skipped'
    WHEN rq.status = 'skipped'                                   THEN 'skipped'
    WHEN rq.status = 'in_progress'                               THEN 'in_review'
    WHEN rq.status = 'open'                                      THEN 'queued'
    WHEN ia.resolution_status IN ('pending_match','needs_review')
         AND rq.id IS NULL                                       THEN 'orphaned'
    ELSE 'detected'
  END
"""

_FROM = """
  FROM image_assets ia
  JOIN source_images si ON si.id = ia.source_image_id
  LEFT JOIN review_queue rq ON rq.image_asset_id = ia.id
"""

_STATE_ORDER = [
    "detected", "auto_matched", "queued", "in_review",
    "skipped", "resolved", "rejected", "orphaned", "superseded",
]


def _cohort_eurio_ids(conn: sqlite3.Connection, cohort_id: str) -> list[str]:
    row = conn.execute(
        "SELECT eurio_ids_json FROM experiment_cohorts WHERE id=?", (cohort_id,)
    ).fetchone()
    if not row:
        return []
    return list(json.loads(row[0]))


def _distribution(conn: sqlite3.Connection, eurio_ids: list[str] | None) -> dict[str, int]:
    """Répartition par état canonique calculée à la volée (dry-run)."""
    where, params = "", []
    if eurio_ids:
        ph = ",".join("?" for _ in eurio_ids)
        where = f"WHERE si.target_eurio_id IN ({ph})"
        params = eurio_ids
    sql = f"SELECT {STATE_CASE} AS state, COUNT(*) AS n {_FROM} {where} GROUP BY 1"
    return {r["state"]: r["n"] for r in conn.execute(sql, params)}


def _print_dist(title: str, dist: dict[str, int]) -> None:
    total = sum(dist.values())
    print(f"\n{title} (total {total})")
    print("-" * 40)
    for st in _STATE_ORDER:
        n = dist.get(st, 0)
        flag = "  ← invisibles aujourd'hui" if st == "orphaned" and n else ""
        print(f"  {st:14}{n:>7}{flag}")
    extra = {k: v for k, v in dist.items() if k not in _STATE_ORDER}
    for k, v in extra.items():
        print(f"  {k:14}{v:>7}  ⚠ état hors enum")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="écrit (défaut = dry-run)")
    ap.add_argument("--cohort", default="b0299ca0252b",
                    help="cohorte pour la ventilation d'audit (défaut mix-zone-17)")
    ap.add_argument("--verify", action="store_true",
                    help="détecteur de drift : compare image_state_current à l'état "
                         "re-dérivé du CASE. 0 mismatch = cohérent (toutes les "
                         "transitions live sont journalisées) ; >0 = un site de "
                         "mutation n'appelle pas emit_state_event.")
    args = ap.parse_args()

    # Instancier Store → applique schema.sql (crée image_state_events/current +
    # cohort_jobs en IF NOT EXISTS sur la DB existante). Aucune autre mutation.
    from store import Store
    Store(DB_PATH)

    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row

    if args.verify:
        mism = conn.execute(
            f"""SELECT isc.current_state AS stored, d.state AS derived, COUNT(*) AS n
                  FROM image_state_current isc
                  JOIN (SELECT ia.id AS asset_id, {STATE_CASE} AS state {_FROM}) d
                    ON d.asset_id = isc.asset_id
                 WHERE isc.current_state <> d.state
                 GROUP BY 1, 2 ORDER BY 3 DESC"""
        ).fetchall()
        n_missing = conn.execute(
            "SELECT COUNT(*) FROM image_assets ia WHERE NOT EXISTS "
            "(SELECT 1 FROM image_state_current isc WHERE isc.asset_id=ia.id)"
        ).fetchone()[0]
        total_drift = sum(r["n"] for r in mism)
        print(f"[VERIFY] drift current vs CASE : {total_drift} mismatch · "
              f"{n_missing} crops absents de current")
        for r in mism:
            print(f"  stored={r['stored']:14} derived={r['derived']:14} n={r['n']}")
        if total_drift == 0 and n_missing == 0:
            print("  ✓ cohérent — toutes les transitions sont journalisées")
        conn.close()
        return 0 if (total_drift == 0 and n_missing == 0) else 1

    n_assets = conn.execute("SELECT COUNT(*) FROM image_assets").fetchone()[0]
    n_already = conn.execute("SELECT COUNT(*) FROM image_state_current").fetchone()[0]
    n_todo = conn.execute(
        "SELECT COUNT(*) FROM image_assets ia "
        "WHERE NOT EXISTS (SELECT 1 FROM image_state_current isc WHERE isc.asset_id=ia.id)"
    ).fetchone()[0]

    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[{mode}] backfill modèle d'état")
    print(f"  image_assets total      : {n_assets}")
    print(f"  déjà dans current        : {n_already}")
    print(f"  à amorcer (NOT EXISTS)   : {n_todo}")

    _print_dist("Répartition GLOBALE (état dérivé)", _distribution(conn, None))
    cohort_ids = _cohort_eurio_ids(conn, args.cohort)
    if cohort_ids:
        _print_dist(f"Répartition COHORTE {args.cohort} ({len(cohort_ids)} pièces)",
                    _distribution(conn, cohort_ids))

    if not args.commit:
        print("\n[DRY-RUN — rien écrit]")
        conn.close()
        return 0

    # --- COMMIT : amorçage idempotent ---
    cur = conn.execute(
        f"""INSERT INTO image_state_current
              (asset_id, current_state, eurio_id, target_eurio_id, state_since)
            SELECT ia.id, {STATE_CASE}, ia.eurio_id, si.target_eurio_id,
                   COALESCE(ia.resolved_at, ia.fetched_at)
            {_FROM}
            WHERE NOT EXISTS (SELECT 1 FROM image_state_current isc
                              WHERE isc.asset_id = ia.id)"""
    )
    n_current = cur.rowcount

    cur = conn.execute(
        """INSERT INTO image_state_events
             (asset_id, from_state, to_state, actor, reason,
              eurio_id, target_eurio_id, created_at)
           SELECT isc.asset_id, NULL, isc.current_state, 'system', 'backfill',
                  isc.eurio_id, isc.target_eurio_id, isc.state_since
           FROM image_state_current isc
           WHERE NOT EXISTS (SELECT 1 FROM image_state_events e
                             WHERE e.asset_id = isc.asset_id)"""
    )
    n_events = cur.rowcount

    conn.execute(
        """UPDATE image_state_current
              SET last_event_id = (SELECT MAX(e.id) FROM image_state_events e
                                   WHERE e.asset_id = image_state_current.asset_id),
                  actor = COALESCE(actor, 'system')
            WHERE last_event_id IS NULL"""
    )

    print(f"\n[COMMITTÉ] current +{n_current} lignes · events +{n_events} synthétiques")
    # Vérif post-écriture : current GROUP BY state == ce qu'on a annoncé.
    verify = {r["current_state"]: r["n"] for r in conn.execute(
        "SELECT current_state, COUNT(*) n FROM image_state_current GROUP BY 1")}
    _print_dist("VÉRIF current (post-commit, global)", verify)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
