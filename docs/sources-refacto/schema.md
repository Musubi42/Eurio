# Schéma DB cible

> DDL des tables ajoutées par cette refacto. Toutes vivent dans
> SQLite (`ml/state/training.db`) côté Mac dev. Voir `decisions.md`
> D-05 et D-06.
>
> **Avant de lire ce fichier**, lire `decisions.md` — toutes les
> contraintes (`eurio_id` nullable, split image/source, multi-coin,
> pHash, etc.) sont actées là.

## Principes

1. **Séparation stricte** du référentiel canonique. `coins` et
   `coin_images` Supabase ne sont pas modifiés.
2. **Pas de cross-source averaging** — chaque row porte un `source`,
   l'agrégation est lecture-only.
3. **Dédup intra-source** via `(source, source_ref)`, plus dédup
   intra/cross via `pHash`.
4. **Ingestion non destructive** — `eurio_id` peut être NULL le temps
   d'une résolution. Aucun delete auto.
5. **`raw_payload` jsonb** systématique pour audit / re-derivation.

## Vue d'ensemble des tables

| Table | Rôle | `eurio_id` |
|---|---|---|
| `source_images` | 1 row par fichier physique téléchargé (le "raw") | facultatif (héritage par défaut depuis le contexte du fetch quand cible précise, sinon NULL) |
| `image_assets` | 1 row par crop pièce dérivé d'un raw | nullable, résolu plus tard |
| `coin_market_quotes` | 1 row par cotation marché par condition × période | NOT NULL |
| `pending_quotes` | Quotes en attente que l'image associée soit résolue | NULL toléré, promu vers `coin_market_quotes` à la résolution |
| `review_queue` | File de revue humaine pour les `image_assets` non résolus | NULL par construction |
| `source_runs` | Logs des runs par source | n/a |

## Table `source_images` (raw)

```sql
create table source_images (
  id              uuid primary key default gen_random_uuid(),

  -- Identité source
  source          text not null,
  source_ref      text not null,                    -- 'ebay_listing_<itemId>' (sans index image)
  source_url      text,                             -- URL source du listing/lot

  -- Lien optionnel à un eurio_id "ciblé" : quand le fetch est dirigé
  -- (ex: scrape_ebay sur eurio_id=BE-2EUR-2002), on note la cible
  -- attendue, ce qui aide la résolution. NULL si fetch non ciblé.
  target_eurio_id  text,

  -- Métadonnées listing (optionnelles)
  listing_title   text,
  listing_country text,                             -- ISO2 si extrait
  listing_year    integer,
  listing_price   numeric,                          -- prix global du listing/lot (peut ≠ prix par pièce)
  listing_currency text default 'EUR',
  condition_raw   text,
  seller_id       text,                             -- pour stats / dedup vendeur

  -- Stockage du fichier raw
  storage_path    text not null,                    -- 'ml/datasets/sources/<source>/<source_ref>/raw_<hash>.jpg'
  width           integer,
  height          integer,
  bytes           integer,
  sha256          text,

  -- Provenance & audit
  license         text not null,
  redistributable boolean not null default false,
  fetched_at      timestamptz not null default now(),
  raw_payload     jsonb,
  run_id          uuid references source_runs(id),

  unique (source, source_ref)
);

create index source_images_target_idx on source_images(target_eurio_id);
create index source_images_source_idx on source_images(source);
create index source_images_run_idx on source_images(run_id);
```

## Table `image_assets` (crops)

```sql
create table image_assets (
  id              uuid primary key default gen_random_uuid(),

  -- Lien vers le raw parent
  source_image_id uuid not null references source_images(id) on delete cascade,
  crop_index      integer not null default 0,       -- 0..N-1, ordre des crops dans le raw

  -- Géométrie du crop dans le raw
  bbox            jsonb,                            -- {x, y, w, h, conf}
  detection_method text,                            -- 'yolo' | 'hough' | 'merged' | 'manual'

  -- Résolution vers eurio_id (nullable, voir D-02)
  eurio_id            text,
  resolution_status   text not null default 'pending_match',
                                                    -- 'pending_crop' | 'pending_match'
                                                    -- | 'auto_name' | 'auto_phash'
                                                    -- | 'needs_review' | 'manual' | 'rejected'
  resolution_confidence  real,                      -- 0..1
  resolution_attempts    jsonb,                     -- log des étapes tentées
  candidate_eurio_ids    jsonb,                     -- top-K avec scores, pour la review UI

  -- Sémantique image
  face            text,                             -- 'obverse' | 'reverse' | 'unknown'
  variant_kind    text not null default 'unknown',
                                                    -- 'canonical' | 'official_press' | 'merchant_catalog'
                                                    -- | 'auction_listing' | 'in_hand' | 'macro' | 'unknown'

  -- Qualité (cf. quality-pipeline.md)
  quality_score        real,
  training_eligible    boolean not null default false,
  quality_reason       text,
  quality_pipeline_version smallint,

  -- Dédup perceptuelle
  phash               bigint,

  -- Stockage du crop (dérivable depuis le raw + bbox, mais matérialisé pour rapidité)
  storage_path    text not null,
  width           integer,
  height          integer,
  sha256          text,

  -- Audit
  fetched_at      timestamptz not null default now(),
  resolved_at     timestamptz,                      -- timestamp de la dernière transition de status
  run_id          uuid references source_runs(id),

  unique (source_image_id, crop_index)
);

create index image_assets_eurio_idx on image_assets(eurio_id);
create index image_assets_status_idx on image_assets(resolution_status);
create index image_assets_training_idx on image_assets(training_eligible) where training_eligible = true;
create index image_assets_phash_idx on image_assets(phash);
create index image_assets_run_idx on image_assets(run_id);
create index image_assets_face_idx on image_assets(face);
```

### `resolution_status` — états

| État | Sémantique | Promotion possible vers |
|---|---|---|
| `pending_crop` | Raw téléchargé, pas encore croppé | `pending_match` |
| `pending_match` | Crop fait, name-match pas encore tenté ou en cours | `auto_name`, `needs_review` |
| `auto_name` | Match automatique par nom haute confiance | `manual` (override humain), `rejected` |
| `auto_phash` | Match propagé via pHash depuis une row déjà résolue | `manual`, `rejected` |
| `needs_review` | Auto-match a échoué ou confiance trop basse | `manual`, `rejected` |
| `manual` | Validé par review humaine | (terminal sauf override) |
| `rejected` | Image inutilisable (illisible, pas une pièce, hors-scope) | (terminal) |

### `variant_kind`

| Valeur | Sources typiques |
|---|---|
| `canonical` | numista |
| `official_press` | mdp, bce, wikipedia |
| `merchant_catalog` | numiscorner, cgb, lmdlp |
| `auction_listing` | ebay, catawiki |
| `in_hand` | ebay, catawiki (sous-cas) |
| `macro` | catawiki haut de gamme, cgb |
| `unknown` | défaut au fetch |

### `license` & `redistributable`

| Valeur | Redistribuable | Usage |
|---|---|---|
| `numista_api` | ❌ | usage ML interne |
| `public_domain` | ✅ | wikipedia commons, BCE certains cas |
| `cc_by` | ✅ avec attribution | wikipedia commons |
| `fair_use_research` | ❌ | catawiki, ebay, numiscorner, cgb |
| `editorial_official` | partiel | mdp, bce officielles |
| `unknown` | ❌ | par défaut |

## Table `coin_market_quotes`

```sql
create table coin_market_quotes (
  id              uuid primary key default gen_random_uuid(),

  eurio_id        text not null,                    -- NOT NULL : voir D-04
  source          text not null,                    -- 'ebay_active' | 'lmdlp' | 'numiscorner' | …

  condition_raw           text,
  condition_normalized    text not null default 'unknown',

  currency        text not null default 'EUR',
  p10             numeric,
  p50             numeric,
  p90             numeric,
  sample_size     integer not null default 1,

  period_start    timestamptz not null,
  period_end      timestamptz not null,

  fetched_at      timestamptz not null default now(),
  raw_payload     jsonb,
  run_id          uuid references source_runs(id),

  -- Note : `condition_raw` (et pas `condition_normalized`) dans la
  -- unique key, sinon SUP-62 et FDC mappent tous deux vers 'UNC' et
  -- s'écrasent. Cf. critique #7.
  unique (source, eurio_id, period_start, condition_raw)
);

create index cmq_eurio_idx on coin_market_quotes(eurio_id);
create index cmq_source_idx on coin_market_quotes(source);
create index cmq_period_idx on coin_market_quotes(period_start desc);
create index cmq_run_idx on coin_market_quotes(run_id);
```

## Table `pending_quotes`

> Les prix de listings non encore résolus. Promus vers
> `coin_market_quotes` au moment de la review humaine (D-04).

```sql
create table pending_quotes (
  id              uuid primary key default gen_random_uuid(),
  source_image_id uuid not null references source_images(id) on delete cascade,
  source          text not null,
  -- payload du prix tel qu'extrait du listing
  price           numeric,
  currency        text default 'EUR',
  condition_raw   text,
  observed_at     timestamptz not null default now(),
  raw_payload     jsonb
);

create index pq_source_image_idx on pending_quotes(source_image_id);
```

Quand un `image_assets` rattaché à ce `source_image_id` passe en
`manual`/`auto_*` avec un `eurio_id` résolu **et** que le listing
est mono-pièce (`n_crops_detected = 1`), un trigger applicatif
crée la row `coin_market_quotes` correspondante et supprime la row
`pending_quotes`.

## Table `review_queue`

```sql
create table review_queue (
  id                 uuid primary key default gen_random_uuid(),
  image_asset_id     uuid not null references image_assets(id) on delete cascade,

  -- Priorisation
  priority           integer not null default 100,  -- plus bas = plus prioritaire
  candidate_eurio_ids jsonb,                        -- top-K denormalisé pour rapidité UI

  -- État review
  status             text not null default 'open',  -- 'open' | 'in_progress' | 'done' | 'skipped'
  assigned_to        text,                          -- qui a la main (optionnel V1, mono-user)
  decided_eurio_id   text,                          -- résolu par l'humain
  decided_face       text,                          -- 'obverse' | 'reverse' | 'unknown'
  decided_variant_kind text,
  decided_at         timestamptz,
  decided_by         text,
  decision_notes     text,

  enqueued_at        timestamptz not null default now(),

  unique (image_asset_id)
);

create index rq_status_priority_idx on review_queue(status, priority);
```

Une row `image_assets` n'a au plus **1 entrée** dans `review_queue`.
Quand le reviewer décide, le statut passe à `'done'`, et l'image_asset
est mis à jour avec `resolution_status='manual'` + `eurio_id`
décidé. L'entrée `review_queue` reste pour l'audit (`status='done'`).

## Table `source_runs`

```sql
create table source_runs (
  id              uuid primary key default gen_random_uuid(),
  source          text not null,
  kind            text not null,                    -- 'run' | 'dry' | 'limit' | 'reset'
  started_at      timestamptz not null default now(),
  ended_at        timestamptz,
  status          text not null default 'running',  -- 'running' | 'success' | 'failed' | 'partial'

  n_calls            integer default 0,
  n_raws_added       integer default 0,
  n_crops_added      integer default 0,
  n_quotes_added     integer default 0,
  n_pending_added    integer default 0,
  n_errors           integer default 0,

  filters         jsonb,
  log_path        text,
  error_summary   text
);

create index source_runs_source_started_idx on source_runs(source, started_at desc);
```

## Conventions `source_ref`

| Source | Pattern (1 row par listing/lot, pas par image) |
|---|---|
| numista | `numista_<numistaId>` (un row source_image, deux child crops obverse+reverse) |
| ebay | `ebay_listing_<itemId>` |
| catawiki | `catawiki_lot_<lotId>` |
| numiscorner | `numiscorner_<sku>` |
| cgb | `cgb_<reference>` |
| mdp | `mdp_<slug>` |
| bce | `bce_<year>_<countryCode>` |
| wikipedia | `wikipedia_<pageId>` |
| lmdlp | `lmdlp_<slug>` |

L'index image (`_img0`, `_img1`...) **n'est plus dans `source_ref`** :
les multiples images d'un listing sont des `image_assets.crop_index`
distincts attachés au même `source_images`.

## Notes de cohérence

- `image_assets.face` reste rempli par le quality pipeline
  (heuristique). Le filtre training utilise `face='obverse'` (D-11).
- `image_assets.training_eligible` exige : `eurio_id IS NOT NULL` AND
  `quality_score >= seuil` AND `resolution_status NOT IN ('rejected',
  'pending_*', 'needs_review')`. Cf. quality-pipeline.md.
- `coin_market_quotes` : aucune row sans `eurio_id` résolu (D-04).
- pHash sert à propager les labels (D-07) et à dédupliquer cross-listing.

## Migration

- Tables s'ajoutent à `ml/state/training.db`. Migration via une nouvelle
  série `ml/state/schema_extensions/sources_refacto.sql`.
- `coin_market_prices` Supabase legacy reste tel quel pendant la
  transition. Une fois `coin_market_quotes` peuplé pour eBay et
  l'admin câblé dessus (phase 4), un refacto séparé archive le legacy.
- Pas de backfill automatique des images Numista existantes vers
  `source_images` / `image_assets`. Optionnel via une task one-shot
  (cf. open-problems OP-4).
