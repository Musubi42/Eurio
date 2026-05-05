"""Generic 8-step ingestion pipeline (D-13).

Drives any `SourceAdapter` through Discover → Persist → Text-signal →
Download → Detect → Resolve → Auto-validate → Enqueue, writing to
`source_runs` after each step. Step implementations live under
`ml/sources/_base/steps/`. The canonical step list is
`PIPELINE_STEPS` in `run_logger.py`.

Idempotence is the contract: a re-run must produce zero new rows /
zero new files / zero new crops. Each step owns its upserts; the
orchestrator only sequences them.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from sources._base.adapter import SourceAdapter, SourceQuery
from sources._base.run_logger import PIPELINE_STEPS, start_run

__all__ = ["PIPELINE_STEPS", "run_pipeline"]
from sources._base.steps.auto_validate import run_auto_validate_dino
from sources._base.steps.detect_crop import run_detect_crop
from sources._base.steps.discover import run_discover
from sources._base.steps.download import run_download
from sources._base.steps.enqueue import run_enqueue
from sources._base.steps.persist import run_persist
from sources._base.steps.resolve import run_resolve
from sources._base.steps.text_signal import run_text_signal_extract

if TYPE_CHECKING:
    from state.store import Store

logger = logging.getLogger(__name__)


def run_pipeline(
    adapter: SourceAdapter,
    query: SourceQuery,
    *,
    store: "Store",
    dry_run: bool = False,
    force: bool = False,
) -> str:
    """Execute the 8-step pipeline for one source.

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

        # ── 2.5. Text-signal extraction (chunk 5 auto-validation) ────
        # Pure regex/dict, no I/O on the listing API. Persiste 1 row par
        # source_image dans listing_text_signals. Pas un step de
        # décision en V1 — le filtre dur arrivera au chunk 6.
        run.set_step("text_signal")
        run_text_signal_extract(
            conn=conn,
            run=run,
            source_image_ids=persist_result.source_image_ids,
            store=store,
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

        # ── 5.5. Auto-validate via DINOv2 ────────────────────────────
        # Suggestion layer (V1, no decision). Skipped if anchor bank
        # missing — does not fail the pipeline. See
        # docs/sources-refacto/auto-validation/.
        run.set_step("auto_validate")
        run_auto_validate_dino(
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
