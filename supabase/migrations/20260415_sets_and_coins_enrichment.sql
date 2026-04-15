-- Migration: sets architecture + coins metadata enrichment
-- Date: 2026-04-15
-- Refs:
--   docs/design/_shared/sets-architecture.md §4, §6
--   docs/design/admin/README.md
--   docs/DECISIONS.md §"Sets d'achievement", §"Admin tooling"
--
-- This migration is additive only (no DROP, no data loss).
-- It adds:
--   1. Metadata columns on `coins` (issue_type, series, ruler, theme_code, mintage, series_rank)
--   2. New table `sets` (achievement set definitions)
--   3. New table `set_members` (curated set memberships)
--   4. New table `sets_audit` (append-only audit log)
--   5. RLS policies (public read, admin-role write)
--
-- Apply via: mcp__supabase__apply_migration (or Supabase SQL editor).

BEGIN;

-- =============================================================================
-- 1. Enrich `coins` with metadata needed by the structural sets DSL
-- =============================================================================
-- Rationale: the DSL in sets-architecture.md §3 needs `issue_type`, `series`,
-- `ruler`, `theme_code` to express rich sets (per-ruler Vatican, per-redesign
-- France, common commemoratives by BCE theme). `mintage` + `series_rank` enable
-- rarity-based sets (min/max_mintage) and ordered display.
--
-- Note: `is_commemorative` (bool) and `theme` (free text) are kept as legacy
-- fields for compat; `issue_type` (enum) and `theme_code` (canonical key) are
-- the new canonical fields. Bootstrap script will populate both.

ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS issue_type  text
    CHECK (issue_type IN (
      'circulation',
      'commemo-national',
      'commemo-common',
      'starter-kit',
      'bu-set',
      'proof'
    )),
  ADD COLUMN IF NOT EXISTS series       text,       -- e.g. 'fr-1999', 'fr-2022', 'be-albert-ii'
  ADD COLUMN IF NOT EXISTS ruler        text,       -- e.g. 'jp2', 'benedict-xvi' (nullable, redundant with series for monarchies)
  ADD COLUMN IF NOT EXISTS theme_code   text,       -- e.g. 'eu-rome-2007', 'eu-emu-2009' (BCE canonical)
  ADD COLUMN IF NOT EXISTS mintage      bigint,     -- total mintage from Numista
  ADD COLUMN IF NOT EXISTS series_rank  int;        -- position within a series (for ordered display)

CREATE INDEX IF NOT EXISTS idx_coins_country_series
  ON coins (country, series);

CREATE INDEX IF NOT EXISTS idx_coins_theme_code
  ON coins (theme_code)
  WHERE theme_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_coins_issue_type_year
  ON coins (issue_type, year);

COMMENT ON COLUMN coins.issue_type IS
  'Canonical issue type, richer than is_commemorative. Values: circulation, commemo-national, commemo-common, starter-kit, bu-set, proof. Nullable until bootstrap populates it.';
COMMENT ON COLUMN coins.series IS
  'Series/type identifier for ruler changes and redesigns. E.g. fr-1999, fr-2022, be-albert-ii, be-philippe, va-jp2. Nullable.';
COMMENT ON COLUMN coins.ruler IS
  'Ruler identifier for monarchies and Vatican. Redundant with series. E.g. jp2, benedict-xvi, francis. Nullable.';
COMMENT ON COLUMN coins.theme_code IS
  'Canonical theme code for common commemoratives, sourced from BCE. E.g. eu-rome-2007, eu-emu-2009. Nullable.';
COMMENT ON COLUMN coins.mintage IS
  'Total mintage, sourced from Numista. Nullable.';
COMMENT ON COLUMN coins.series_rank IS
  'Position within a series for ordered display. Nullable.';


-- =============================================================================
-- 2. Table `sets` — achievement set definitions
-- =============================================================================
-- One row per achievement set. Source of truth for app mobile and admin.
-- Full spec: docs/design/_shared/sets-architecture.md §4.1

CREATE TABLE IF NOT EXISTS sets (
  id               text PRIMARY KEY,
  kind             text NOT NULL CHECK (kind IN ('structural', 'curated', 'parametric')),
  name_i18n        jsonb NOT NULL,                                  -- {fr:"…", en:"…", de:"…", it:"…"}
  description_i18n jsonb,
  criteria         jsonb,                                           -- structural/parametric only (DSL §3)
  param_key        text,                                            -- parametric only ('birth_year')
  reward           jsonb,                                           -- {badge:'gold', xp:500, level_bump:false}
  display_order    int NOT NULL DEFAULT 1000,
  category         text NOT NULL CHECK (category IN ('country', 'theme', 'tier', 'personal', 'hunt')),
  icon             text,                                            -- asset ref
  expected_count   int,                                             -- bootstrap validation (optional)
  active           bool NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),

  -- Shape validation per kind
  CONSTRAINT sets_structural_has_criteria
    CHECK (kind <> 'structural' OR criteria IS NOT NULL),
  CONSTRAINT sets_parametric_has_criteria_and_param
    CHECK (kind <> 'parametric' OR (criteria IS NOT NULL AND param_key IS NOT NULL)),
  CONSTRAINT sets_curated_no_criteria
    CHECK (kind <> 'curated' OR criteria IS NULL),
  -- name_i18n must at least have fr and en
  CONSTRAINT sets_name_i18n_has_fr_en
    CHECK (name_i18n ? 'fr' AND name_i18n ? 'en')
);

CREATE INDEX IF NOT EXISTS idx_sets_active_order
  ON sets (active, display_order);

CREATE INDEX IF NOT EXISTS idx_sets_category
  ON sets (category);

COMMENT ON TABLE sets IS
  'Achievement set definitions. Source of truth for mobile app and admin. See docs/design/_shared/sets-architecture.md.';
COMMENT ON COLUMN sets.kind IS
  'structural = DSL criteria; curated = explicit member list; parametric = DSL with user-provided param';
COMMENT ON COLUMN sets.criteria IS
  'JSONB criteria per the frozen v1 DSL (sets-architecture.md §3). Keys: country, issue_type, year, denomination, series, ruler, theme_code, distinct_by, min_mintage, max_mintage.';
COMMENT ON COLUMN sets.param_key IS
  'For parametric sets: the user-provided variable name, e.g. birth_year.';
COMMENT ON COLUMN sets.expected_count IS
  'Expected number of matching coins after bootstrap, used as a sanity assert.';


-- Auto-bump updated_at
CREATE OR REPLACE FUNCTION sets_touch_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sets_touch_updated_at ON sets;
CREATE TRIGGER sets_touch_updated_at
  BEFORE UPDATE ON sets
  FOR EACH ROW
  EXECUTE FUNCTION sets_touch_updated_at();


-- =============================================================================
-- 3. Table `set_members` — curated set memberships
-- =============================================================================
-- Only populated for sets where kind='curated'. Structural/parametric sets
-- derive their members at runtime from the `criteria` DSL.
--
-- Constraint: set_members.set_id must reference a curated set. Enforced via
-- trigger below (cannot be done in a CHECK constraint with a subquery).

CREATE TABLE IF NOT EXISTS set_members (
  set_id     text NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
  eurio_id   text NOT NULL REFERENCES coins(eurio_id),
  position   int,                                                   -- display order within the set (nullable)
  PRIMARY KEY (set_id, eurio_id)
);

CREATE INDEX IF NOT EXISTS idx_set_members_coin
  ON set_members (eurio_id);

CREATE OR REPLACE FUNCTION set_members_enforce_curated_parent()
RETURNS trigger AS $$
DECLARE
  parent_kind text;
BEGIN
  SELECT kind INTO parent_kind FROM sets WHERE id = NEW.set_id;
  IF parent_kind IS DISTINCT FROM 'curated' THEN
    RAISE EXCEPTION
      'set_members rows must reference a curated set (set_id=%, parent kind=%)',
      NEW.set_id, parent_kind;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_members_enforce_curated_parent ON set_members;
CREATE TRIGGER set_members_enforce_curated_parent
  BEFORE INSERT OR UPDATE ON set_members
  FOR EACH ROW
  EXECUTE FUNCTION set_members_enforce_curated_parent();

COMMENT ON TABLE set_members IS
  'Curated set memberships only. Structural/parametric sets derive members at runtime.';


-- =============================================================================
-- 4. Table `sets_audit` — append-only audit log
-- =============================================================================
-- Populated by the admin tool and the bootstrap script. Append-only enforced
-- via RLS (no UPDATE/DELETE policy).

CREATE TABLE IF NOT EXISTS sets_audit (
  id         bigserial PRIMARY KEY,
  set_id     text NOT NULL,
  action     text NOT NULL CHECK (action IN (
    'create',
    'update',
    'delete',
    'activate',
    'deactivate',
    'publish'
  )),
  before     jsonb,
  after      jsonb,
  actor      text NOT NULL,                                         -- email or 'bootstrap-script'
  at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sets_audit_set ON sets_audit (set_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_sets_audit_actor ON sets_audit (actor, at DESC);

COMMENT ON TABLE sets_audit IS
  'Append-only audit log for set mutations. Never UPDATE or DELETE rows.';


-- =============================================================================
-- 5. RLS policies
-- =============================================================================
-- Pattern: public SELECT on active sets, admin-role full write.
-- Admin role identified via JWT claim: auth.jwt() ->> 'role' = 'admin'.

ALTER TABLE sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE set_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE sets_audit ENABLE ROW LEVEL SECURITY;

-- sets: public read (active only), admin write
DROP POLICY IF EXISTS sets_public_read ON sets;
CREATE POLICY sets_public_read ON sets
  FOR SELECT
  USING (active = true);

DROP POLICY IF EXISTS sets_admin_all ON sets;
CREATE POLICY sets_admin_all ON sets
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

-- set_members: public read, admin write
DROP POLICY IF EXISTS set_members_public_read ON set_members;
CREATE POLICY set_members_public_read ON set_members
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS set_members_admin_all ON set_members;
CREATE POLICY set_members_admin_all ON set_members
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

-- sets_audit: admin read, admin INSERT only (no UPDATE/DELETE = append-only)
DROP POLICY IF EXISTS sets_audit_admin_read ON sets_audit;
CREATE POLICY sets_audit_admin_read ON sets_audit
  FOR SELECT
  USING (auth.jwt() ->> 'role' = 'admin');

DROP POLICY IF EXISTS sets_audit_admin_insert ON sets_audit;
CREATE POLICY sets_audit_admin_insert ON sets_audit
  FOR INSERT
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

-- Deliberately no UPDATE or DELETE policy on sets_audit → append-only.


COMMIT;
