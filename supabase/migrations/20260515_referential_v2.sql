-- Migration: referential V2 — variants, mint releases, multi-source refs
-- Date: 2026-05-15
-- Refs:
--   docs/research/referential-v2.md (canonique : décisions D1–D8)
--   ml/datasets/audit_referential_v2.json (audit qui a déclenché V2)
--
-- Context
-- -------
-- Le référentiel V1 (table `coins`) modélise une pièce comme un identifiant
-- unique `eurio_id` agrégeant design + finition + format. L'audit 2026-05-15
-- a montré 132 groupes Numista sous-représentés, 159 entrées 2€ "perdues",
-- 58 matchings sémantiquement faux. Plus le besoin produit (P2P trading,
-- 10€ MdP collector, multi-source) dépasse Numista-pivot.
--
-- V2 introduit un modèle à 3 niveaux :
--   TYPE          = la pièce canonique (= table `coins`, conservée telle quelle)
--   VARIANT       = finition graphique du même type (coloured, hologram, …)
--   MINT_RELEASE  = format de frappe (BU/BE/PROOF/CIRC) × année × atelier
-- + SOURCE_REFS   = relation many-to-many entre Type et (source, native_id)
--   pour l'ingestion multi-référentielle (Numista, MdP, BCE, Catawiki, …).
--
-- Cette migration est **strictement additive** (aucun DROP, aucune modif de
-- `coins`). Les tables existantes (`coin_market_prices`, `set_members`, …)
-- continuent de référencer `coins.eurio_id` sans changement. La table `coins`
-- est désormais documentée comme « niveau Type » du modèle V2.
--
-- Apply via: mcp__supabase__apply_migration (ou Supabase SQL editor).

BEGIN;

-- =============================================================================
-- 0. Mise à jour conceptuelle de `coins`
-- =============================================================================
-- Pas de changement de structure. On documente le rôle V2 de la table.

COMMENT ON TABLE coins IS
  'Niveau TYPE du référentiel V2. Une ligne = une pièce canonique (design + pays + année + denomination). Les finitions graphiques (coloured, hologram, …) vivent dans coin_variants. Les formats de frappe (BU/BE/PROOF) vivent dans coin_mint_releases. Les références externes multi-sources (Numista, MdP, BCE, …) vivent dans coin_source_refs. Schéma intact pour compat V1 (snapshot Android, eBay scrape, sets). Voir docs/research/referential-v2.md.';


-- =============================================================================
-- 1. coin_variants — finition graphique d'un Type
-- =============================================================================
-- Convention :
--   id = `{parent_eurio_id}/{finish}` quand unique
--   id = `{parent_eurio_id}/{finish}-{seq}` quand le même type a plusieurs
--        variants avec la même finition (ex Bleuet 2018 : 2 colored distincts)
--   seq démarre à 1 et n'apparaît que sur collision (géré côté script de population).
--
-- Tout Type a au minimum un variant logique "classic" — il est matérialisé en
-- ligne dans cette table dès qu'il a au moins 1 variant non-classic (sinon il
-- reste implicite et représenté par les obverse/reverse de `coins`).

CREATE TABLE IF NOT EXISTS coin_variants (
  id              text PRIMARY KEY,
  parent_type_id  text NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  finish          text NOT NULL CHECK (finish IN (
    'classic',      -- standard / circulation finish
    'coloured',     -- single or multi-colour print
    'hologram',     -- holographic insert / coating
    'gilded',       -- gold-plated
    'pattern',      -- pattern / essai / pre-production
    'mule',         -- mismatched obverse/reverse strike
    'misstrike',    -- off-center / clipped planchet / etc.
    'other'         -- escape hatch, justify in `notes`
  )),
  obverse_url     text,                                        -- spécifique au variant si différent du type
  reverse_url     text,
  notes           text,                                        -- justification finish='other', détails Numista, …
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coin_variants_parent
  ON coin_variants(parent_type_id);

CREATE INDEX IF NOT EXISTS idx_coin_variants_finish
  ON coin_variants(finish);

COMMENT ON TABLE coin_variants IS
  'Niveau VARIANT du référentiel V2. Finitions graphiques d''un Type (coloured, hologram, gilded, pattern, mule). PAS pour les formats de frappe (BU/BE/PROOF) qui vivent dans coin_mint_releases.';
COMMENT ON COLUMN coin_variants.id IS
  'Slug `{parent_eurio_id}/{finish}` ou `{parent_eurio_id}/{finish}-{seq}` si collision (ex Bleuet 2018 : 2 colored distincts).';
COMMENT ON COLUMN coin_variants.finish IS
  'Type de finition. Décision D4 du doc V2 : coloured/hologram/gilded/pattern/mule/misstrike = variant.finish. BU/BE/PROOF = coin_mint_releases.issue_type, pas ici.';


CREATE OR REPLACE FUNCTION coin_variants_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS coin_variants_touch_updated_at ON coin_variants;
CREATE TRIGGER coin_variants_touch_updated_at
  BEFORE UPDATE ON coin_variants
  FOR EACH ROW
  EXECUTE FUNCTION coin_variants_touch_updated_at();


-- =============================================================================
-- 2. coin_mint_releases — émission par atelier × année × format
-- =============================================================================
-- Convention :
--   id = `{parent_eurio_id}/{mint_year}-{issue_type}` quand unique
--   id = `{parent_eurio_id}/{mint_year}-{issue_type}-{mint_mark}` si atelier
--        distingue (ex DE 1c "A"/"D"/"F"/"G"/"J")
--
-- Utile pour modéliser :
--   - FR 2024 JO Paris en BU vs BE (Numista distingue ces tirages)
--   - Cents allemands frappés dans plusieurs ateliers la même année
--   - Pièces post-millésime ré-émises (rare)

CREATE TABLE IF NOT EXISTS coin_mint_releases (
  id              text PRIMARY KEY,
  parent_type_id  text NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  mint_year       int  NOT NULL,
  mint_mark       text,                                        -- 'A','D','F','G','J' pour DE — null si N/A
  issue_type      text NOT NULL CHECK (issue_type IN (
    'CIRC',         -- circulation standard
    'BU',           -- Brilliant Uncirculated
    'BE',           -- Belle Épreuve (Proof FR)
    'PROOF',        -- Proof international
    'COIN_CARD',    -- conditionné dans coin card
    'OTHER'
  )),
  mintage         bigint,                                      -- tirage si connu
  released_on     date,
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coin_mint_releases_parent
  ON coin_mint_releases(parent_type_id);

CREATE INDEX IF NOT EXISTS idx_coin_mint_releases_year
  ON coin_mint_releases(parent_type_id, mint_year);

COMMENT ON TABLE coin_mint_releases IS
  'Niveau MINT_RELEASE du référentiel V2. Émission d''un Type par atelier × année × format de frappe. Capture BU/BE/PROOF (qualité de frappe) sans changer le design. Voir D4 du doc V2.';
COMMENT ON COLUMN coin_mint_releases.issue_type IS
  'CIRC=circulation, BU=Brilliant Uncirculated, BE=Belle Épreuve (Proof FR), PROOF=Proof international, COIN_CARD=conditionné. NE PAS confondre avec coins.issue_type (V1 hybride qui sera désaffecté progressivement).';
COMMENT ON COLUMN coin_mint_releases.mint_mark IS
  'Marque d''atelier. NULL pour les pays sans marque (la plupart des 2€ commémos). A/D/F/G/J pour Allemagne (cents).';


CREATE OR REPLACE FUNCTION coin_mint_releases_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS coin_mint_releases_touch_updated_at ON coin_mint_releases;
CREATE TRIGGER coin_mint_releases_touch_updated_at
  BEFORE UPDATE ON coin_mint_releases
  FOR EACH ROW
  EXECUTE FUNCTION coin_mint_releases_touch_updated_at();


-- =============================================================================
-- 3. coin_source_refs — relation many-to-many Type × source
-- =============================================================================
-- Remplace progressivement le JSON `coins.cross_refs` et le tableau
-- `coins.sources_used`. Décision D2 : multi-référentiel additif, plusieurs
-- sources peuvent déclarer le même Type, chacune avec son propre native_id.
--
-- Granularité : par défaut on attache au Type. Si une source distingue déjà
-- les variants/releases natifs (ex Numista qui a un nid par variant
-- coloured/hologram), on peut ajouter target_kind ultérieurement. Pour V2
-- initial, on reste 1:N (Type ↔ sources), suffisant pour 95% des cas.

CREATE TABLE IF NOT EXISTS coin_source_refs (
  id              bigserial PRIMARY KEY,
  coin_type_id    text NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source          text NOT NULL CHECK (source IN (
    'numista',
    'mdp',           -- Monnaie de Paris (officielle FR)
    'lmdlp',         -- La Maison de la Pièce (cotation FR)
    'bce',           -- Banque Centrale Européenne (annonces commémo)
    'wikipedia',
    'catawiki',
    'wikidata',
    'ngc',           -- NGC Coin Explorer
    'pcgs',          -- PCGS CoinFacts
    'joue',          -- Journal Officiel UE
    'other'
  )),
  native_id       text NOT NULL,                               -- ID natif côté source
  native_url      text,                                        -- URL canonique de la fiche
  fetched_at      timestamptz NOT NULL DEFAULT now(),
  -- (coin_type_id, source, native_id) doit être unique : un même Type ne peut
  -- pas être référencé deux fois par la même source avec le même native_id.
  -- En revanche un même native_id peut couvrir plusieurs Types (cas typique :
  -- URL Wikipedia d'une page pays référençant N pièces du pays).
  UNIQUE (coin_type_id, source, native_id)
);

CREATE INDEX IF NOT EXISTS idx_coin_source_refs_type
  ON coin_source_refs(coin_type_id);

CREATE INDEX IF NOT EXISTS idx_coin_source_refs_source
  ON coin_source_refs(source, fetched_at DESC);

COMMENT ON TABLE coin_source_refs IS
  'Relation many-to-many entre coins (Types V2) et leurs identifiants natifs dans les sources externes. Décision D2 du doc V2 : multi-référentiel additif. Remplace progressivement coins.cross_refs JSON et coins.sources_used array.';
COMMENT ON COLUMN coin_source_refs.source IS
  'Identifiant de la source. Whitelist par CHECK constraint pour traçabilité. Pour ajouter une source : étendre l''enum dans une nouvelle migration.';
COMMENT ON COLUMN coin_source_refs.native_id IS
  'ID natif côté source. Ex pour numista: "102697". Pour mdp: SKU produit. Pour wikidata: Q-id.';


-- =============================================================================
-- 4. Row Level Security
-- =============================================================================
-- Pattern aligné avec design_groups et coin_market_prices :
--   - public read sur les 3 tables (référentiel partagé)
--   - admin write only

ALTER TABLE coin_variants       ENABLE ROW LEVEL SECURITY;
ALTER TABLE coin_mint_releases  ENABLE ROW LEVEL SECURITY;
ALTER TABLE coin_source_refs    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS coin_variants_public_read ON coin_variants;
CREATE POLICY coin_variants_public_read ON coin_variants
  FOR SELECT USING (true);

DROP POLICY IF EXISTS coin_variants_admin_all ON coin_variants;
CREATE POLICY coin_variants_admin_all ON coin_variants
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

DROP POLICY IF EXISTS coin_mint_releases_public_read ON coin_mint_releases;
CREATE POLICY coin_mint_releases_public_read ON coin_mint_releases
  FOR SELECT USING (true);

DROP POLICY IF EXISTS coin_mint_releases_admin_all ON coin_mint_releases;
CREATE POLICY coin_mint_releases_admin_all ON coin_mint_releases
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

DROP POLICY IF EXISTS coin_source_refs_public_read ON coin_source_refs;
CREATE POLICY coin_source_refs_public_read ON coin_source_refs
  FOR SELECT USING (true);

DROP POLICY IF EXISTS coin_source_refs_admin_all ON coin_source_refs;
CREATE POLICY coin_source_refs_admin_all ON coin_source_refs
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');


COMMIT;

-- =============================================================================
-- Notes post-migration
-- =============================================================================
-- 1. Aucune ligne n'est insérée par cette migration. La population se fait via
--    ml/referential/migrate_to_v2.py (Chunk 2c) en mode --dry-run d'abord.
-- 2. coin_market_prices reste attaché à coins.eurio_id (= Type). L'extension
--    polymorphe (target_kind/target_id, D8) sera traitée dans une migration
--    future quand le besoin variant/specimen pricing arrivera.
-- 3. coins.cross_refs JSON et coins.sources_used array sont conservés tels
--    quels en V2.0. Désaffectation progressive : V2.1 read-from-both,
--    V2.2 write-only-to-source_refs, V2.3 drop des colonnes JSON.
-- 4. La table `coin_specimens` (P2P trading, grading UNC/TTB/TB) n'est PAS
--    créée ici. Elle arrivera quand la feature trading démarre.
