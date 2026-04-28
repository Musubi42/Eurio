-- Migration: coins.personal_owned (admin's personal collection flag)
-- Date: 2026-04-28
--
-- Context:
--   The /coins admin gets a "ma collection perso" toggle: per-card checkbox
--   with a wallet-icon background, direct toggle (no batch footer), filter
--   chip "Collection perso / Pas perso" on the page header. This lets the
--   solo admin (Raphaël) tag every 2 EUR coin he physically owns and use
--   that subset as the candidate pool for the next training round (Phase F5
--   in docs/scan-normalization/), instead of curating a 20-design list.
--
--   Single-admin assumption: this column is global on the coins table, not
--   user-scoped. If we ever support multiple admins with distinct personal
--   collections we'll move to a junction table — keeping it simple for now.

ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS personal_owned boolean NOT NULL DEFAULT false;

-- Partial index — almost every coin will be unowned, so the WHERE clause
-- keeps the index tight (the same shape as has_bce/has_wikipedia/etc.).
CREATE INDEX IF NOT EXISTS idx_coins_personal_owned
  ON coins(eurio_id) WHERE personal_owned;

COMMENT ON COLUMN coins.personal_owned
  IS 'True iff the admin physically owns this coin. Toggled from the /coins admin checkbox; used as candidate pool for training-set composition in Phase F5 (docs/scan-normalization/).';
