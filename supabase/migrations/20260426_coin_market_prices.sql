-- Migration: coin_market_prices — historical market price observations
-- Date: 2026-04-26
--
-- Context:
--   Stores periodic eBay market price snapshots (P25/P50/P75) per coin.
--   Each scrape_ebay.py run INSERTs a new row (never upserts) to preserve
--   the full time series. The admin reads the most recent row via
--   DISTINCT ON (eurio_id, source) ORDER BY fetched_at DESC.
--
--   Only 2€ commemoratives are targeted initially (see ml/ib/ebay-market-prices.md).
--   fetched_at is the canonical observation date — it represents when we
--   observed the active market, not the listing publication date.

BEGIN;

CREATE TABLE IF NOT EXISTS coin_market_prices (
  id               bigserial    PRIMARY KEY,
  eurio_id         text         NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source           text         NOT NULL,
  p25              numeric(8,2),
  p50              numeric(8,2),
  p75              numeric(8,2),
  samples_count    int,
  with_sales_count int,
  query_used       text,
  fetched_at       timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coin_market_prices_lookup
  ON coin_market_prices(eurio_id, source, fetched_at DESC);

COMMENT ON TABLE coin_market_prices IS
  'Time series of market price observations per coin. One row per scrape run, never overwritten.';

COMMENT ON COLUMN coin_market_prices.fetched_at IS
  'Timestamp of the observation run (when we queried the market), not the listing date.';

ALTER TABLE coin_market_prices ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read coin_market_prices"
  ON coin_market_prices FOR SELECT
  USING (true);

COMMIT;
