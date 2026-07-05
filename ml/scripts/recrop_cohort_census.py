"""recrop_cohort_census.py — récupère les zéro-crops d'une cohorte en mode census+gate.

ADDITIF & SÛR (R0) : ne touche QUE les source_images eBay de la cohorte qui n'ont
**aucun** crop présent (`image_assets` storage_status=present = 0) — typiquement les
`crop_status='zero_crops'`. Aucune écriture sur des crops existants / déjà reviewés
(`training_eligible`). Les crops récupérés sont créés en `pending_match`/`auto_phash`,
`training_eligible=0` → ils passent par la review humaine comme tout crop pipeline.

Détection = mode census (`EURIO_CENSUS_DETECT=1`) + gate anti-fragment DINO
(`EURIO_CENSUS_FRAGMENT_TAU`, défaut 0.45) : on ne récupère que des **faces propres**,
pas le flot de fragments (cf. census-detector-design.md §8-9).

Persistance identique au pipeline (`sources/_base/steps/detect_crop.py`) :
crop_key → cache + MinIO (upload_through) → upsert_image_asset + storage_status=present,
dédup phash (Hamming ≤4) pour auto-résoudre l'eurio_id, bbox reconstruite pour la
forensics admin. run_id traçable `census-recover-<cohort>`.

Dry-run par défaut (compte seulement). `--commit` pour écrire.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/recrop_cohort_census.py --cohort b0299ca0252b           # dry
  .venv/bin/python scripts/recrop_cohort_census.py --cohort b0299ca0252b --commit  # écrit
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")


def _run_single_coin_job(
    *, coin: str, job_id: str, run_id: str, tau: float,
    recrop_zero_for_coin, register_udfs, push: bool = False,
) -> int:
    """Exécute UN recrop-zero en mode détaché et clôt son cohort_jobs lui-même.

    Appelé par l'endpoint ``POST …/recrop-zero`` via subprocess (PYTHONPATH=ml).
    Le job a déjà été ouvert (``status='running'``, ``n_total`` posé) par
    l'endpoint ; ici on ne fait qu'avancer ``n_done`` (commit par raw) puis
    ``finish``. Toute exception → ``finish(status='failed', error=…)`` pour qu'un
    crash soit visible in-row (jamais de zombie silencieux). Sortie 0 = OK,
    1 = échec (déjà persisté).

    ``push`` (Direction A / Modèle B) : le bookkeeping du job (``cohort_jobs``
    progress/finish) reste TOUJOURS sur la DB Mac locale (``conn``, état
    opérationnel de la workstation) — seule l'écriture des crops bascule sur
    une réplique pull-ée (``client.replica.pull_replica``) suivie d'un
    ``push_run`` vers le canonique VPS, comme le fait déjà le mode batch
    ``--push`` (sans ``--coin``) plus bas dans ce fichier."""
    from store import cohort_job_finish, cohort_job_progress

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")  # cohabite avec les écritures API
    register_udfs(conn)
    n_total = conn.execute(
        "SELECT n_total FROM cohort_jobs WHERE id=?", (job_id,)
    ).fetchone()
    n_total = (n_total[0] if n_total else 0) or 0

    def _progress(n: int) -> None:
        # Bookkeeping toujours sur la connexion locale (job status), même en
        # mode --push (la connexion de travail des crops, elle, est distincte).
        cohort_job_progress(conn, job_id, n_done=n)
        conn.commit()

    work_conn = conn
    if push:
        from store import staging_store
        # SCRATCH inscriptible dédié (pas le cache autopull `eurio.replica.db` :
        # course avec le pull, et ro sous le flip). Le bookkeeping (cohort_job_*)
        # reste sur `conn` local — cf. précondition flip « split bookkeeping ».
        work_store = staging_store(prefix="eurio-recrop-")
        print(f"[model-b] réplique scratch inscriptible → {work_store.db_path}", flush=True)
        work_conn = work_store._connection()  # noqa: SLF001

    try:
        counts = recrop_zero_for_coin(
            work_conn, coin, run_id=run_id, commit=True, progress_cb=_progress,
        )
        note = None
        if counts["crops"] == 0:
            note = (f"épuisé à τ={tau} — 0 crop récupérable "
                    f"({n_total} raws déjà tentés)")
        if push:
            from client.runbatch import push_run
            res = push_run(work_conn, run_id)
            if res.get("already_applied"):
                print(f"[model-b] push {run_id} → déjà appliqué (no-op)", flush=True)
            else:
                total = sum((res.get("counts") or {}).values())
                print(f"[model-b] push {run_id} → {total} ligne(s) appliquée(s) "
                      "au canonique", flush=True)
        cohort_job_finish(
            conn, job_id, status="done", n_done=n_total or counts["scanned"],
            n_produced=counts["crops"], note=note,
        )
        conn.commit()
        print(f"[recrop-zero] {coin} done: {counts}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 — surfacé via cohort_jobs.error
        cohort_job_finish(conn, job_id, status="failed", error=str(exc))
        conn.commit()
        print(f"[recrop-zero] {coin} crashed: {exc}", flush=True)
        return 1
    finally:
        if push:
            work_conn.close()
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="b0299ca0252b")
    ap.add_argument("--commit", action="store_true", help="écrit (défaut = dry-run)")
    ap.add_argument("--tau", default=None, help="override EURIO_CENSUS_FRAGMENT_TAU")
    ap.add_argument("--limit", type=int, default=0, help="cap raws/classe (0=tous)")
    ap.add_argument("--coin", default=None,
                    help="single eurio_id (mode job arrière-plan de l'endpoint admin)")
    ap.add_argument("--job-id", dest="job_id", default=None,
                    help="cohort_jobs.id à piloter (mode --coin) : ce process "
                         "écrit lui-même progress/finish → survit au --reload")
    ap.add_argument("--run-id", dest="run_id", default=None, help="run_id override")
    ap.add_argument("--push", action="store_true",
                    help="Direction A / Modèle B : recrop (cohorte ou --coin) "
                         "sur une réplique read-only (pull depuis le VPS) puis "
                         "POST le run au canonique via /ingest/run. Implique "
                         "--commit. En mode --coin, le bookkeeping cohort_jobs "
                         "reste sur la DB Mac locale — seule l'écriture des "
                         "crops bascule sur la réplique. Sans ce flag : écrit "
                         "la DB Mac (Modèle A).")
    args = ap.parse_args()

    os.environ["EURIO_CENSUS_DETECT"] = "1"
    if args.tau is not None:
        os.environ["EURIO_CENSUS_FRAGMENT_TAU"] = args.tau

    from vision.normalize_snap import _census_fragment_tau
    from vision.recrop_zero import recrop_zero_for_coin
    from store import _register_phash_udfs

    tau = _census_fragment_tau()   # vraie τ appliquée par le gate (source unique)

    # Mode single-coin : exécution détachée d'UN recrop pour l'endpoint admin.
    # Ce subprocess possède le cycle de vie du cohort_jobs (progress + finish)
    # via sa PROPRE connexion → si le worker --reload meurt, le job se clôt
    # quand même en base (plus de zombie). Commit par raw (progress_cb) =
    # avancement visible + crops déjà committés survivent à un crash.
    if args.coin and args.job_id:
        return _run_single_coin_job(
            coin=args.coin, job_id=args.job_id,
            run_id=args.run_id or f"recrop-zero-{args.coin}", tau=tau,
            recrop_zero_for_coin=recrop_zero_for_coin,
            register_udfs=_register_phash_udfs,
            push=args.push,
        )

    run_id = f"census-recover-{args.cohort}"
    # Model B (C6b) : --push → réplique read-only (FK ON, Store) ; recrop_zero_for_coin
    # stubbe source_runs avant d'écrire les crops (FK satisfaite). Sinon : DB Mac via
    # connexion brute (FK OFF, comportement Modèle A historique).
    commit = args.commit or args.push
    if args.push:
        from store import staging_store
        # SCRATCH inscriptible dédié (pas le cache autopull `eurio.replica.db` :
        # course avec le pull, et ro sous le flip) — même correctif que
        # _run_single_coin_job. Le batch pousse depuis ce scratch via push_run.
        _push_store = staging_store(prefix="eurio-recrop-batch-")
        print(f"[model-b] réplique scratch inscriptible → {_push_store.db_path}")
        conn = _push_store._connection()
    else:
        if commit:
            from store import resolve_db_readonly

            if resolve_db_readonly():
                raise SystemExit(
                    "DB en lecture seule (réplique Direction A) — writer canonique = VPS. "
                    "Poser EURIO_DB_READONLY=0 seulement sur le host canonique."
                )
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        _register_phash_udfs(conn)   # hamming() / phash_match() UDFs (dédup C4)
    row = conn.execute("SELECT eurio_ids_json FROM experiment_cohorts WHERE id = ?",
                       (args.cohort,)).fetchone()
    classes = json.loads(row["eurio_ids_json"]) if row and row["eurio_ids_json"] else []
    mode = "COMMIT" if commit else "DRY-RUN"
    print(f"[{mode}] cohorte {args.cohort} : {len(classes)} classes, τ={tau}, run_id={run_id}\n")

    T = dict(scanned=0, recovered=0, crops=0, auto_phash=0)
    print(f"{'classe':45s}{'cand0':>7}{'récup':>7}{'crops':>7}")
    print("-" * 66)
    for cls in sorted(classes):
        # Cœur partagé avec l'endpoint admin (scan/recrop_zero.py). Commit par
        # classe = transaction courte (évite les locks SQLite avec l'API admin) +
        # reprise propre (le scope additif re-skippe les raws déjà faits).
        c = recrop_zero_for_coin(
            conn, cls, run_id=run_id, commit=commit, limit=args.limit,
        )
        if c["scanned"]:
            print(f"{cls[:45]:45s}{c['scanned']:>7}{c['recovered']:>7}{c['crops']:>7}",
                  flush=True)
        for k in T:
            T[k] += c[k]

    if commit:
        conn.commit()  # no-op sur la connexion Store autocommit (--push)
    print("-" * 66)
    print(f"{'TOTAL':45s}{T['scanned']:>7}{T['recovered']:>7}{T['crops']:>7}")
    print(f"\n{'[COMMITTÉ]' if commit else '[DRY-RUN — rien écrit]'} "
          f"candidats zéro-crop {T['scanned']} → {T['recovered']} raws récupérés, "
          f"+{T['crops']} crops ({T['auto_phash']} auto-phash) → review queue (training_eligible=0)")

    if args.push:
        from client.runbatch import push_run
        res = push_run(conn, run_id)
        if res.get("already_applied"):
            print(f"[model-b] push {run_id} → déjà appliqué (no-op)")
        else:
            total = sum((res.get("counts") or {}).values())
            print(f"[model-b] push {run_id} → {total} ligne(s) appliquée(s) au canonique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
