"""CLI ``python -m sources.jo.cli`` — ingestion JO (EUR-Lex) en local.

Exemples :
- ``python -m sources.jo.cli --dry-run``         — énumère + parse, n'écrit rien
- ``python -m sources.jo.cli --since 2024``       — notices publiées depuis 2024
- ``python -m sources.jo.cli --country FR``
- ``python -m sources.jo.cli --target fr-2024-2eur-…``
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
    parser.add_argument("--since", type=int, default=2004,
                        help="Année min de publication JO (default: 2004).")
    parser.add_argument("--country", type=str, help="Filtre ISO2 (FR, IT…).")
    parser.add_argument("--target", action="append", default=None,
                        help="eurio_id à cibler (répétable).")
    parser.add_argument("--dry-run", action="store_true",
                        help="S'arrête après discover, n'écrit rien.")
    parser.add_argument("--force", action="store_true", help="Ignore l'anti-double-run.")
    parser.add_argument("--log", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from sources._base.adapter import SourceQuery
    from sources.jo import JoAdapter
    from sources.jo.pipeline import run_jo_pipeline
    from state import Store

    store = Store(_ML_ROOT / "state" / "eurio.db")
    adapter = JoAdapter(conn=store._connection(), since_year=args.since)  # noqa: SLF001

    targets = tuple(args.target) if args.target else None
    query = SourceQuery(
        source_id="jo", country=args.country, target_eurio_ids=targets,
    )
    run_id = run_jo_pipeline(
        adapter, query, store=store, dry_run=args.dry_run, force=args.force,
    )
    print(f"run_id = {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
