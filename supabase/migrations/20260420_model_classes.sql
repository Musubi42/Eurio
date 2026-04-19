-- Migration: model_classes — per-class trained embeddings keyed by class_id
-- Date: 2026-04-20
-- Refs:
--   docs/design/_shared/design-groups.md §6.1
--
-- Context:
--   ArcFace labels switch from `eurio_id` (one class per coin) to
--   `COALESCE(design_group_id, eurio_id)`. A design_group of 14 annual re-issues
--   becomes ONE class rather than 14, dramatically improving label efficiency
--   (OCR handles the year disambiguation at scan time, cf. design-groups.md §4.3).
--
--   This table stores one centroid embedding per trained class, with an explicit
--   class_kind discriminating between coin-level (eurio_id) and group-level
--   (design_group_id) classes.
--
--   coin_embeddings (keyed by eurio_id) remains populated via dual-write during
--   the transition period so Android clients can continue reading it unchanged.
--   The switch to model_classes on mobile is a separate chantier.

BEGIN;

-- ============================================================================
-- 1. Table `model_classes`
-- ============================================================================

CREATE TABLE IF NOT EXISTS model_classes (
  class_id        text PRIMARY KEY,
  class_kind      text NOT NULL
                  CHECK (class_kind IN ('eurio_id', 'design_group_id')),
  embedding       real[] NOT NULL,
  model_version   text NOT NULL,
  n_train_images  integer,
  n_val_images    integer,
  recall_at_1     real,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_classes_model_version
  ON model_classes(model_version);

CREATE INDEX IF NOT EXISTS idx_model_classes_class_kind
  ON model_classes(class_kind);

COMMENT ON TABLE model_classes IS
  'Per-class centroid embeddings for the current ArcFace model. One row per class, where a class is either a single eurio_id (standalone coin) or a design_group_id (shared-design grouping). Dual-written with coin_embeddings during the mobile migration. See docs/design/_shared/design-groups.md §6.1.';
COMMENT ON COLUMN model_classes.class_id IS
  'Foreign identifier: either coins.eurio_id or design_groups.id, discriminated by class_kind. Not a hard FK — a class may outlive its source row for archival purposes.';
COMMENT ON COLUMN model_classes.class_kind IS
  'Discriminant: "eurio_id" = coin-level class (design_group_id is NULL), "design_group_id" = shared-design class spanning >=2 coins.';
COMMENT ON COLUMN model_classes.embedding IS
  'L2-normalized centroid in the ArcFace embedding space (typically 256-dim float).';
COMMENT ON COLUMN model_classes.model_version IS
  'Semantic version of the training run that produced this embedding (e.g. "v3-arcface"). Bumped on every full retrain.';


-- Auto-bump updated_at on UPDATE
CREATE OR REPLACE FUNCTION model_classes_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS model_classes_touch_updated_at ON model_classes;
CREATE TRIGGER model_classes_touch_updated_at
  BEFORE UPDATE ON model_classes
  FOR EACH ROW
  EXECUTE FUNCTION model_classes_touch_updated_at();


-- ============================================================================
-- 2. RLS — public read, admin write (mirrors coin_embeddings / design_groups)
-- ============================================================================

ALTER TABLE model_classes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS model_classes_public_read ON model_classes;
CREATE POLICY model_classes_public_read ON model_classes
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS model_classes_admin_all ON model_classes;
CREATE POLICY model_classes_admin_all ON model_classes
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

COMMIT;
