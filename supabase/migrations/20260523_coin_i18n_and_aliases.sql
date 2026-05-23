-- Migration: coin_names_i18n + coin_aliases — projection ML → Supabase
-- Date: 2026-05-23
-- Refs:
--   docs/sources-refacto/ebay-multi-marketplace/i18n-strategy.md
--   docs/data-harmonization/i18n-147-handoff.md
--
-- Context:
--   `coin_names_i18n` et `coin_aliases` vivent depuis longtemps dans
--   ml/state/eurio.db (SQLite canonique côté ML). Elles ne traversaient
--   pas vers Supabase faute de sync. Cette migration crée les deux tables
--   côté Postgres et `ml/export/sync_to_supabase.py` les peuple ensuite.
--
--   Sémantique mirrror le schema SQLite (cf. ml/state/schema.sql §698-735).
--   Différences :
--     - timestamps `timestamptz` (au lieu de TEXT)
--     - FK vers `coins(eurio_id)` ON DELETE CASCADE
--     - RLS public-read + admin-write, comme model_classes/design_groups.

BEGIN;

-- ============================================================================
-- 1. Table `coin_names_i18n`
-- ============================================================================

CREATE TABLE IF NOT EXISTS coin_names_i18n (
  eurio_id    text NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  lang        text NOT NULL
              CHECK (lang IN ('fr','en','de','it','es','nl')),
  title       text NOT NULL,
  source      text NOT NULL DEFAULT 'numista'
              CHECK (source IN ('numista','llm_v1','manual')),
  confidence  text NOT NULL DEFAULT 'canon'
              CHECK (confidence IN ('canon','assisted','uncertain')),
  model       text,
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (eurio_id, lang)
);

CREATE INDEX IF NOT EXISTS idx_coin_names_i18n_lang
  ON coin_names_i18n(lang);

COMMENT ON TABLE coin_names_i18n IS
  'Localized coin titles. Source ''numista''/''canon'' for FR+EN (scraped). ''llm_v1''/''assisted'' for DE/IT/ES/NL (Claude). ''manual''/''canon'' for human edits. App displays only canon; matcher uses all confidences. See docs/sources-refacto/ebay-multi-marketplace/i18n-strategy.md.';
COMMENT ON COLUMN coin_names_i18n.confidence IS
  'canon=human-authored / scraped; assisted=LLM-translated; uncertain=LLM unsure (UI hides).';


-- ============================================================================
-- 2. Table `coin_aliases`
-- ============================================================================

CREATE TABLE IF NOT EXISTS coin_aliases (
  eurio_id    text NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  lang        text NOT NULL,
  alias       text NOT NULL,
  source      text NOT NULL DEFAULT 'mined',
  confidence  text NOT NULL DEFAULT 'high',
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (eurio_id, lang, alias)
);

CREATE INDEX IF NOT EXISTS idx_coin_aliases_eurio
  ON coin_aliases(eurio_id);

COMMENT ON TABLE coin_aliases IS
  'Surface-form aliases for the theme-matcher (nicknames, acronyms, culturally consacrated forms not present in i18n titles). lang=''xx'' for language-agnostic proper nouns. source: ''mined''|''acronym''|''llm''|''manual''. confidence: ''high''|''low''. Sister-collision guard enforced at ingest (cf. ml/scripts/llm_coin_aliases.py).';


-- ============================================================================
-- 3. RLS — public read, admin write
-- ============================================================================

ALTER TABLE coin_names_i18n ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS coin_names_i18n_public_read ON coin_names_i18n;
CREATE POLICY coin_names_i18n_public_read ON coin_names_i18n
  FOR SELECT USING (true);

DROP POLICY IF EXISTS coin_names_i18n_admin_all ON coin_names_i18n;
CREATE POLICY coin_names_i18n_admin_all ON coin_names_i18n
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');


ALTER TABLE coin_aliases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS coin_aliases_public_read ON coin_aliases;
CREATE POLICY coin_aliases_public_read ON coin_aliases
  FOR SELECT USING (true);

DROP POLICY IF EXISTS coin_aliases_admin_all ON coin_aliases;
CREATE POLICY coin_aliases_admin_all ON coin_aliases
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

COMMIT;
