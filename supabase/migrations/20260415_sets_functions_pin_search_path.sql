-- Follow-up to 20260415_sets_and_coins_enrichment.sql
-- Date: 2026-04-15
--
-- Remediation for Supabase advisor 0011_function_search_path_mutable:
-- pin search_path on the trigger functions created in the previous migration
-- to prevent search_path hijacking attacks.
--
-- See: https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable

CREATE OR REPLACE FUNCTION sets_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION set_members_enforce_curated_parent()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
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
$$;
