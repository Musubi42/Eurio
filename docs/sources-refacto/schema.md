# Schéma DB cible

> DDL des deux nouvelles tables, conventions `source_ref`, valeurs
> autorisées de `source` / `license` / `variant_kind`.

## Principes

1. **Séparation stricte** du référentiel canonique (table `coins`,
   `coin_images` côté Supabase). Les nouvelles tables n'écrasent
   jamais le référentiel — elles s'ajoutent.
2. **Pas de cross-source averaging.** Chaque row porte un `source`.
   Toute agrégation se fait à la lecture, jamais à l'écriture.
3. **Dédup intra-source** uniquement, via `(source, source_ref)`.
4. **`raw_payload` jsonb** systématique pour audit et re-derivation
   sans refetch.

## Table `image_assets`

```sql
create table image_assets (
  id              uuid primary key default gen_random_uuid(),

  -- Identité
  eurio_id        text not null,                    -- FK logique vers le label space lab
  source          text not null,                    -- enum: cf. valeurs autorisées
  source_ref      text not null,                    -- identifiant unique de l'image dans la source
                                                    -- ex: 'ebay_listing_<itemId>_img0'
                                                    --     'catawiki_lot_<lotId>_img2'
                                                    --     'numista_<numistaId>_obverse'

  -- Sémantique image
  face            text,                             -- 'obverse' | 'reverse' | 'pair' | 'unknown'
  variant_kind    text not null,                    -- cf. valeurs autorisées

  -- Qualité (cf. quality-pipeline.md)
  quality_score        real,                        -- 0.0-1.0
  training_eligible    boolean not null default false,
  quality_reason       text,                        -- 'low_sharpness' | 'no_coin_detected' | …

  -- License & redistribution
  license              text not null,               -- cf. valeurs autorisées
  redistributable      boolean not null default false,

  -- Stockage
  storage_path         text not null,               -- 'ml/datasets/sources/<source>/<eurio_id>/<hash>.jpg'
  width                integer,
  height               integer,
  bytes                integer,

  -- Provenance temporelle
  captured_at          timestamptz,                 -- date de l'image côté source si dispo
  fetched_at           timestamptz not null default now(),

  -- Audit
  raw_payload          jsonb,                       -- payload brut de la source (URL, listing meta, etc.)
  run_id               uuid references source_runs(id),

  unique (source, source_ref)
);

create index image_assets_eurio_id_idx on image_assets(eurio_id);
create index image_assets_source_idx on image_assets(source);
create index image_assets_training_eligible_idx
  on image_assets(training_eligible)
  where training_eligible = true;
```

### `source` — valeurs autorisées

| Valeur | Type | Note |
|---|---|---|
| `numista` | API | canonical obverse/reverse |
| `ebay` | API | listings actifs (Browse API) |
| `ebay_sold` | API | sold listings (Marketplace Insights, futur) |
| `lmdlp` | scrape | La Maison de la Pièce |
| `mdp` | scrape | Monnaie de Paris officiel |
| `bce` | scrape | annonces commémo BCE |
| `wikipedia` | scrape | pages catalogue par pays |
| `catawiki` | scrape | enchères |
| `numiscorner` | scrape | marchand pro |
| `cgb` | scrape | marchand FR pro |

Une nouvelle source = une nouvelle valeur. Pas d'enum SQL strict pour ne
pas avoir à migrer à chaque ajout — on valide côté Python via
`ml/sources/_base/sources_registry.py`.

### `variant_kind` — valeurs autorisées

| Valeur | Sémantique | Sources typiques |
|---|---|---|
| `canonical` | photo de référence propre, fond neutre | numista |
| `official_press` | photo officielle haute qualité | mdp, bce, wikipedia |
| `merchant_catalog` | photo marchand pro, fond contrôlé | numiscorner, cgb, lmdlp |
| `auction_listing` | photo enchère, qualité variable | catawiki, ebay |
| `in_hand` | tenue main, contexte non contrôlé | ebay, catawiki (sous-cas) |
| `macro` | gros plan détaillé | catawiki haut de gamme, cgb |
| `reverse_only` | spécifique reverse | numista |
| `unknown` | non classifié encore | par défaut au fetch |

`variant_kind` peut être affiné par le quality-pipeline après fetch
(ex: `auction_listing` → `in_hand` si confiance haute).

### `license` — valeurs autorisées

| Valeur | Redistribuable ? | Usage |
|---|---|---|
| `numista_api` | ❌ | usage ML interne, ToS Numista |
| `public_domain` | ✅ | wikipedia commons, BCE certain cas |
| `cc_by` | ✅ avec attribution | wikipedia commons certain cas |
| `fair_use_research` | ❌ | catawiki, ebay, numiscorner, cgb — training only |
| `editorial_official` | partielle | mdp, bce officielles, à clarifier |
| `unknown` | ❌ | par défaut, à requalifier |

`redistributable` est dérivé de `license` au moment du fetch et figé.

## Table `coin_market_quotes`

```sql
create table coin_market_quotes (
  id              uuid primary key default gen_random_uuid(),

  -- Identité
  eurio_id        text not null,
  source          text not null,                    -- 'ebay_active' | 'lmdlp' | 'numiscorner' | …

  -- Condition (cf. note plus bas)
  condition_raw           text,                     -- string brute telle que la source la donne
  condition_normalized    text,                     -- enum optionnelle: 'UNC'|'BU'|'FDC'|'XF'|'VF'|'F'|'circulated'|'unknown'

  -- Distribution prix
  currency        text not null default 'EUR',
  p10             numeric,
  p50             numeric,                          -- toujours présent
  p90             numeric,
  sample_size     integer not null default 1,       -- 1 si cotation marchand unique, n si agrégat

  -- Période d'observation
  period_start    timestamptz not null,
  period_end      timestamptz not null,

  -- Audit
  fetched_at      timestamptz not null default now(),
  raw_payload     jsonb,
  run_id          uuid references source_runs(id),

  unique (source, eurio_id, period_start, condition_normalized)
);

create index coin_market_quotes_eurio_idx on coin_market_quotes(eurio_id);
create index coin_market_quotes_source_idx on coin_market_quotes(source);
create index coin_market_quotes_period_idx on coin_market_quotes(period_start desc);
```

### Sur `condition`

- **Brute** : telle que la source la déclare. CGB peut donner "FDC",
  eBay listing peut donner "Mint, Uncirculated, BU", LMDLP "neuf".
- **Normalisée** : enum simplifiée pour les requêtes admin/app, mappée
  par une table de correspondance versionnée
  (`ml/sources/_base/condition_map.py`).
- Ne pas perdre la brute : un grade CGB fin (SUP-58 vs SUP-62) est
  utile en analyse même si l'enum les regroupe.

### `source` côté quotes vs images

Les valeurs ne sont **pas identiques** :
- `image_assets.source = 'ebay'` couvre listings actifs et sold
  indistinctement (ce qui compte c'est l'image).
- `coin_market_quotes.source = 'ebay_active'` vs `'ebay_sold'` car
  c'est sémantiquement différent pour les prix.

## Table `source_runs`

```sql
create table source_runs (
  id              uuid primary key default gen_random_uuid(),
  source          text not null,
  kind            text not null,                    -- 'run' | 'dry' | 'limit' | 'reset'
  started_at      timestamptz not null default now(),
  ended_at        timestamptz,
  status          text not null default 'running',  -- 'running' | 'success' | 'failed' | 'partial'

  -- Volumes
  n_calls         integer default 0,
  n_images_added  integer default 0,
  n_quotes_added  integer default 0,
  n_errors        integer default 0,

  -- Filtres run-spécifiques
  filters         jsonb,                            -- {countries: ['FR','DE'], limit: 5, …}

  -- Logs / erreurs
  log_path        text,
  error_summary   text
);

create index source_runs_source_started_idx on source_runs(source, started_at desc);
```

C'est cette table qui alimente l'onglet **Runs** de la page admin
détail et les badges "dernier run" sur les cards.

## Migration

- Les tables s'ajoutent, rien ne casse côté `coins` / `coin_images` /
  `coin_market_prices` existants.
- `coin_market_prices` legacy : on **n'y touche pas** dans cette
  refacto. Une fois `coin_market_quotes` rempli pour eBay, on
  bascule la lecture admin/app et on archive l'ancienne table dans
  un refacto séparé.
- Pas de backfill historique des images Numista existantes vers
  `image_assets`. Les nouveaux fetchs y vont, les anciens restent
  dans `coin_images`. Optionnel : un script one-shot
  `ml:src:numista:backfill-image-assets` pour exposer le canonique
  Numista existant via le nouveau contrat.

## Conventions `source_ref`

Doit être **stable** (un re-fetch produit la même valeur) et **unique
intra-source**. Recommandations :

| Source | Pattern |
|---|---|
| numista | `numista_<numistaId>_<face>` |
| ebay | `ebay_listing_<itemId>_img<index>` |
| catawiki | `catawiki_lot_<lotId>_img<index>` |
| numiscorner | `numiscorner_<sku>_img<index>` |
| cgb | `cgb_<reference>_img<index>` |
| mdp | `mdp_<slug>_img<index>` |
| bce | `bce_<year>_<countryCode>_img<index>` |
| wikipedia | `wikipedia_<pageId>_<filenameSlug>` |
| lmdlp | `lmdlp_<slug>_img<index>` |

Le `<index>` permet d'avoir plusieurs images par listing/lot sans
collision. Si la source n'expose qu'une image, `<index>=0`.
