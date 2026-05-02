"""CLI entrypoint for the sources orchestrator.

Usage (via Taskfile):
    go-task ml:src:run -- --source mock --limit 5
    go-task ml:src:run -- --source mock --country FR --dry-run

Or directly:
    .venv/bin/python -m sources.cli --source mock --dry-run

The CLI prints the final counters and exits non-zero if the run
ended with status='failed' (so it surfaces in CI / Make-style chains).
A 'partial' run (some items errored, others succeeded) exits 0 — the
counters tell the story.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sources._base.adapter import SourceQuery
from sources._base.orchestrator import run_pipeline
from state.store import Store

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "state" / "training.db"


def _load_adapter(source_id: str):
    if source_id == "mock":
        from sources._mock import MockAdapter
        return MockAdapter()
    raise SystemExit(
        f"Unknown source '{source_id}'. Available: mock. "
        "Real sources (ebay, numista...) will be added as their adapters land."
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sources.cli",
        description="Run the 6-step ingestion pipeline for one source.",
    )
    p.add_argument("--source", required=True, help="Source id (e.g. 'mock', 'ebay').")
    p.add_argument("--dry-run", action="store_true",
                   help="Stop after Discover; write nothing past discovery_log.")
    p.add_argument("--force", action="store_true",
                   help="Override anti-double-run guard.")
    p.add_argument("--country", default=None, help="Filter by ISO-2 country.")
    p.add_argument("--year", type=int, default=None, help="Filter by year.")
    p.add_argument("--denomination", default=None,
                   help="Filter by face value (e.g. '2eur', '0.50').")
    p.add_argument("--target-eurio-id", default=None,
                   help="Pin the fetch to a single eurio_id (raises priority).")
    p.add_argument("--limit", type=int, default=None, help="Cap discovered items.")
    p.add_argument("--db", type=Path, default=_DEFAULT_DB,
                   help=f"Path to the SQLite store (default: {_DEFAULT_DB}).")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG-level logs.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    adapter = _load_adapter(args.source)
    query = SourceQuery(
        source_id=args.source,
        country=args.country,
        denomination=args.denomination,
        year=args.year,
        target_eurio_id=args.target_eurio_id,
        limit=args.limit,
    )

    store = Store(args.db)
    run_id = run_pipeline(adapter, query, store=store, dry_run=args.dry_run, force=args.force)

    row = store._connection().execute(
        "SELECT status, current_step, n_calls, n_raws_added, n_crops_added, "
        "n_review_enqueued, n_errors, error_summary "
        "FROM source_runs WHERE id = ?",
        (run_id,),
    ).fetchone()

    print()
    print(f"run_id           {run_id}")
    print(f"status           {row['status']}")
    print(f"current_step     {row['current_step']}")
    print(f"n_calls          {row['n_calls']}")
    print(f"n_raws_added     {row['n_raws_added']}")
    print(f"n_crops_added    {row['n_crops_added']}")
    print(f"n_review_enqueued {row['n_review_enqueued']}")
    print(f"n_errors         {row['n_errors']}")
    if row["error_summary"]:
        print(f"error_summary    {row['error_summary']}")

    return 1 if row["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
