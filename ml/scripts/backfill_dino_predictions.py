"""Backfill DINOv2 predictions for crops that already exist in DB.

Walks `image_assets` (filtered to the V1 scope: parent source_image's
target_eurio_id is a 2€ commemorative coin, crop file present on disk)
and writes one row per crop into `image_asset_dino_predictions` for
the requested ``--kind`` (default ``2eur_commemo``).

Idempotent: skips assets that already have a prediction for the same
``(encoder_version, anchors_kind)``. Pass ``--force`` to recompute
in place.

Usage:
    .venv/bin/python -m scripts.backfill_dino_predictions
    .venv/bin/python -m scripts.backfill_dino_predictions --limit 50
    .venv/bin/python -m scripts.backfill_dino_predictions --force
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sources._base.steps.auto_validate import run_auto_validate_dino_backfill  # noqa: E402
from store import Store, resolve_db_path  # noqa: E402

# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la
# machine lit (`EURIO_DB_PATH` — la réplique sous Direction A, le canonique
# sur le VPS), jamais un chemin codé en dur. Mesuré le 2026-08-19 :
# `state/eurio.db` porte 6205 `image_assets` (5466 prédictions `2eur_all`)
# contre 12454 / 12454 dans `state/eurio.replica.db` — la banque `2eur_all`
# avait été bâtie dessus pendant des semaines.
# Repli hors devShell : `state/eurio.replica.db`. La règle et son arbitrage
# (2026-08-19) sont dans la docstring de `store.resolve_db_path`.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        default="2eur_commemo",
        choices=["2eur_commemo", "2eur_standard", "2eur_all"],
        help="Anchor scope (default: 2eur_commemo).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if a prediction row already exists.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N assets (for smoke / dry runs).",
    )
    parser.add_argument(
        "--db",
        default=None,
        help=f"Fichier SQLite à lire/écrire quand --no-push (défaut : {DB_PATH}, "
             "résolu par store.resolve_db_path — c'est EURIO_DB_PATH quand la "
             "variable est posée, donc la RÉPLIQUE sous Direction A ; "
             "ml/state/eurio.replica.db n'est que le repli hors devShell). "
             "IGNORÉ quand --push est actif : le backfill pull alors sa propre "
             "réplique scratch depuis le VPS.",
    )
    parser.add_argument(
        "--push", action=argparse.BooleanOptionalAction, default=None,
        help="Backfill sur une réplique fraîche (pull depuis le VPS) puis POST "
             "les prédictions au canonique via /ingest/run. Défaut : ACTIVÉ si "
             "EURIO_API_URL est configurée (Direction A — un backfill local "
             "seul ferait diverger la machine du canonique), désactivé sinon "
             "(dev Model A). --no-push force l'écriture locale seule.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    for name in ("training.foundation", "sources._base.steps.auto_validate"):
        logging.getLogger(name).setLevel(logging.INFO)

    # Direction A (C4d) : push par défaut dès que la sync est configurée —
    # même bascule que l'orchestrateur C4c (_maybe_push_run). --no-push est
    # l'échappatoire explicite (dev Model A).
    from client.http import sync_enabled
    push = sync_enabled() if args.push is None else args.push

    if push and args.db is not None:
        # Panne muette évitée : sous --push le fichier passé n'est JAMAIS ouvert
        # (on pull une réplique scratch). Sans ce message l'opérateur croirait
        # avoir choisi la base.
        logging.getLogger("backfill_dino_predictions").warning(
            "--db %s IGNORÉ : --push est actif, le backfill travaille sur une "
            "réplique scratch pull-ée du canonique. Utiliser --no-push pour "
            "travailler sur ce fichier.", args.db,
        )

    if push:
        import tempfile

        from client.replica import pull_replica
        # dest DÉDIÉ : ne PAS écrire dans le cache réplique de la machine
        # (`eurio.replica.db`, alimenté par le thread autopull) — on pull dans
        # un scratch jetable propre à ce backfill pour éviter la course.
        scratch = Path(tempfile.mkdtemp(prefix="dino-backfill-")) / "dino_scratch.db"
        db_path = pull_replica(dest=scratch)
        print(f"[model-b] réplique scratch → {db_path}")
        # read_only=False explicite : cette réplique pull-ée est un SCRATCH de
        # travail (stub source_runs + prédictions y sont écrits avant push_run),
        # pas le cache réplique de la machine — elle doit rester inscriptible
        # même sous EURIO_DB_READONLY (C5).
        store = Store(db_path, read_only=False)
    else:
        db_path = Path(args.db) if args.db else DB_PATH
        print(f"[model-a] base locale → {db_path}")
        store = Store(db_path)

    # Model B (C6b) : stub source_runs pour CE backfill → export_run collecte les
    # prédictions (sur assets préexistants) par run_id. ISO-timestamp = run_id unique.
    from datetime import datetime, timezone
    run_id = f"dino-backfill-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    conn = store._connection()  # noqa: SLF001
    conn.execute(
        "INSERT OR IGNORE INTO source_runs (id, source, kind, status, current_step, filters_json) "
        "VALUES (?, 'dino_backfill', 'reset', 'success', 'auto_validate', ?)",
        (run_id, json.dumps({"anchors_kind": args.kind, "force": args.force})),
    )

    t0 = time.perf_counter()
    result = run_auto_validate_dino_backfill(
        store=store,
        anchors_kind=args.kind,
        force=args.force,
        limit=args.limit,
        run_id=run_id,
    )
    dt = time.perf_counter() - t0

    print()
    print(f"Kind:               {args.kind}")
    print(f"Predicted:          {result.n_predicted}")
    print(f"Skipped (existing): {result.n_skipped_existing}")
    print(f"Skipped (oos):      {result.n_skipped_out_of_scope}")
    print(f"Errors:             {result.n_errors}")
    print(f"Total time:         {dt:.1f}s")
    if result.n_predicted:
        print(f"Per-asset average:  {dt / result.n_predicted * 1000:.1f}ms")

    if push:
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
