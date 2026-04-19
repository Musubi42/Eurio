-- Migration: refresh COMMENT ON TABLE coin_confusion_map after design_groups exclusion landed
-- Date: 2026-04-19
-- Refs:
--   docs/design/_shared/design-groups.md §6.3
--   ml/confusion_map.py (compute_pairwise_neighbors)
--
-- Cosmetic-only. The original comment from migration 20260417 mentioned exclusion
-- by Numista design id; the actual exclusion logic is now design_group_id with a
-- numista_id fallback for coins not yet bootstrapped. Keeps the schema docs in
-- sync with the runtime behaviour.

BEGIN;

COMMENT ON TABLE coin_confusion_map IS
  'Per-coin visual confusion cartography. One row per (eurio_id, encoder_version). Nearest neighbor excludes coins sharing the same design_group_id (annual re-issues + future joint-issue variants). Falls back to cross_refs->>numista_id when design_group_id is NULL on either side (covers coins not yet bootstrapped into a design_group).';

COMMIT;
