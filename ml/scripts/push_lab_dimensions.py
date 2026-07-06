"""Backfill des dimensions lab locales → canonique VPS (F09).

Pousse TOUTES les cohortes locales (``POST /ingest/cohort``) PUIS toutes les
itérations (``PUT /iterations/{id}``) — ordre parent→enfant garanti (FK
``cohort_id``, ``foreign_keys=ON`` au VPS). Idempotent : chaque push est un
upsert par ``id`` (last-writer-wins), relancer ne duplique rien. Rattrape
l'historique pré-F09 et tout trou laissé par un push best-effort raté.

Le payload itération est LE MÊME que celui du push runner
(``iteration_runner._sync_canonical``) : construit par
``serving.iteration_summary.build_iteration_push_payload`` (``created_on`` =
cette machine + ``summary`` dénormalisé).

Usage :
    .venv/bin/python -m scripts.push_lab_dimensions          # pousse tout
    .venv/bin/python -m scripts.push_lab_dimensions --dry    # liste sans pousser
    go-task ml:lab:push-dimensions [-- --dry]

Exige ``EURIO_API_URL`` pointant un canonique DISTANT (+ ``EURIO_API_TOKEN``).
DB source : ``EURIO_DB_PATH`` ou ``ml/state/eurio.db`` (lecture seule).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.push_lab_dimensions", description=__doc__,
    )
    parser.add_argument(
        "--dry", action="store_true",
        help="Liste ce qui serait poussé sans appeler le canonique.",
    )
    args = parser.parse_args(argv)

    from client import http as api_http
    from client import ingest as api_ingest
    from serving.iteration_summary import build_iteration_push_payload
    from store import Store, resolve_db_path

    if not api_http.remote_sync_enabled():
        raise SystemExit(
            "EURIO_API_URL ne pointe pas un canonique distant — rien à pousser.\n"
            "Exporte EURIO_API_URL=https://eurio-api.musubi.dev (+ EURIO_API_TOKEN) "
            "puis relance."
        )

    store = Store(resolve_db_path(ML_DIR / "state" / "eurio.db"), read_only=True)
    cohorts = store.list_cohorts()
    iterations = store.list_iterations()

    pushed = failed = skipped = 0

    # 1) Cohortes D'ABORD (parent FK des itérations côté canonique).
    for cohort in cohorts:
        if args.dry:
            print(f"[dry] cohort    {cohort.id}  {cohort.name}")
            skipped += 1
            continue
        try:
            api_ingest.push_cohort(cohort.to_dict())
            print(f"[ok]  cohort    {cohort.id}  {cohort.name}")
            pushed += 1
        except Exception as exc:  # noqa: BLE001 — on continue, rapport final
            print(f"[ERR] cohort    {cohort.id}  {cohort.name}: {exc}", file=sys.stderr)
            failed += 1

    # 2) Itérations ensuite (même payload que le push runner).
    for it in iterations:
        if args.dry:
            print(f"[dry] iteration {it.id}  {it.name} ({it.status})")
            skipped += 1
            continue
        try:
            payload = build_iteration_push_payload(store, it)
            api_http.put_json(f"/iterations/{it.id}", payload, timeout=15)
            print(f"[ok]  iteration {it.id}  {it.name} ({it.status})")
            pushed += 1
        except Exception as exc:  # noqa: BLE001 — on continue, rapport final
            print(f"[ERR] iteration {it.id}  {it.name}: {exc}", file=sys.stderr)
            failed += 1

    print(
        f"\n{len(cohorts)} cohorte(s), {len(iterations)} itération(s) — "
        f"pushed={pushed} failed={failed} skipped={skipped}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
