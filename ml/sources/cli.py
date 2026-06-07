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

from sources._base.adapter import DiscoveryGroup, SourceQuery
from sources._base.orchestrator import process_downloaded, run_pipeline
from store import Store

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "state" / "eurio.db"


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
        if store is None:
            raise SystemExit("ebay adapter requires a Store (internal: pass store=).")
        # B4 — factory partagée pour les N clients par mkt. Tracker partagé
        # via QuotaTracker singleton (table api_call_log côté SQLite),
        # passé explicitement pour éviter qu'EbayClient n'instancie un
        # tracker par mkt (sinon le quota daily compterait à part par mkt).
        from api_quota import QuotaTracker
        from market.ebay_client import EBAY_DAILY_LIMIT
        shared_tracker = QuotaTracker("ebay", "daily", EBAY_DAILY_LIMIT)
        make_client = lambda mkt: EbayClient(  # noqa: E731
            token, marketplace=mkt, tracker=shared_tracker,
        )
        return EbayAdapter(make_client=make_client, conn=store._connection())
    raise SystemExit(
        f"Unknown source '{source_id}'. Available: mock, ebay. "
        "Real sources will be added as their adapters land."
    )


def _resolve_ebay_groups(
    store, *, batch: int, country: str | None, year: int | None,
) -> list["EbayGroup"]:
    """Resolve **commemorative** discovery groups for an eBay run.

    Renvoie une liste d'``EbayGroup`` (kind=``commemorative``). Priorité :
    ``--country`` + ``--year`` épingle un groupe unique ; sinon, tête de la
    freshness queue groupée (top-N des groupes les plus stale de
    ``v_ebay_freshness_groups``). Les standards ne passent pas par la
    freshness queue — ils sont scopés par cohort (``cohort_ebay_groups``).
    """
    from sources.cohort_scope import EbayGroup

    conn = store._connection()
    if country and year:
        rows = conn.execute(
            """
            SELECT denomination, country, year, n_coins
              FROM v_ebay_freshness_groups
             WHERE country = ? AND year = ?
            """,
            (country, year),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT denomination, country, year, n_coins
              FROM v_ebay_freshness_groups
             ORDER BY last_enriched_at ASC NULLS FIRST, country, year
             LIMIT ?
            """,
            (batch,),
        ).fetchall()
    return [
        EbayGroup(
            r["denomination"], r["country"], r["year"], r["n_coins"],
            "commemorative",
        )
        for r in rows
    ]


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
        description="Run the 8-step ingestion pipeline for one source.",
    )
    p.add_argument("--source", required=True, help="Source id (e.g. 'mock', 'ebay').")
    p.add_argument("--dry-run", action="store_true",
                   help="Stop after Discover; write nothing past discovery_log.")
    p.add_argument("--download-only", action="store_true",
                   help="Stop after Download; persist raws, defer crop (CPU). "
                        "Crop later with --crop-pending <RUN_ID>.")
    p.add_argument("--crop-pending", default=None, metavar="RUN_ID",
                   help="Crop a previous --download-only run (detect→resolve→…→"
                        "price). No re-download, no source credentials needed.")
    p.add_argument("--force", action="store_true",
                   help="Override anti-double-run guard.")
    p.add_argument("--country", default=None, help="Filter by ISO-2 country.")
    p.add_argument("--year", type=int, default=None, help="Filter by year.")
    p.add_argument("--denomination", default=None,
                   help="Filter by face value (e.g. '2eur', '0.50').")
    p.add_argument("--target-eurio-id", default=None,
                   help="Pin the eBay fetch to one eurio_id's group (debug).")
    p.add_argument("--target-eurio-ids", default=None,
                   help="Comma-separated eurio_ids (per-coin discovery — generic sources).")
    p.add_argument("--cohort-id", default=None,
                   help="Scope an eBay run to a lab cohort: only its coins' "
                        "(denom,country,year) groups are searched.")
    p.add_argument("--batch", type=int, default=10,
                   help="Number of discovery groups for the ebay freshness queue (default: 10).")
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

    # Crop-on-demand path : crop a previous --download-only run. No adapter
    # load (no eBay token needed), no discovery — just the deferred crop steps.
    if args.crop_pending:
        result = process_downloaded(store=store, run_id=args.crop_pending)
        print()
        print(f"run_id        {result.run_id}")
        print(f"n_pending     {result.n_pending}")
        print(f"n_crops_added {result.n_crops_added}")
        row = store._connection().execute(  # noqa: SLF001
            "SELECT status, current_step, n_crops_added, n_review_enqueued, "
            "n_errors, error_summary FROM source_runs WHERE id = ?",
            (args.crop_pending,),
        ).fetchone()
        if row is not None:
            print(f"status        {row['status']}")
            print(f"current_step  {row['current_step']}")
            if row["error_summary"]:
                print(f"error_summary {row['error_summary']}")
            return 1 if row["status"] == "failed" else 0
        return 0

    target_eurio_ids: tuple[str, ...] | None = None
    discovery_groups: tuple[DiscoveryGroup, ...] | None = None

    if args.target_eurio_ids:
        target_eurio_ids = tuple(
            s.strip() for s in args.target_eurio_ids.split(",") if s.strip()
        )
    elif args.cohort_id and args.source == "ebay":
        # Cohort-scoped run : only the groups covering the cohort's coins.
        from sources.cohort_scope import cohort_ebay_groups

        groups, non_scrapable = cohort_ebay_groups(store, args.cohort_id)
        if not groups:
            raise SystemExit(
                f"Cohort {args.cohort_id}: aucun groupe eBay-scrapable "
                "(que des eu-issues/variants ?)."
            )
        discovery_groups = tuple(
            DiscoveryGroup(
                denomination=g.denomination, country=g.country,
                year=g.year, kind=g.kind,
            )
            for g in groups
        )
        n_coins = sum(g.n_coins for g in groups)
        if non_scrapable:
            print(
                f"[ebay] {len(non_scrapable)} coin(s) hors découverte groupée "
                f"(eu-issues/variants — Numista-only): "
                f"{', '.join(non_scrapable)}"
            )
        if not args.dry_run:
            _ebay_preflight_or_die(store, n_eurio_ids=n_coins)
        labels = ", ".join(
            f"{g.country}/{g.year if g.year is not None else 'std'}"
            for g in groups[:4]
        )
        print(
            f"[ebay] cohort {args.cohort_id}: {len(groups)} group(s) / "
            f"{n_coins} coin(s): {labels}{'...' if len(groups) > 4 else ''}"
        )
    elif args.source == "ebay" and not args.target_eurio_id:
        # Découverte groupée : un run = un batch de groupes (denom, pays,
        # année). Sans --country/--year explicites, on prend la tête de la
        # freshness queue groupée.
        groups = _resolve_ebay_groups(
            store, batch=args.batch, country=args.country, year=args.year,
        )
        if not groups:
            raise SystemExit(
                "No discovery group found in freshness queue. "
                "Run `go-task ml:bootstrap-coins` first."
            )
        discovery_groups = tuple(
            DiscoveryGroup(
                denomination=g.denomination, country=g.country,
                year=g.year, kind=g.kind,
            )
            for g in groups
        )
        n_coins = sum(g.n_coins for g in groups)
        if not args.dry_run:
            _ebay_preflight_or_die(store, n_eurio_ids=n_coins)
        labels = ", ".join(
            f"{g.country}/{g.year if g.year is not None else 'std'}"
            for g in groups[:4]
        )
        print(
            f"[ebay] batch of {len(groups)} group(s) / {n_coins} coin(s): "
            f"{labels}{'...' if len(groups) > 4 else ''}"
        )

    adapter = _load_adapter(args.source, store=store)
    if args.dry_run and hasattr(adapter, "dry_run"):
        adapter.dry_run = True
    query = SourceQuery(
        source_id=args.source,
        country=args.country if discovery_groups is None else None,
        denomination=args.denomination,
        year=args.year if discovery_groups is None else None,
        target_eurio_id=args.target_eurio_id,
        target_eurio_ids=target_eurio_ids,
        discovery_groups=discovery_groups,
        limit=args.limit,
    )

    run_id = run_pipeline(
        adapter, query, store=store,
        dry_run=args.dry_run, download_only=args.download_only, force=args.force,
    )

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
