"""CLI ``python -m sources.lmdlp.cli`` — lance le pipeline LMDLP en local.

Équivalent CLI du bouton « Trigger run » de ``/sources/lmdlp`` côté admin.

Exemples :
- ``python -m sources.lmdlp.cli`` — tout le catalogue 2€
- ``python -m sources.lmdlp.cli --country FR``
- ``python -m sources.lmdlp.cli --target fr-2026-2eur-marine-nationale``
- ``python -m sources.lmdlp.cli --dry-run``
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ML_ROOT = Path(__file__).resolve().parents[2]
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", type=str, help="Filtre ISO2 (FR, IT…)")
    parser.add_argument(
        "--target", action="append", default=None,
        help="eurio_id à cibler (répétable). Sans --target : tous les coins matchables.",
    )
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
    from sources.lmdlp import LmdlpAdapter
    from sources.lmdlp.pipeline import run_lmdlp_pipeline
    from store import Store

    store = Store(_ML_ROOT / "state" / "eurio.db")
    adapter = LmdlpAdapter(conn=store._connection())  # noqa: SLF001

    targets = tuple(args.target) if args.target else None
    query = SourceQuery(
        source_id="lmdlp",
        country=args.country,
        target_eurio_ids=targets,
    )

    run_id = run_lmdlp_pipeline(
        adapter, query, store=store, dry_run=args.dry_run, force=args.force,
    )
    print(f"run_id = {run_id}")
    print(f"manifest → ml/state/lmdlp_runs/{run_id}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
