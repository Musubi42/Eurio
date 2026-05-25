"""CLI ``python -m sources.bce.cli`` — lance le pipeline BCE en local.

Équivalent CLI du bouton "Trigger run" de ``/sources/bce`` côté admin.
Pas besoin de booter FastAPI : on instancie Store + adapter directement.

Exemples :
- ``python -m sources.bce.cli`` — toutes les années (2004 → current-1)
- ``python -m sources.bce.cli --year 2024``
- ``python -m sources.bce.cli --target ee-2019-2eur-100-years-...``
- ``python -m sources.bce.cli --dry-run``
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Le module vit dans ml/sources/bce/cli.py ; on remonte 3 niveaux jusqu'à
# ml/ pour que les imports `sources.*` / `state.*` résolvent quand on
# l'invoque via ``python -m sources.bce.cli`` ou direct.
_ML_ROOT = Path(__file__).resolve().parents[2]
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, help="Année unique (sinon : toutes)")
    parser.add_argument(
        "--target", action="append", default=None,
        help="eurio_id à cibler (répétable). Sans --target : tous les coins matchables.",
    )
    parser.add_argument("--country", type=str, help="Filtre ISO2 (IT, FR…)")
    parser.add_argument("--dry-run", action="store_true",
                        help="S'arrête après discover, n'écrit rien.")
    parser.add_argument("--force", action="store_true",
                        help="Ignore l'anti-double-run lock.")
    parser.add_argument("--log", default="INFO",
                        help="Niveau de log Python (DEBUG/INFO/WARNING).")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from sources._base.adapter import SourceQuery
    from sources.bce import BceAdapter
    from sources.bce.pipeline import run_bce_pipeline
    from state import Store

    store = Store(_ML_ROOT / "state" / "eurio.db")
    adapter = BceAdapter(conn=store._connection())  # noqa: SLF001

    targets = tuple(args.target) if args.target else None
    query = SourceQuery(
        source_id="bce",
        year=args.year,
        country=args.country,
        target_eurio_ids=targets,
    )

    run_id = run_bce_pipeline(
        adapter, query, store=store, dry_run=args.dry_run, force=args.force,
    )
    print(f"run_id = {run_id}")
    print(f"manifest → ml/state/bce_runs/{run_id}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
