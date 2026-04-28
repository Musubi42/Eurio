-- Migration: coin_market_prices.quality + LMDLP source
-- Date: 2026-04-27
--
-- Context:
--   eBay scrapes were the only writers so far (P25/P50/P75 across many sales,
--   no quality breakdown — `quality` stays NULL for those rows). We now also
--   want to ingest LMDLP catalogue prices, which are quoted per numismatic
--   quality (UNC, BU FDC, BE Proof, BE Polissage inversé). One LMDLP row per
--   (coin × quality), using `p50` for the catalogue price.
--
--   Stays append-only to preserve the historical eBay time series. To keep
--   re-syncing the same LMDLP snapshot idempotent we add a unique constraint
--   on (eurio_id, source, quality, fetched_at) with NULLS NOT DISTINCT so a
--   NULL quality is treated as a single bucket per timestamp.

BEGIN;

ALTER TABLE coin_market_prices
  ADD COLUMN IF NOT EXISTS quality text;

COMMENT ON COLUMN coin_market_prices.quality IS
  'Numismatic quality bucket (UNC, BU FDC, BE Proof, BE Polissage inversé, …). '
  'NULL for sources that quote a market mix (eBay).';

-- Drop a previous lookup index that doesn't include quality.
DROP INDEX IF EXISTS idx_coin_market_prices_lookup;

CREATE INDEX IF NOT EXISTS idx_coin_market_prices_lookup
  ON coin_market_prices(eurio_id, source, quality, fetched_at DESC);

-- Idempotency for re-runs of the same snapshot. NULLS NOT DISTINCT so eBay
-- rows (quality IS NULL) collide on (eurio_id, source, fetched_at) just like
-- LMDLP rows do on (eurio_id, source, quality, fetched_at).
ALTER TABLE coin_market_prices
  DROP CONSTRAINT IF EXISTS coin_market_prices_snapshot_uniq;

ALTER TABLE coin_market_prices
  ADD CONSTRAINT coin_market_prices_snapshot_uniq
  UNIQUE NULLS NOT DISTINCT (eurio_id, source, quality, fetched_at);

COMMIT;
