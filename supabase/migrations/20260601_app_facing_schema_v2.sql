-- 20260601_app_facing_schema_v2.sql
--
-- RESET v2 : Supabase devient la projection app-facing read-only de eurio.db.
-- Voir docs/research/supabase-app-schema-v2.md (ADR, décisions 2026-06-01).
--
-- Cette migration SUPERSEDE l'ensemble des migrations antérieures (squelette V1 +
-- V2-partiel issu du pipeline). Wipe total autorisé (dev single-user) puis création
-- du schéma cible. Les images du bucket Storage `coin-images` sont vidées hors
-- migration (DML storage, cf. note d'opération).
--
-- Décisions baked-in :
--   - caractéristiques physiques à plat sur `coin` (pas de blob)
--   - variantes = `coin` first-class (variant_kind + canonical_eurio_id) ; PAS de table
--     coin_variants enfant côté app
--   - provenance minimale : pas de source_ref crédits, pas de source topics, pas de
--     confidence i18n (la provenance reste dans eurio.db)
--   - prix : table unique `coin_price` dimensionnée par kind ('market'|'catalogue')
--   - images : avers unique dans Storage via `coin_image` ; côté commun via `shared_reverse`

-- ───────────────────────────────────────────────────────────────────────────
-- 1. WIPE — tables, fonctions, triggers de l'ancien schéma
-- ───────────────────────────────────────────────────────────────────────────

drop table if exists
  coin_aliases, coin_confusion_map, coin_embeddings, coin_market_prices,
  coin_mint_releases, coin_names_i18n, coin_series, coin_source_refs, coin_variants,
  coins, design_groups, matching_decisions, mint_release_prices, model_classes,
  review_queue, set_members, sets, sets_audit, source_observations, user_collections
  cascade;

drop function if exists
  coin_mint_releases_touch_updated_at(), coin_series_touch_updated_at(),
  coin_variants_touch_updated_at(), coins_set_source_flag(),
  design_groups_touch_updated_at(), model_classes_touch_updated_at(),
  rls_auto_enable(), set_members_enforce_curated_parent(), sets_touch_updated_at(),
  trg_coin_market_prices_set_flag(), trg_source_observations_set_flag()
  cascade;

-- ───────────────────────────────────────────────────────────────────────────
-- 2. CREATE — schéma app-facing v2
-- ───────────────────────────────────────────────────────────────────────────

-- Côté commun (carte/globe) partagé — catalogue packagé dans l'APK.
create table shared_reverse (
  id          text primary key,            -- ex: '2eur-map-v2'
  label       text not null,
  asset_name  text not null,               -- fichier packagé APK (ex: 'reverse_2eur_v2.webp')
  map_version int,                         -- 1 | 2
  applies_to  text                         -- doc de la règle (denomination/période)
);
comment on table shared_reverse is 'Côté commun partagé (carte). Packagé APK, résolu par règle (face_value, year>=2007). Cf ADR §3.';

-- Regroupement visuel canonique (re-issues annuelles + commémos jointes).
create table design_group (
  id                    text primary key,
  designation           text,
  designation_i18n_json jsonb
);
comment on table design_group is 'Groupes de design partagé (axe A annuel + axe B joint). Source: design_groups eurio.db.';

-- Ateliers de frappe.
create table mint (
  id           text primary key,           -- slug ex: 'de-berlin-a'
  country      text,
  mark         text,
  city         text,
  display_name text
);

-- Séries de circulation (vide au 1er passage, peuplé plus tard).
create table coin_series (
  id                    text primary key,
  country               text,
  designation           text,
  designation_i18n_json jsonb,
  minting_started_at    text,
  minting_ended_at      text,
  minting_end_reason    text,
  supersedes_series_id  text references coin_series(id) on delete set null
);

-- Identité + caractéristiques physiques à plat (1:1 figé).
create table coin (
  eurio_id            text primary key,
  country             text not null,        -- ISO2 ('FR', 'eu' joint)
  country_name        text,
  year                int  not null,
  face_value_cents    int  not null,        -- 200 = 2 €
  is_commemorative    boolean not null default false,
  collector_only      boolean not null default false,
  theme               text,                 -- observation Numista verbatim EN
  design_description  text,
  mintage             bigint,               -- type-level (drill-down: coin_mint_release)
  -- caractéristiques physiques (coin_observations aplati) :
  diameter_mm         real,
  weight_g            real,
  thickness_mm        real,
  composition         text,
  shape               text,
  orientation         text,                 -- 'medal' | 'coin'
  edge_description    text,
  edge_lettering      text,
  obverse_lettering   text,
  reverse_lettering   text,
  demonetized         boolean,
  demonetized_on      date,
  -- référentiel / variantes :
  design_group_id     text references design_group(id) on delete set null,
  variant_kind        text not null default 'classic',  -- classic|coloured|hologram|pattern|mule
  canonical_eurio_id  text references coin(eurio_id) on delete set null,  -- self-ref si variante
  series_id           text references coin_series(id) on delete set null,
  -- images :
  shared_reverse_id   text references shared_reverse(id) on delete set null,  -- côté commun (APK)
  updated_at          timestamptz not null default now()
);
comment on table coin is 'Identité + caractéristiques physiques à plat. Projection app-facing de eurio.db.coins + coin_observations. Avers via coin_image (eurio_id, role=obverse).';
create index idx_coin_country_year on coin(country, year);
create index idx_coin_face_value on coin(face_value_cents);
create index idx_coin_design_group on coin(design_group_id) where design_group_id is not null;
create index idx_coin_canonical on coin(canonical_eurio_id) where canonical_eurio_id is not null;

-- Avers unique (Supabase Storage, on-demand). Un avers par pièce.
create table coin_image (
  id           bigint generated always as identity primary key,
  eurio_id     text not null references coin(eurio_id) on delete cascade,
  role         text not null default 'obverse' check (role in ('obverse','reverse')),
  storage_path text not null,              -- chemin dans le bucket 'coin-images'
  source       text not null,             -- 'bce_official' | 'eurlex_jo' | 'numista_api'
  license      text,
  width        int,
  height       int,
  unique (eurio_id, role)
);
comment on table coin_image is 'Avers (côté national unique) hébergé dans Storage, fetch on-demand. Le côté commun est dans shared_reverse (packagé APK).';

-- Valeur (eBay) ET cote/achat (catalogue), par état.
create table coin_price (
  id          bigint generated always as identity primary key,
  eurio_id    text not null references coin(eurio_id) on delete cascade,
  kind        text not null check (kind in ('market','catalogue')),
  grade       text check (grade in ('UNC','TTB','TB')),  -- null = overall
  p_low       int,                         -- cents
  p_mid       int,                         -- cents
  p_high      int,                         -- cents
  currency    text not null default 'EUR',
  source      text not null,               -- 'ebay_browse' | 'numista_api' | 'lmdlp'
  buy_url     text,                         -- kind='catalogue' (achat neuf), nullable
  sampled_at  timestamptz not null
);
comment on table coin_price is 'kind=market = valeur eBay par état (affichage principal) ; kind=catalogue = cote/achat. Baseline offline = dernier market par (eurio_id, grade).';
create index idx_coin_price_lookup on coin_price(eurio_id, kind, grade);

-- Titres localisés (FR+EN packagés offline ; autres langues = packs téléchargeables).
create table coin_name_i18n (
  eurio_id text not null references coin(eurio_id) on delete cascade,
  lang     text not null,
  title    text not null,
  primary key (eurio_id, lang)
);

-- Descriptions localisées (BCE 24 langs ; FR+EN packagés offline).
create table coin_description_i18n (
  eurio_id    text not null references coin(eurio_id) on delete cascade,
  lang        text not null,
  title       text not null,
  description text,
  primary key (eurio_id, lang)
);

-- Crédits (designers / graveurs).
create table coin_credit (
  id       bigint generated always as identity primary key,
  eurio_id text not null references coin(eurio_id) on delete cascade,
  role     text not null,                  -- designer | engraver | sculptor
  name     text not null,
  position int
);
create index idx_coin_credit_eurio on coin_credit(eurio_id);

-- Topics / thématiques.
create table coin_topic (
  id       bigint generated always as identity primary key,
  eurio_id text not null references coin(eurio_id) on delete cascade,
  lang     text not null,
  topic    text not null
);
create index idx_coin_topic_eurio on coin_topic(eurio_id);

-- Émission par atelier × année × format de frappe.
create table coin_mint_release (
  id             text primary key,
  parent_type_id text not null references coin(eurio_id) on delete cascade,
  mint_year      int,
  mint_id        text references mint(id) on delete set null,
  issue_type     text,                     -- CIRC|BU|BE|PROOF|COIN_CARD|OTHER
  mintage        bigint
);
create index idx_coin_mint_release_parent on coin_mint_release(parent_type_id);

-- Sets / achievements (vides au 1er passage, app-facing).
create table sets (
  id              text primary key,
  kind            text,
  name_i18n       jsonb,
  description_i18n jsonb,
  criteria        jsonb,
  param_key       text,
  reward          jsonb,
  display_order   int,
  category        text,
  icon            text,
  expected_count  int,
  active          boolean not null default true
);
create table set_members (
  set_id   text not null references sets(id) on delete cascade,
  eurio_id text not null references coin(eurio_id) on delete cascade,
  position int,
  primary key (set_id, eurio_id)
);

-- ───────────────────────────────────────────────────────────────────────────
-- 3. RLS — lecture publique (app via clé anon), écriture service_role seulement
-- ───────────────────────────────────────────────────────────────────────────

do $$
declare t text;
begin
  foreach t in array array[
    'shared_reverse','design_group','mint','coin_series','coin','coin_image',
    'coin_price','coin_name_i18n','coin_description_i18n','coin_credit','coin_topic',
    'coin_mint_release','sets','set_members'
  ] loop
    execute format('alter table %I enable row level security;', t);
    execute format(
      'create policy %I on %I for select to anon, authenticated using (true);',
      t || '_read', t);
  end loop;
end $$;
