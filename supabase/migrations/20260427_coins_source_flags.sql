-- Migration: coins source flags + maintenance triggers
-- Date: 2026-04-27
--
-- Context:
--   The /coins admin needs cumulative source filters (Numista, BCE, Wikipedia,
--   LMDLP, eBay). The first cut filtered client-side by intersecting the
--   eurio_id sets per source, then issuing `coins?eurio_id=in.(<thousands>)`,
--   which blew past the URL length limit. Fix: pre-compute boolean flags on
--   `coins` so the query is a trivial `.eq('has_bce', true)` etc.
--
--   Numista already has a usable cross_refs->>numista_id filter and doesn't
--   need its own column.
--   eBay rows live in coin_market_prices (not source_observations) so it gets
--   its own trigger source.

ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS has_bce        boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS has_wikipedia  boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS has_lmdlp      boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS has_ebay       boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_coins_has_bce       ON coins(eurio_id) WHERE has_bce;
CREATE INDEX IF NOT EXISTS idx_coins_has_wikipedia ON coins(eurio_id) WHERE has_wikipedia;
CREATE INDEX IF NOT EXISTS idx_coins_has_lmdlp     ON coins(eurio_id) WHERE has_lmdlp;
CREATE INDEX IF NOT EXISTS idx_coins_has_ebay      ON coins(eurio_id) WHERE has_ebay;

-- Backfill from current state.
UPDATE coins c SET
  has_bce       = EXISTS(SELECT 1 FROM source_observations o
                         WHERE o.eurio_id = c.eurio_id AND o.source = 'bce_comm'),
  has_wikipedia = EXISTS(SELECT 1 FROM source_observations o
                         WHERE o.eurio_id = c.eurio_id AND o.source = 'wikipedia'),
  has_lmdlp     = EXISTS(SELECT 1 FROM source_observations o
                         WHERE o.eurio_id = c.eurio_id AND o.source = 'lmdlp'),
  has_ebay      = EXISTS(SELECT 1 FROM coin_market_prices m
                         WHERE m.eurio_id = c.eurio_id AND m.source = 'ebay');

CREATE OR REPLACE FUNCTION coins_set_source_flag(_eurio_id text, _source text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  IF _source = 'bce_comm' THEN
    UPDATE coins SET has_bce = true WHERE eurio_id = _eurio_id AND has_bce = false;
  ELSIF _source = 'wikipedia' THEN
    UPDATE coins SET has_wikipedia = true WHERE eurio_id = _eurio_id AND has_wikipedia = false;
  ELSIF _source = 'lmdlp' THEN
    UPDATE coins SET has_lmdlp = true WHERE eurio_id = _eurio_id AND has_lmdlp = false;
  ELSIF _source = 'ebay' THEN
    UPDATE coins SET has_ebay = true WHERE eurio_id = _eurio_id AND has_ebay = false;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION trg_source_observations_set_flag() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM coins_set_source_flag(NEW.eurio_id, NEW.source);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION trg_coin_market_prices_set_flag() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM coins_set_source_flag(NEW.eurio_id, NEW.source);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS source_observations_set_flag ON source_observations;
CREATE TRIGGER source_observations_set_flag
  AFTER INSERT OR UPDATE ON source_observations
  FOR EACH ROW EXECUTE FUNCTION trg_source_observations_set_flag();

DROP TRIGGER IF EXISTS coin_market_prices_set_flag ON coin_market_prices;
CREATE TRIGGER coin_market_prices_set_flag
  AFTER INSERT OR UPDATE ON coin_market_prices
  FOR EACH ROW EXECUTE FUNCTION trg_coin_market_prices_set_flag();

COMMENT ON COLUMN coins.has_bce       IS 'True iff a source_observations row with source = bce_comm exists. Maintained by trigger.';
COMMENT ON COLUMN coins.has_wikipedia IS 'True iff a source_observations row with source = wikipedia exists. Maintained by trigger.';
COMMENT ON COLUMN coins.has_lmdlp     IS 'True iff a source_observations row with source = lmdlp exists. Maintained by trigger.';
COMMENT ON COLUMN coins.has_ebay      IS 'True iff a coin_market_prices row with source = ebay exists. Maintained by trigger.';
