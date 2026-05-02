# `ml/sources/_base/` — generic plumbing

This package holds everything a source-specific module ([`ebay`](../ebay/),
[`catawiki`](../catawiki/), ...) does not need to re-implement. The
specification is in [`docs/sources-refacto/`](../../../docs/sources-refacto/),
specifically:

- [`decisions.md`](../../../docs/sources-refacto/decisions.md) — the 15
  frozen decisions
- [`orchestration.md`](../../../docs/sources-refacto/orchestration.md) — 4
  layers + 6-step pipeline
- [`schema.md`](../../../docs/sources-refacto/schema.md) — DDL of the
  new tables (mirrored in [`ml/state/schema.sql`](../../state/schema.sql))

## Status (2026-05-02)

| Module | Status |
|---|---|
| `sources_registry.py` | ✅ live (9 sources declared) |
| `run_logger.py`       | ✅ live (start/step/bump/end + anti-double-run) |
| `dedup.py`            | ✅ live (idempotent upserts for the 4 ingestion tables) |
| `storage.py`          | ⏳ next |
| `quota_guard.py`      | ⏳ next (wrap `ml/api_quota.py`) |
| `http.py`             | ⏳ next |
| `license_map.py`      | ⏳ next |
| `condition_map.py`    | ⏳ next |
| `orchestrator.py`     | ⏳ depends on the above |

Tests : [`ml/tests/test_sources_base.py`](../../tests/test_sources_base.py).
Run with `cd ml && .venv/bin/python -m pytest tests/test_sources_base.py -q`.
