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
| `discovery_log` | 1 row par `(source, source_ref)` rencontré (couche 1 dédup) | n/a |
| `source_images` | 1 row par fichier physique téléchargé (le "raw") | facultatif (héritage par défaut depuis le contexte du fetch quand cible précise, sinon NULL) |
| `image_assets` | 1 row par crop pièce dérivé d'un raw | nullable, résolu plus tard |
| `coin_market_quotes` | 1 row par cotation marché par condition × période | NOT NULL |
| `pending_quotes` | Quotes en attente que l'image associée soit résolue | NULL toléré, promu vers `coin_market_quotes` à la résolution |
| `review_queue` | File de revue humaine pour les `image_assets` non résolus | NULL par construction |
| `source_runs` | Logs des runs par source | n/a |

## Table `discovery_log`

> Couche 1 du dédup cross-runs / cross-sources (cf. §"Dédup en
> 5 couches"). Inscrit chaque `(source, source_ref)` rencontré
> pendant l'étape Discover de l'orchestrateur, **avant** même
> le download. Permet de skipper en O(1) un listing déjà connu
> sans charger `source_images` en mémoire.

```sql
create table discovery_log (
  id              text primary key,
  source          text not null,
  source_ref      text not null,                    -- ex: 'ebay_listing_195832104221'
  query_signature text,                             -- hash stable de (eurio_id_target, filters)
  first_seen_at   text not null default now(),
  last_seen_at    text not null default now(),
  last_run_id     text references source_runs(id) on delete set null,
  pipeline_state  text not null default 'discovered',
                                                    -- 'discovered' | 'persisted' | 'downloaded'
                                                    -- | 'cropped' | 'resolved' | 'rejected'
  unique (source, source_ref)
);

create index idx_discovery_log_source_seen on discovery_log(source, last_seen_at desc);
create index idx_discovery_log_state       on discovery_log(pipeline_state);
create index idx_discovery_log_query       on discovery_log(query_signature);
```

**Pattern d'usage** — tous les fetch font un upsert :

```sql
insert into discovery_log (id, source, source_ref, query_signature, last_run_id)
values (?, ?, ?, ?, ?)
on conflict (source, source_ref) do update set
  last_seen_at = datetime('now'),
  last_run_id  = excluded.last_run_id;
```

L'orchestrateur peut alors décider : si `pipeline_state >= 'downloaded'`
**et** `first_seen_at < now - 7j`, on saute le download (la couche 3
fait la double-vérif via `os.path.exists(local_path)`).

`pipeline_state` est mis à jour par chaque étape qui réussit (Persist
→ `persisted`, Download → `downloaded`, etc.). Les valeurs sont
strictement croissantes à part `rejected`, terminal pour les listings
qu'on choisit d'abandonner.

`query_signature` n'est pas requis mais utile pour invalider une
cohorte ciblée (re-scrape d'`eurio_id=BE-2EUR-2002` peut sélectionner
toutes les rows liées à cette query pour forcer un re-fetch).

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

## Dédup en 5 couches

Le pipeline d'ingestion est non destructif (D-02) mais doit
absolument **éviter de re-faire le travail** d'un run à l'autre.
Le dédup est en cascade, chaque couche répondant à un niveau
différent de duplication :

| Couche | Question | Mécanisme | Coût évité |
|---|---|---|---|
| 1 — Discovery | "j'ai déjà vu ce listing récemment" | `discovery_log.UNIQUE(source, source_ref)` + `last_seen_at` | API call inutile |
| 2 — Persistence | "j'ai déjà ce listing en base" | `source_images.UNIQUE(source, source_ref)` + ON CONFLICT | INSERT redondant |
| 3 — Download | "j'ai déjà le fichier sur disque" | `source_images.storage_path` + `os.path.exists` | bandwidth |
| 4 — Crop pHash | "ce crop est visuellement identique à un autre" | `phash_match(phash, ?, 4)` (D-07) | review humaine redondante |
| 5 — Resolution | "ce crop est déjà résolu" | `image_assets.resolution_status` ≠ `pending_*` / `needs_review` | re-running un name-match |

Cas concret cross-source : même vendeur poste son listing sur eBay
et Catawiki. Couches 1-3 ne dédupliquent pas (les `source_ref`
diffèrent : `ebay_listing_X` vs `catawiki_lot_Y`). La couche 4
attrape : le pHash du crop est identique, le 2ᵉ asset hérite du
`eurio_id` du 1ᵉʳ (statut `auto_phash`), pas de re-review humaine.

Cas où l'on **veut** dupliquer : 2 photos différentes du même
`eurio_id` (in-the-wild eBay vs studio MdP). Les pHash diffèrent →
les 2 assets sont conservés, ce qui enrichit le training set. Bingo.

## Recherche pHash et UDF Hamming

SQLite < 3.43 n'a pas de `bit_count` natif, et même les versions
récentes ne l'exposent pas systématiquement via le module Python
`sqlite3`. On enregistre donc deux UDF Python via
`conn.create_function(deterministic=True)` (cf.
`ml/state/store.py::_register_phash_udfs`) :

| UDF | Signature | Sémantique |
|---|---|---|
| `hamming(a, b)` | `(int64?, int64?) → int?` | Distance de Hamming entre deux pHash 64 bits. NULL-safe (retourne NULL si entrée NULL). Masque interne `& 0xFFFFFFFFFFFFFFFF` pour gérer signed/unsigned. |
| `phash_match(a, b, threshold)` | `(int64?, int64?, int) → 0/1` | Wrapper booléen pour `WHERE`. Retourne `1` si `hamming(a, b) ≤ threshold`. |

**Pattern de cluster lookup** :

```sql
-- Trouve les assets visuellement identiques à un asset donné
-- (D-07 : seuil Hamming = 4)
select id, eurio_id, resolution_status
from image_assets
where phash_match(phash, ?, 4)
  and id != ?
  and resolution_status in ('manual', 'auto_name');
```

Un `index idx_image_assets_phash` existe sur `image_assets(phash)`
mais ne sert pas à accélérer un Hamming search (B-tree ne range-scan
pas par distance). Le scan reste full-table-driven, **acceptable
jusqu'à ~100k assets**. Plus haut volume → option BK-tree en mémoire,
chargée au boot et invalidée à l'insertion (hors V1).

Note : la fonction est marquée `deterministic=True` pour autoriser
SQLite à l'optimiser et à la garder safe dans les expressions
indexées futures (cf.
[doc SQLite](https://www.sqlite.org/c3ref/create_function.html)).

## Migration

- Tables ajoutées directement dans `ml/state/schema.sql` (idempotent
  via `executescript` à chaque boot du `Store`, cf. `state/store.py`).
- **`sources_runs.json` → `source_runs`** : migration one-shot via
  `python -m scripts.migrate_sources_runs_to_db` (re-exécutable,
  idempotente par `id` déterministe `migrated:<source>:<last_run_at>`).
  Le JSON est conservé en read-only pour audit historique mais
  `state/sources_runs.py` est déprécié — les nouveaux runs écrivent
  directement en DB.
- `coin_market_prices` Supabase legacy reste tel quel pendant la
  transition. Une fois `coin_market_quotes` peuplé pour eBay et
  l'admin câblé dessus (phase 4), un refacto séparé archive le legacy.
- Pas de backfill automatique des images Numista existantes vers
  `source_images` / `image_assets`. Optionnel via une task one-shot
  (cf. open-problems OP-4).
