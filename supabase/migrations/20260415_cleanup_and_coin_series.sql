-- Migration: cleanup + coin_series first-class model
-- Date: 2026-04-15
-- Refs:
--   docs/design/_shared/sets-architecture.md (revised)
--   docs/DECISIONS.md §"Sets d'achievement"
--
-- Context:
--   - Drop theme_code (redundant with (year, issue_type='commemo-common') — only ever
--     one common commemo per year since 2002).
--   - Drop ruler (redundant with coin_series.designation).
--   - Drop series_rank (unused in DSL v1).
--   - Refactor coins.series (loose text) → coins.series_id FK to new coin_series table
--     that properly models series lifecycle (minting_started_at, minting_ended_at,
--     supersedes chain).
--   - Add individual coin withdrawal tracking (is_withdrawn, withdrawn_at,
--     withdrawal_reason) on coins. Distinct from minting_ended_at on the series:
--     a series can stop minting while coins remain in circulation (the euro standard
--     since 2002 — no post-release recall ever happened, but we model it because it
--     matters for valuation if it ever does).

-- 1. Drop unused columns
ALTER TABLE coins
  DROP COLUMN IF EXISTS theme_code,
  DROP COLUMN IF EXISTS ruler,
  DROP COLUMN IF EXISTS series_rank;

DROP INDEX IF EXISTS idx_coins_theme_code;
DROP INDEX IF EXISTS idx_coins_country_series;


-- 2. New table coin_series — first-class series entity
CREATE TABLE IF NOT EXISTS coin_series (
  id                      text PRIMARY KEY,
  country                 text NOT NULL,
  designation             text NOT NULL,
  designation_i18n        jsonb,
  description             text,

  minting_started_at      date NOT NULL,
  minting_ended_at        date,
  minting_end_reason      text CHECK (minting_end_reason IN (
    'ruler_change',
    'redesign',
    'policy',
    'sede_vacante_end',
    'other'
  )),

  supersedes_series_id    text REFERENCES coin_series(id),
  superseded_by_series_id text REFERENCES coin_series(id),

  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT coin_series_end_after_start
    CHECK (minting_ended_at IS NULL OR minting_ended_at >= minting_started_at)
);

CREATE INDEX IF NOT EXISTS idx_coin_series_country ON coin_series(country);
CREATE INDEX IF NOT EXISTS idx_coin_series_active
  ON coin_series(country)
  WHERE minting_ended_at IS NULL;

COMMENT ON TABLE coin_series IS
  'Circulation coin series (design types) with lifecycle metadata. One row per series = (country, design type). Ruler changes and redesigns create new series with supersedes chain.';
COMMENT ON COLUMN coin_series.minting_ended_at IS
  'Date when minting of this series stopped. NULL = still in production.';
COMMENT ON COLUMN coin_series.minting_end_reason IS
  'Why minting ended: ruler_change, redesign (e.g. FR 2022), policy, sede_vacante_end, other.';
COMMENT ON COLUMN coin_series.supersedes_series_id IS
  'Previous series this one replaced (e.g. be-philippe supersedes be-albert-ii).';


-- 3. Trigger: auto-bump updated_at
CREATE OR REPLACE FUNCTION coin_series_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS coin_series_touch_updated_at ON coin_series;
CREATE TRIGGER coin_series_touch_updated_at
  BEFORE UPDATE ON coin_series
  FOR EACH ROW
  EXECUTE FUNCTION coin_series_touch_updated_at();


-- 4. Refactor coins.series → coins.series_id (FK)
ALTER TABLE coins RENAME COLUMN series TO series_id;

ALTER TABLE coins
  ADD CONSTRAINT coins_series_id_fkey
  FOREIGN KEY (series_id) REFERENCES coin_series(id)
  ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_coins_series_id ON coins(series_id);

COMMENT ON COLUMN coins.series_id IS
  'FK to coin_series(id). NULL for commemorative coins (commemos are standalone, not part of a series). Populated for circulation coins via (country, year) match against coin_series date range.';


-- 5. Individual coin withdrawal tracking
ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS is_withdrawn       boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS withdrawn_at       date,
  ADD COLUMN IF NOT EXISTS withdrawal_reason  text;

CREATE INDEX IF NOT EXISTS idx_coins_withdrawn
  ON coins(is_withdrawn)
  WHERE is_withdrawn = true;

COMMENT ON COLUMN coins.is_withdrawn IS
  'True if this specific coin has been officially withdrawn from circulation. Rare but important for collectors (affects valuation). Distinct from minting_ended_at on the series (ended minting != withdrawn from circulation).';
COMMENT ON COLUMN coins.withdrawn_at IS
  'Date of withdrawal decision. Nullable.';
COMMENT ON COLUMN coins.withdrawal_reason IS
  'Reason for withdrawal: design_issue, political, defect, other. Nullable.';


-- 6. RLS on coin_series
ALTER TABLE coin_series ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS coin_series_public_read ON coin_series;
CREATE POLICY coin_series_public_read ON coin_series
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS coin_series_admin_all ON coin_series;
CREATE POLICY coin_series_admin_all ON coin_series
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');
