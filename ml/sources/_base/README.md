# `ml/sources/_base/` — generic plumbing

This package holds everything a source-specific module ([`ebay`](../ebay/),
[`catawiki`](../catawiki/), ...) does not need to re-implement. The
specification is in [`docs/sources-refacto/`](../../../docs/sources-refacto/),
specifically:

- [`decisions.md`](../../../docs/sources-refacto/decisions.md) — the 15
  frozen decisions
- [`orchestration.md`](../../../docs/sources-refacto/orchestration.md) — 4
  layers + 8-step pipeline
- [`schema.md`](../../../docs/sources-refacto/schema.md) — DDL of the
  new tables (mirrored in [`ml/state/schema.sql`](../../state/schema.sql))

## Status (2026-05-03)

| Module | Status |
|---|---|
| `sources_registry.py` | ✅ live (10 sources, including `mock` test fixture) |
| `run_logger.py`       | ✅ live (start/step/bump/end + anti-double-run) |
| `dedup.py`            | ✅ live (4 ingestion tables + `discovery_log` C1 helpers) |
| `adapter.py`          | ✅ live (`SourceAdapter` Protocol + dataclasses) |
| `query_sig.py`        | ✅ live (sha256 16 chars stable) |
| `storage.py`          | ✅ live (sharded canonical paths + atomic write) |
| `phash.py`            | ✅ live (DCT 64-bit signed, compatible UDFs) |
| `steps/discover.py`   | ✅ live (C1 dédup) |
| `steps/persist.py`    | ✅ live (C2 dédup + license/redistributable from spec) |
| `steps/download.py`   | ✅ live (C3 dédup, per-item errors non-blocking) |
| `steps/detect_crop.py`| ✅ live (`scan.normalize_studio` direct, no fallback — D-17) |
| `steps/resolve.py`    | ✅ live (V1: all `needs_review` — D-18) |
| `steps/enqueue.py`    | ✅ live (C5 dédup + priority calc) |
| `orchestrator.py`     | ✅ live (`run_pipeline(adapter, query, *, store, dry_run)`) |
| `quota_guard.py`      | ⏳ next (wrap `ml/api_quota.py`, needed for real eBay/Numista) |
| `http.py`             | ⏳ next (shared retry/backoff for HTTP-based adapters) |
| `license_map.py`      | ⏳ next |
| `condition_map.py`    | ⏳ next |

Tests :
- [`ml/tests/test_sources_base.py`](../../tests/test_sources_base.py) — 8 tests
- [`ml/tests/test_orchestrator.py`](../../tests/test_orchestrator.py) — 9 tests

Run all : `cd ml && .venv/bin/python -m pytest tests/test_sources_base.py tests/test_orchestrator.py -v`.
