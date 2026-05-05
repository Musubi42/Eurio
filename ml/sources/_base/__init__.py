"""Generic plumbing shared by every source module.

A source-specific module (e.g. `ml/sources/ebay/fetch.py`) only owns
the bits that depend on the source: HTTP calls, listing parsing,
metadata extraction. Everything else — run logging, dedup, storage,
quota, name-match, pHash, review-queue enqueue — lives here.

Phase 1 surface (what's wired up):
- `sources_registry`  — declarative metadata per source
- `run_logger`        — context-manager that writes to `source_runs`
- `dedup`             — idempotent upsert helpers for the new tables

Phase 1 surface to be added next session:
- `quota_guard`       — wrapper on existing `ml/api_quota.py`
- `storage`           — disk paths + hashing
- `http`              — shared session
- `license_map`, `condition_map`
- `orchestrator`      — the 8-step generic runner
"""

from .run_logger import RunHandle, start_run
from .sources_registry import SOURCES, SourceSpec

__all__ = ["RunHandle", "SOURCES", "SourceSpec", "start_run"]
