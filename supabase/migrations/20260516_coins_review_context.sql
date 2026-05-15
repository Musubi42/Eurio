-- Migration: coins review context (review queue UI backing)
-- Date: 2026-05-16
-- Refs:
--   docs/research/referential-v2-progress.md §3e (review queue)
--   docs/research/referential-v2.md §3.3 (Type Review Queue, frontière)
--
-- Context
-- -------
-- Les chunks 3b / 3d / 3e.1 ont flagé 32 coins avec `needs_review = true` +
-- `review_reason` (texte libre). Cette information textuelle ne suffit pas à
-- piloter une UI : il faut un hint d'action ('rebind' / 'verify_parent' /
-- 'confirm_or_rematch_uncertain') et un payload structuré contenant le
-- contexte (nid suspect, member variants, audit-derived candidates).
--
-- Cette migration ajoute 2 colonnes au `coins` :
--   review_action_hint TEXT   — workflow hint pour l'UI admin
--   review_payload     JSONB  — contexte structuré (nids, catalog names, etc.)
--
-- Le contrat exact du payload est documenté par `apply_3e_enrich_context.py`
-- qui est la seule source qui peuple ces colonnes. La progression de la
-- review queue est trackée via `needs_review = true` (existant) ; quand
-- l'humain résout un cas, l'UI clear les 4 colonnes (`needs_review`,
-- `review_reason`, `review_action_hint`, `review_payload`) en une seule
-- PATCH.
--
-- Idempotence : ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
-- Apply via: mcp__supabase__apply_migration

BEGIN;

ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS review_action_hint TEXT
    CHECK (review_action_hint IS NULL OR review_action_hint IN (
      'rebind',
      'verify_parent',
      'confirm_or_rematch_uncertain'
    )),
  ADD COLUMN IF NOT EXISTS review_payload JSONB;

COMMENT ON COLUMN coins.review_action_hint IS
  'Workflow hint pour la review queue admin (chunk 3e). One of: rebind | verify_parent | confirm_or_rematch_uncertain. NULL = pas dans la queue.';

COMMENT ON COLUMN coins.review_payload IS
  'Contexte structuré pour l''UI review : audit-derived nids, catalog names, member variants, suggested rematches. Schéma documenté dans ml/referential/apply_3e_enrich_context.py.';

-- Index partiel pour servir la queue UI rapidement (32 rows actuels, jusqu'à
-- quelques centaines dans le futur — l'index reste petit).
CREATE INDEX IF NOT EXISTS idx_coins_needs_review
  ON coins(needs_review)
  WHERE needs_review = true;

CREATE INDEX IF NOT EXISTS idx_coins_review_action_hint
  ON coins(review_action_hint)
  WHERE review_action_hint IS NOT NULL;

COMMIT;
