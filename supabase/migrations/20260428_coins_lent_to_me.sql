-- Migration: coins.lent_to_me
-- Context: friends lend 2€ coins via eurio-loan Vercel site. This column
-- is a binary signal: "do I currently have physical access to this coin
-- for ML training or testing?". Toggled manually from admin /coins card.
-- Loan tracking (lender, dates, return) lives in Notion, not here.

ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS lent_to_me boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_coins_lent_to_me
  ON coins(eurio_id) WHERE lent_to_me;

COMMENT ON COLUMN coins.lent_to_me
  IS 'True iff a friend has physically lent this coin to the admin.
      Toggled manually from /coins admin card (third checkbox alongside
      personal_owned). Loan tracking lives in Notion — this is only the
      binary "currently testable" flag.';
