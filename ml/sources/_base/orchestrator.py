"""Generic 6-step ingestion pipeline (D-13).

Drives any `SourceAdapter` through Discover → Persist → Download →
Detect → Resolve → Enqueue, writing to `source_runs` after each step.
Chunks 2.B → 2.D progressively replace the stubs below with real
step implementations under `ml/sources/_base/steps/`.

Idempotence is the contract: a re-run must produce zero new rows /
zero new files / zero new crops. Each step owns its upserts; the
orchestrator only sequences them.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from sources._base.adapter import SourceAdapter, SourceQuery
from sources._base.run_logger import start_run
from sources._base.steps.detect_crop import run_detect_crop
from sources._base.steps.discover import run_discover
from sources._base.steps.download import run_download
from sources._base.steps.enqueue import run_enqueue
from sources._base.steps.persist import run_persist
from sources._base.steps.resolve import run_resolve

if TYPE_CHECKING:
    from state.store import Store

logger = logging.getLogger(__name__)

PIPELINE_STEPS = ("discover", "persist", "download", "detect", "resolve", "enqueue")


def run_pipeline(
    adapter: SourceAdapter,
    query: SourceQuery,
    *,
    store: "Store",
    dry_run: bool = False,
    force: bool = False,
) -> str:
    """Execute the 6-step pipeline for one source.

    `dry_run=True` runs Discover only and writes nothing past the
    `source_runs` row (kind='dry') and the `discovery_log` upserts.
    Returns the run_id either way so the caller (CLI / front) can
    fetch counters and the log.
    """
    kind = "dry" if dry_run else "run"

    conn = store._connection()  # noqa: SLF001
    with start_run(
        conn,
        source=adapter.source_id,
        kind=kind,
        filters=asdict(query),
        force=force,
    ) as run:
        logger.info(
            "[%s] run_id=%s kind=%s query=%s",
            adapter.source_id, run.run_id, kind, query,
        )

        # ── 1. Discover ──────────────────────────────────────────────
        run.set_step("discover")
        discover_result = run_discover(adapter, query, conn=conn, run=run)

        if dry_run:
            logger.info("[%s] dry-run: stopping after discover", adapter.source_id)
            run.end("success")
            return run.run_id

        # ── 2. Persist raw ───────────────────────────────────────────
        run.set_step("persist")
        persist_result = run_persist(
            discover_result.items,
            conn=conn,
            run=run,
            source_id=adapter.source_id,
        )

        # ── 3. Download ──────────────────────────────────────────────
        run.set_step("download")
        run_download(
            conn=conn,
            run=run,
            adapter=adapter,
            source_image_ids=persist_result.source_image_ids,
        )

        # ── 4. Detect & crop ─────────────────────────────────────────
        run.set_step("detect")
        run_detect_crop(
            conn=conn,
            run=run,
            source_id=adapter.source_id,
            source_image_ids=persist_result.source_image_ids,
        )

        # ── 5. Resolve ───────────────────────────────────────────────
        run.set_step("resolve")
        run_resolve(
            conn=conn,
            run=run,
            source_id=adapter.source_id,
            source_image_ids=persist_result.source_image_ids,
        )

        # ── 6. Enqueue review ────────────────────────────────────────
        run.set_step("enqueue")
        run_enqueue(
            conn=conn,
            run=run,
            source_id=adapter.source_id,
            source_image_ids=persist_result.source_image_ids,
        )

        n_errors = conn.execute(
            "SELECT n_errors FROM source_runs WHERE id = ?", (run.run_id,)
        ).fetchone()["n_errors"]
        if n_errors > 0:
            run.end("partial", error_summary=f"{n_errors} item(s) failed — see logs")
        else:
            run.end("success")
        return run.run_id
