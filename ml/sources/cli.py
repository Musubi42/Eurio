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


def _load_adapter(source_id: str, *, store=None):
    if source_id == "mock":
        from sources._mock import MockAdapter
        return MockAdapter()
    if source_id == "ebay":
        import os

        from market.ebay_client import EbayClient, get_app_token
        from sources.ebay import EbayAdapter

        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise SystemExit(
                "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set in env. "
                "Run inside a directory with .envrc loaded (direnv allow)."
            )
        token = get_app_token(client_id, client_secret)
        client = EbayClient(token)
        if store is None:
            raise SystemExit("ebay adapter requires a Store (internal: pass store=).")
        return EbayAdapter(client=client, conn=store._connection())
    raise SystemExit(
        f"Unknown source '{source_id}'. Available: mock, ebay. "
        "Real sources will be added as their adapters land."
    )


def _resolve_ebay_targets(store, *, batch: int, explicit: list[str] | None) -> list[str]:
    """Resolve `target_eurio_ids` for an eBay run.

    Priority: explicit `--eurio-ids a,b,c` > freshness queue head (top-N
    of `v_ebay_freshness` ordered NULLS FIRST). Default batch size = 10
    (D-21).
    """
    if explicit:
        return list(explicit)
    rows = store._connection().execute(
        """
        SELECT eurio_id FROM v_ebay_freshness
         ORDER BY last_enriched_at ASC NULLS FIRST, eurio_id
         LIMIT ?
        """,
        (batch,),
    ).fetchall()
    return [r["eurio_id"] for r in rows]


def _ebay_preflight_or_die(store, *, n_eurio_ids: int) -> None:
    from api.sources_routes import check_ebay_quota

    check = check_ebay_quota(store, n_eurio_ids=n_eurio_ids)
    print(
        f"[pre-flight] avg={check['avg_calls_per_eurio_id']} calls/eurio_id, "
        f"estimate={check['estimate']} calls, remaining={check['remaining']}/{check['limit']}"
    )
    if not check["ok"]:
        raise SystemExit(
            f"Quota insufficient: estimate {check['estimate']} × 1.3 > "
            f"remaining {check['remaining']}. Reduce batch to "
            f"≤{check['max_safe_batch']} or wait for tomorrow."
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
    p.add_argument("--target-eurio-ids", default=None,
                   help="Comma-separated eurio_ids (overrides freshness queue for ebay).")
    p.add_argument("--batch", type=int, default=10,
                   help="Batch size for ebay freshness queue (default: 10, D-21).")
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

    store = Store(args.db)

    target_eurio_ids: tuple[str, ...] | None = None
    if args.source == "ebay" and not args.target_eurio_id:
        explicit = (
            [s.strip() for s in args.target_eurio_ids.split(",") if s.strip()]
            if args.target_eurio_ids else None
        )
        ids = _resolve_ebay_targets(store, batch=args.batch, explicit=explicit)
        if not ids:
            raise SystemExit(
                "No eurio_ids found in freshness queue. "
                "Run `go-task ml:bootstrap-coins` first."
            )
        if not args.dry_run:
            _ebay_preflight_or_die(store, n_eurio_ids=len(ids))
        target_eurio_ids = tuple(ids)
        print(f"[ebay] batch of {len(ids)} eurio_ids: {ids[:3]}{'...' if len(ids) > 3 else ''}")
    elif args.target_eurio_ids:
        target_eurio_ids = tuple(s.strip() for s in args.target_eurio_ids.split(",") if s.strip())

    adapter = _load_adapter(args.source, store=store)
    if args.dry_run and hasattr(adapter, "dry_run"):
        adapter.dry_run = True
    query = SourceQuery(
        source_id=args.source,
        country=args.country,
        denomination=args.denomination,
        year=args.year,
        target_eurio_id=args.target_eurio_id,
        target_eurio_ids=target_eurio_ids,
        limit=args.limit,
    )

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
