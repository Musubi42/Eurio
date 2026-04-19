-- Migration: design_groups — shared-design grouping for coins
-- Date: 2026-04-18
-- Refs:
--   docs/design/_shared/design-groups.md
--
-- Context:
--   Coins sharing the same visual design (annual re-issues intra-country OR
--   joint commemorative variants cross-country) need a canonical grouping so
--   that (a) ArcFace trains on one class per design rather than one class per
--   eurio_id, (b) the confusion map excludes intra-group pairs from collision
--   scoring, (c) the admin has a natural "variants of this design" view, and
--   (d) scan inference disambiguates design first, then (year | country) via
--   OCR in a second pass.
--
--   This table is the pivot. One row per shared design. FK from coins is
--   nullable: a coin has a design_group_id iff its design is shared by >=2
--   coins. True one-offs (FR D-Day 2014, AT Mozart 2006) stay NULL.
--
--   Bootstrap is two-stage (see ml/bootstrap_design_groups.py):
--     1. Axis A (intra-country annual re-issues) — automatic, grouping coins
--        by cross_refs->>numista_id when count >= 2. Numista assigns one id
--        per design and changes id on effigy/map/type changes.
--     2. Axis B (joint commemoratives) — manual seed, loaded from
--        ml/data/design_groups_seed.json.

BEGIN;

-- ============================================================================
-- 1. Table `design_groups`
-- ============================================================================

CREATE TABLE IF NOT EXISTS design_groups (
  id                 text PRIMARY KEY,
  designation        text NOT NULL,
  designation_i18n   jsonb,
  description        text,
  shared_obverse_url text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_design_groups_updated_at
  ON design_groups(updated_at DESC);

COMMENT ON TABLE design_groups IS
  'Canonical grouping of coins sharing the same visual design. Covers both intra-country annual re-issues (axis A, seeded from Numista cross_refs) and cross-country joint commemoratives (axis B, seeded from ml/data/design_groups_seed.json). See docs/design/_shared/design-groups.md.';
COMMENT ON COLUMN design_groups.id IS
  'Stable slug identifier. Convention: {country}-{denom}-{series-short}[-{variant}] for axis A (e.g. be-2euro-albert-ii-ef1, fr-2euro-1999-std), eu-{theme-slug}-{year} for axis B (e.g. eu-rome-2007).';
COMMENT ON COLUMN design_groups.designation IS
  'Admin-facing label (e.g. "BE 2€ Albert II (1re effigie)").';
COMMENT ON COLUMN design_groups.designation_i18n IS
  'Localized labels for mobile and admin. {fr:"…", en:"…", de:"…", it:"…"}.';
COMMENT ON COLUMN design_groups.shared_obverse_url IS
  'Reference image URL (one of the members) used as training cover and admin display.';


-- Auto-bump updated_at on UPDATE
CREATE OR REPLACE FUNCTION design_groups_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS design_groups_touch_updated_at ON design_groups;
CREATE TRIGGER design_groups_touch_updated_at
  BEFORE UPDATE ON design_groups
  FOR EACH ROW
  EXECUTE FUNCTION design_groups_touch_updated_at();


-- ============================================================================
-- 2. FK on `coins`
-- ============================================================================
-- Nullable: NULL = coin has a unique design (true one-off or singleton).
-- Non-NULL = coin shares its design with >=1 other coin.
-- ON DELETE SET NULL: removing a design_group unparents the coins, does not
-- delete them. The coins remain valid, just uncategorised.

ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS design_group_id text
    REFERENCES design_groups(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_coins_design_group
  ON coins(design_group_id)
  WHERE design_group_id IS NOT NULL;

COMMENT ON COLUMN coins.design_group_id IS
  'FK to design_groups(id). NULL for coins with a unique design. Non-NULL when design is shared by >=2 coins (annual re-issue within a country OR joint commemorative across countries). See docs/design/_shared/design-groups.md.';


-- ============================================================================
-- 3. RLS — public read, admin write (mirrors coin_series/sets pattern)
-- ============================================================================

ALTER TABLE design_groups ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS design_groups_public_read ON design_groups;
CREATE POLICY design_groups_public_read ON design_groups
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS design_groups_admin_all ON design_groups;
CREATE POLICY design_groups_admin_all ON design_groups
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');


COMMIT;
