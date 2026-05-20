-- SQLite schema for local training state.
-- Applied idempotently at Store init via executescript().

CREATE TABLE IF NOT EXISTS training_runs (
  id                         TEXT PRIMARY KEY,
  version                    INTEGER NOT NULL,
  status                     TEXT NOT NULL
                             CHECK (status IN ('queued','running','completed','failed')),
  started_at                 TEXT,
  finished_at                TEXT,
  config_json                TEXT NOT NULL,
  classes_before_json        TEXT NOT NULL,
  classes_after_json         TEXT NOT NULL,
  classes_added_json         TEXT NOT NULL,
  classes_removed_json       TEXT NOT NULL,
  loss                       REAL,
  recall_at_1                REAL,
  recall_at_3                REAL,
  epoch_duration_median_sec  REAL,
  error                      TEXT,
  created_at                 TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_training_runs_status ON training_runs(status);
CREATE INDEX IF NOT EXISTS idx_training_runs_version ON training_runs(version DESC);
CREATE INDEX IF NOT EXISTS idx_training_runs_started ON training_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS training_run_steps (
  run_id       TEXT NOT NULL REFERENCES training_runs(id) ON DELETE CASCADE,
  step_index   INTEGER NOT NULL,
  name         TEXT NOT NULL,
  status       TEXT NOT NULL
               CHECK (status IN ('pending','running','done','failed','skipped')),
  started_at   TEXT,
  finished_at  TEXT,
  detail       TEXT,
  PRIMARY KEY (run_id, step_index)
);

CREATE TABLE IF NOT EXISTS training_run_epochs (
  run_id        TEXT NOT NULL REFERENCES training_runs(id) ON DELETE CASCADE,
  epoch         INTEGER NOT NULL,
  train_loss    REAL,
  recall_at_1   REAL,
  recall_at_3   REAL,
  lr            REAL,
  duration_sec  REAL,
  PRIMARY KEY (run_id, epoch)
);

CREATE TABLE IF NOT EXISTS training_run_classes (
  run_id          TEXT NOT NULL REFERENCES training_runs(id) ON DELETE CASCADE,
  class_id        TEXT NOT NULL,
  class_kind      TEXT NOT NULL
                  CHECK (class_kind IN ('eurio_id','design_group_id')),
  recall_at_1     REAL,
  n_train_images  INTEGER,
  n_val_images    INTEGER,
  PRIMARY KEY (run_id, class_id)
);

CREATE INDEX IF NOT EXISTS idx_training_run_classes_class_id
  ON training_run_classes(class_id);

CREATE TABLE IF NOT EXISTS training_run_logs (
  run_id      TEXT PRIMARY KEY REFERENCES training_runs(id) ON DELETE CASCADE,
  log_gz      BLOB NOT NULL,
  line_count  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS training_staging (
  class_id    TEXT PRIMARY KEY,
  class_kind  TEXT NOT NULL
              CHECK (class_kind IN ('eurio_id','design_group_id')),
  staged_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS training_removal_staging (
  class_id    TEXT PRIMARY KEY,
  class_kind  TEXT NOT NULL
              CHECK (class_kind IN ('eurio_id','design_group_id')),
  staged_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Augmentation ────────────────────────────────────────────────────────
-- Phase 2 — PRD Bloc 1. Recipes are tuned in the admin Studio (`/augmentation`)
-- and referenced from training runs + benchmark runs (Bloc 3) for traceability.

CREATE TABLE IF NOT EXISTS augmentation_recipes (
  id                    TEXT PRIMARY KEY,
  name                  TEXT NOT NULL UNIQUE,
  zone                  TEXT
                        CHECK (zone IS NULL OR zone IN ('green','orange','red')),
  config_json           TEXT NOT NULL,
  based_on_recipe_id    TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_augmentation_recipes_zone ON augmentation_recipes(zone);

CREATE TABLE IF NOT EXISTS augmentation_runs (
  id                TEXT PRIMARY KEY,
  recipe_id         TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  eurio_id          TEXT,
  design_group_id   TEXT,
  count             INTEGER NOT NULL,
  seed              INTEGER,
  output_dir        TEXT NOT NULL,
  duration_ms       INTEGER,
  status            TEXT NOT NULL
                    CHECK (status IN ('running','completed','failed')),
  error             TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_augmentation_runs_recipe ON augmentation_runs(recipe_id);
CREATE INDEX IF NOT EXISTS idx_augmentation_runs_created ON augmentation_runs(created_at DESC);

-- ─── Benchmark ───────────────────────────────────────────────────────────
-- Phase 2 — PRD Bloc 3. Each row captures one evaluation of a trained model
-- against the real-photo hold-out library under `ml/data/real_photos/`.
-- References back to `training_runs` (which model) and `augmentation_recipes`
-- (which recipe trained that model) to close the traceability loop
-- recipe → training → benchmark.

CREATE TABLE IF NOT EXISTS benchmark_runs (
  id                    TEXT PRIMARY KEY,
  model_path            TEXT NOT NULL,
  model_name            TEXT NOT NULL,
  training_run_id       TEXT REFERENCES training_runs(id) ON DELETE SET NULL,
  recipe_id             TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  eurio_ids_json        TEXT NOT NULL,
  zones_json            TEXT NOT NULL,
  num_photos            INTEGER NOT NULL,
  num_coins             INTEGER NOT NULL,
  r_at_1                REAL,
  r_at_3                REAL,
  r_at_5                REAL,
  mean_spread           REAL,
  per_zone_json         TEXT NOT NULL,
  per_coin_json         TEXT NOT NULL,
  confusion_json        TEXT NOT NULL,
  top_confusions_json   TEXT NOT NULL,
  report_path           TEXT NOT NULL,
  status                TEXT NOT NULL
                        CHECK (status IN ('running','completed','failed')),
  error                 TEXT,
  started_at            TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_model ON benchmark_runs(model_name);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_recipe ON benchmark_runs(recipe_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_training ON benchmark_runs(training_run_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_started ON benchmark_runs(started_at DESC);

-- ─── Lab — experiments ───────────────────────────────────────────────────
-- PRD Bloc 4 (docs/augmentation-benchmark/04-experiments-lab.md). The Lab
-- chains recipe → training → benchmark as a single first-class "iteration"
-- unit, grouped inside a frozen "cohort" (fixed set of eurio_ids with real
-- photos) so that successive tweaks are comparable apples-to-apples.

CREATE TABLE IF NOT EXISTS experiment_cohorts (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL UNIQUE,
  description         TEXT,
  zone                TEXT
                      CHECK (zone IS NULL OR zone IN ('green','orange','red')),
  eurio_ids_json      TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft','frozen')),
  frozen_at           TEXT,
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_experiment_cohorts_zone ON experiment_cohorts(zone);
CREATE INDEX IF NOT EXISTS idx_experiment_cohorts_created ON experiment_cohorts(created_at DESC);

CREATE TABLE IF NOT EXISTS experiment_iterations (
  id                        TEXT PRIMARY KEY,
  cohort_id                 TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,
  parent_iteration_id       TEXT REFERENCES experiment_iterations(id) ON DELETE SET NULL,
  name                      TEXT NOT NULL,
  hypothesis                TEXT,
  recipe_id                 TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,
  variant_count             INTEGER NOT NULL DEFAULT 100,
  training_config_json      TEXT NOT NULL DEFAULT '{}',
  status                    TEXT NOT NULL
                            CHECK (status IN ('pending','training','benchmarking','completed','failed')),
  training_run_id           TEXT REFERENCES training_runs(id) ON DELETE SET NULL,
  benchmark_run_id          TEXT REFERENCES benchmark_runs(id) ON DELETE SET NULL,
  verdict                   TEXT
                            CHECK (verdict IN ('pending','baseline','better','worse','mixed','no_change')),
  verdict_override          TEXT,
  delta_vs_parent_json      TEXT NOT NULL DEFAULT '{}',
  diff_from_parent_json     TEXT NOT NULL DEFAULT '{}',
  notes                     TEXT,
  error                     TEXT,
  created_at                TEXT NOT NULL DEFAULT (datetime('now')),
  started_at                TEXT,
  finished_at               TEXT
);

CREATE INDEX IF NOT EXISTS idx_experiment_iterations_cohort ON experiment_iterations(cohort_id);
CREATE INDEX IF NOT EXISTS idx_experiment_iterations_parent ON experiment_iterations(parent_iteration_id);
CREATE INDEX IF NOT EXISTS idx_experiment_iterations_created ON experiment_iterations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiment_iterations_status ON experiment_iterations(status);

-- ─── Aug ↔ réelles cache (Sprint 2) ──────────────────────────────────────
-- DINO cosine distance per (iteration, eurio_id). Cache key includes
-- dino_version + counts so a model swap or capture/aug delta forces
-- recompute (see `ml/api/distance_logic.py`).

CREATE TABLE IF NOT EXISTS iteration_aug_vs_real (
  iteration_id    TEXT NOT NULL REFERENCES experiment_iterations(id) ON DELETE CASCADE,
  eurio_id        TEXT NOT NULL,
  num_real        INTEGER NOT NULL,
  num_aug         INTEGER NOT NULL,
  cosine          REAL NOT NULL,
  dino_version    TEXT NOT NULL,
  computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (iteration_id, eurio_id)
);

CREATE INDEX IF NOT EXISTS idx_iteration_aug_vs_real_iter
  ON iteration_aug_vs_real(iteration_id);

-- ─── Live tests (Sprint 4) ───────────────────────────────────────────────
-- Per-test result for the cohortTest live-test flow. One row per (iteration,
-- test_idx) — the JSONL log written on-device by `LiveTestLogger.kt` and
-- pulled into `ml/state/live_test_logs/<iteration_id>.jsonl` is the raw
-- source of truth; this table holds the parsed/dedup'd view used by §5
-- in the admin iteration detail page. Resync of the same JSONL is idempotent
-- (the (iteration_id, test_idx) PK absorbs duplicates — see route's
-- skipped_dupe counter).

CREATE TABLE IF NOT EXISTS iteration_live_tests (
  iteration_id        TEXT NOT NULL REFERENCES experiment_iterations(id) ON DELETE CASCADE,
  test_idx            INTEGER NOT NULL,
  expected_eurio_id   TEXT NOT NULL,
  condition           TEXT NOT NULL CHECK (condition IN ('bright','dim','tilt')),
  predicted_top3_json TEXT NOT NULL,        -- [{eurio_id, similarity}, ...]
  predicted_top1      TEXT,                  -- denormalized for fast queries
  similarity_top1     REAL,
  is_correct          INTEGER NOT NULL,      -- 1 if predicted_top1 == expected, else 0
  error               TEXT,                  -- non-null when on-device inference failed (OQ-1)
  ts                  TEXT NOT NULL,         -- ISO8601 from device
  synced_at           TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (iteration_id, test_idx)
);

CREATE INDEX IF NOT EXISTS idx_live_tests_iter
  ON iteration_live_tests(iteration_id);

-- Additive migrations for existing tables — SQLite has no `ADD COLUMN IF NOT
-- EXISTS`, so Store._bootstrap runs these via a PRAGMA-guarded Python helper
-- (see `state/store.py::_ensure_column`). Keeping them here as reference only.
--
-- ALTER TABLE training_runs    ADD COLUMN aug_recipe_id TEXT
--   REFERENCES augmentation_recipes(id) ON DELETE SET NULL;
-- ALTER TABLE training_staging ADD COLUMN aug_recipe_id TEXT
--   REFERENCES augmentation_recipes(id) ON DELETE SET NULL;

-- ─── Sources refacto (docs/sources-refacto/) ─────────────────────────────
-- Two-table image split (source_images = raw download, image_assets = crops)
-- with deferred eurio_id resolution via review_queue. See decisions.md
-- D-01..D-15 and schema.md for the rationale of each column.

CREATE TABLE IF NOT EXISTS source_runs (
  id              TEXT PRIMARY KEY,
  source          TEXT NOT NULL,
  kind            TEXT NOT NULL
                  CHECK (kind IN ('run','dry','limit','reset')),
  started_at      TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at        TEXT,
  status          TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','success','failed','partial')),
  current_step    TEXT,                                -- 'discover'|'persist'|'download'|'detect'|'resolve'|'auto_validate'|'enqueue'
  n_calls            INTEGER NOT NULL DEFAULT 0,
  n_raws_added       INTEGER NOT NULL DEFAULT 0,
  n_crops_added      INTEGER NOT NULL DEFAULT 0,
  n_quotes_added     INTEGER NOT NULL DEFAULT 0,
  n_pending_added    INTEGER NOT NULL DEFAULT 0,
  n_auto_resolved    INTEGER NOT NULL DEFAULT 0,
  n_review_enqueued  INTEGER NOT NULL DEFAULT 0,
  n_errors           INTEGER NOT NULL DEFAULT 0,
  filters_json    TEXT,
  log_path        TEXT,
  error_summary   TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_runs_source_started
  ON source_runs(source, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_runs_status ON source_runs(status);

CREATE TABLE IF NOT EXISTS source_images (
  id               TEXT PRIMARY KEY,
  source           TEXT NOT NULL,
  source_ref       TEXT NOT NULL,
  source_url       TEXT,
  target_eurio_id  TEXT,
  listing_title    TEXT,
  listing_country  TEXT,
  listing_year     INTEGER,
  listing_price    REAL,
  listing_currency TEXT NOT NULL DEFAULT 'EUR',
  condition_raw    TEXT,
  seller_id        TEXT,
  storage_path     TEXT,
  width            INTEGER,
  height           INTEGER,
  bytes            INTEGER,
  sha256           TEXT,
  n_crops_detected INTEGER NOT NULL DEFAULT 0,
  license          TEXT NOT NULL DEFAULT 'unknown',
  redistributable  INTEGER NOT NULL DEFAULT 0,
  fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
  raw_payload_json TEXT,
  run_id           TEXT REFERENCES source_runs(id) ON DELETE SET NULL,
  -- Cascade sync (chunk 9): is the MinIO object behind storage_path still present?
  -- 'present'             : nominal (default)
  -- 'missing_in_storage'  : MinIO returned 404 → drift, investigate
  -- 'removed_via_admin'   : intentional admin deletion, do not auto-repair
  storage_status   TEXT NOT NULL DEFAULT 'present'
                   CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin')),
  UNIQUE (source, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_source_images_source ON source_images(source);
CREATE INDEX IF NOT EXISTS idx_source_images_target ON source_images(target_eurio_id);
CREATE INDEX IF NOT EXISTS idx_source_images_run ON source_images(run_id);
CREATE INDEX IF NOT EXISTS idx_source_images_storage_status
  ON source_images(storage_status) WHERE storage_status != 'present';

CREATE TABLE IF NOT EXISTS image_assets (
  id                       TEXT PRIMARY KEY,
  source_image_id          TEXT NOT NULL REFERENCES source_images(id) ON DELETE CASCADE,
  crop_index               INTEGER NOT NULL DEFAULT 0,
  bbox_json                TEXT,                       -- {x,y,w,h,conf}
  detection_method         TEXT,                       -- 'yolo'|'hough'|'merged'|'manual'

  eurio_id                 TEXT,
  resolution_status        TEXT NOT NULL DEFAULT 'pending_match'
                           CHECK (resolution_status IN (
                             'pending_crop','pending_match',
                             'auto_name','auto_phash',
                             'needs_review','manual','rejected'
                           )),
  resolution_confidence    REAL,
  resolution_attempts_json TEXT,
  candidate_eurio_ids_json TEXT,

  face                     TEXT
                           CHECK (face IS NULL OR face IN ('obverse','reverse','unknown')),
  variant_kind             TEXT NOT NULL DEFAULT 'unknown'
                           CHECK (variant_kind IN (
                             'canonical','official_press','merchant_catalog',
                             'auction_listing','in_hand','macro','reverse_only','unknown'
                           )),

  quality_score            REAL,
  training_eligible        INTEGER NOT NULL DEFAULT 0,
  quality_reason           TEXT,
  quality_pipeline_version INTEGER,

  phash                    INTEGER,                    -- 64-bit perceptual hash

  storage_path             TEXT NOT NULL,
  width                    INTEGER,
  height                   INTEGER,
  sha256                   TEXT,

  fetched_at               TEXT NOT NULL DEFAULT (datetime('now')),
  resolved_at              TEXT,
  run_id                   TEXT REFERENCES source_runs(id) ON DELETE SET NULL,

  -- Cascade sync (chunk 9): same semantics as source_images.storage_status.
  storage_status           TEXT NOT NULL DEFAULT 'present'
                           CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin')),

  UNIQUE (source_image_id, crop_index)
);

CREATE INDEX IF NOT EXISTS idx_image_assets_eurio    ON image_assets(eurio_id);
CREATE INDEX IF NOT EXISTS idx_image_assets_status   ON image_assets(resolution_status);
CREATE INDEX IF NOT EXISTS idx_image_assets_training ON image_assets(training_eligible)
  WHERE training_eligible = 1;
CREATE INDEX IF NOT EXISTS idx_image_assets_phash    ON image_assets(phash);
CREATE INDEX IF NOT EXISTS idx_image_assets_run      ON image_assets(run_id);
CREATE INDEX IF NOT EXISTS idx_image_assets_face     ON image_assets(face);
CREATE INDEX IF NOT EXISTS idx_image_assets_storage_status
  ON image_assets(storage_status) WHERE storage_status != 'present';

-- ─── Auto-validation: Dino predictions per crop ───────────────────────────
-- Voir docs/sources-refacto/auto-validation/dino-verifier-kickoff.md.
-- 1 row par (asset_id, encoder_version, anchors_kind). DINOv2 ViT-S/14
-- encode chaque crop puis compare aux ancres obverse Numista du catalog
-- (bank cachée dans ml/state/foundation_anchors_<kind>.npz). Le résultat
-- top-K + spread sert d'aide visuelle au reviewer humain en V1, et de
-- base pour l'auto-accept ultérieur (chunk futur). L'asset reste en
-- 'needs_review' tant que l'humain n'a pas tranché.

CREATE TABLE IF NOT EXISTS image_asset_dino_predictions (
  asset_id        TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  encoder_version TEXT NOT NULL,        -- 'dinov2-vits14'
  anchors_kind    TEXT NOT NULL,        -- '2eur_commemo' (namespace)
  anchors_count   INTEGER NOT NULL,
  top_k_json      TEXT NOT NULL,        -- [{eurio_id, sim}, ...] desc par sim
  top1_eurio_id   TEXT,
  top1_sim        REAL,
  top2_eurio_id   TEXT,
  top2_sim        REAL,
  spread          REAL,                 -- top1_sim - top2_sim
  -- Country-restricted re-rank: même crop, même bank, mais on masque
  -- aux ancres dont l'eurio_id préfixe = pays cible (ISO2 dérivé du
  -- target_eurio_id de la query eBay parente). NULL si pas de target
  -- pays connu (e.g. crop sans target_eurio_id sur le source_image).
  -- Mesuré chunk 3.5 : R@1 10% → 34%, R@5 21% → 66%.
  target_country         TEXT,
  country_anchors_count  INTEGER,
  top_k_country_json     TEXT,
  top1_country_eurio_id  TEXT,
  top1_country_sim       REAL,
  top2_country_eurio_id  TEXT,
  top2_country_sim       REAL,
  country_spread         REAL,
  computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  duration_ms     INTEGER,
  PRIMARY KEY (asset_id, encoder_version, anchors_kind)
);

CREATE INDEX IF NOT EXISTS idx_dino_pred_asset
  ON image_asset_dino_predictions(asset_id);
CREATE INDEX IF NOT EXISTS idx_dino_pred_top1
  ON image_asset_dino_predictions(top1_eurio_id);
-- idx_dino_pred_top1_country est créé dans Store._bootstrap après que
-- la colonne soit ajoutée via _ensure_column (sinon executescript()
-- pète sur les bases pré-existantes qui n'ont pas encore la colonne).

-- ─── Listing text signals (chunk 5 auto-validation) ───────────────────────
-- Sortie de l'extracteur ml/sources/text_signals/ pour chaque source_image.
-- 1 row par source_image_id. Pas de comparaison vs target ici (chunk 6) :
-- on stocke juste ce que le titre dit explicitement (countries, years,
-- denominations, theme tokens, markers de rejet, lot flag, coverage).

CREATE TABLE IF NOT EXISTS listing_text_signals (
  source_image_id        TEXT PRIMARY KEY REFERENCES source_images(id) ON DELETE CASCADE,
  extractor_version      TEXT NOT NULL DEFAULT 'v1',
  countries_json         TEXT NOT NULL DEFAULT '[]',  -- ["FR","BE"]
  years_json             TEXT NOT NULL DEFAULT '[]',  -- [2014]
  denominations_json     TEXT NOT NULL DEFAULT '[]',  -- [2.0]
  theme_tokens_json      TEXT NOT NULL DEFAULT '[]',  -- ["radio","tele"]
  rejected_markers_json  TEXT NOT NULL DEFAULT '[]',  -- ["proof"]
  is_lot                 INTEGER NOT NULL DEFAULT 0,
  coverage               TEXT NOT NULL CHECK (coverage IN ('rich','sparse','empty')),
  matched_json           TEXT NOT NULL DEFAULT '{}',  -- debug ListingTextSignals.matched
  -- Verdict vs target_eurio_id (chunk 6 auto-validation). NULL quand le
  -- target n'est pas connu (pas de target_eurio_id sur source_images, ou
  -- absent de coins). Cf. docs/sources-refacto/auto-validation/
  -- chunk-06-text-comparator-kickoff.md.
  vs_target_verdict      TEXT
                         CHECK (vs_target_verdict IS NULL
                                OR vs_target_verdict IN
                                  ('convergent','partial','absent','contradict')),
  contradictions_json    TEXT NOT NULL DEFAULT '[]',  -- ["country"]
  convergences_json      TEXT NOT NULL DEFAULT '[]',  -- ["year","denomination"]
  -- Taxonomie listing & état numismatique (chunk C1 — pipeline prix).
  -- NULL = pas encore extrait. Renseignés par l'étape text_signals (C2).
  -- listing_kind : nature du listing → détermine la règle de prix.
  --   'single'      : pièce nue vendue seule → entre dans le prix de réf.
  --   'lot'         : N pièces → prix ÷ N non fiable → exclu.
  --   'coffret'     : coincard/blister → premium emballage → exclu du prix nu.
  --   'graded_slab' : slab gradé PCGS/NGC → on paie le grade → exclu.
  listing_kind            TEXT
                          CHECK (listing_kind IS NULL
                                 OR listing_kind IN
                                   ('single','lot','coffret','graded_slab')),
  listing_kind_confidence REAL,  -- 0..1 — confiance de l'heuristique
  -- condition_normalized : état numismatique extrait du titre. Tiers
  -- alignés sur coin_market_quotes.condition_normalized.
  condition_normalized    TEXT
                          CHECK (condition_normalized IS NULL
                                 OR condition_normalized IN
                                   ('UNC','TTB','TB','unknown')),
  condition_confidence    REAL,  -- 0..1 — confiance de l'heuristique
  computed_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_listing_text_signals_coverage
  ON listing_text_signals(coverage);
CREATE INDEX IF NOT EXISTS idx_listing_text_signals_lot
  ON listing_text_signals(is_lot) WHERE is_lot = 1;
-- idx_listing_text_signals_verdict est créé dans Store._bootstrap après que
-- la colonne vs_target_verdict soit ajoutée via _ensure_column (sinon
-- executescript() pète sur les bases pré-existantes).

CREATE TABLE IF NOT EXISTS coin_market_quotes (
  id                   TEXT PRIMARY KEY,
  eurio_id             TEXT NOT NULL,
  source               TEXT NOT NULL,
  condition_raw        TEXT,
  condition_normalized TEXT NOT NULL DEFAULT 'unknown',
  currency             TEXT NOT NULL DEFAULT 'EUR',
  p10                  REAL,
  p50                  REAL,
  p90                  REAL,
  sample_size          INTEGER NOT NULL DEFAULT 1,
  period_start         TEXT NOT NULL,
  period_end           TEXT NOT NULL,
  fetched_at           TEXT NOT NULL DEFAULT (datetime('now')),
  raw_payload_json     TEXT,
  run_id               TEXT REFERENCES source_runs(id) ON DELETE SET NULL,
  UNIQUE (source, eurio_id, period_start, condition_raw)
);

CREATE INDEX IF NOT EXISTS idx_cmq_eurio  ON coin_market_quotes(eurio_id);
CREATE INDEX IF NOT EXISTS idx_cmq_source ON coin_market_quotes(source);
CREATE INDEX IF NOT EXISTS idx_cmq_period ON coin_market_quotes(period_start DESC);
CREATE INDEX IF NOT EXISTS idx_cmq_run    ON coin_market_quotes(run_id);

CREATE TABLE IF NOT EXISTS pending_quotes (
  id               TEXT PRIMARY KEY,
  source_image_id  TEXT NOT NULL REFERENCES source_images(id) ON DELETE CASCADE,
  source           TEXT NOT NULL,
  price            REAL,
  currency         TEXT NOT NULL DEFAULT 'EUR',
  condition_raw    TEXT,
  observed_at      TEXT NOT NULL DEFAULT (datetime('now')),
  raw_payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_quotes_source_image
  ON pending_quotes(source_image_id);

CREATE TABLE IF NOT EXISTS review_queue (
  id                       TEXT PRIMARY KEY,
  image_asset_id           TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  priority                 INTEGER NOT NULL DEFAULT 100,
  candidate_eurio_ids_json TEXT,
  status                   TEXT NOT NULL DEFAULT 'open'
                           CHECK (status IN ('open','in_progress','done','skipped')),
  assigned_to              TEXT,
  decided_eurio_id         TEXT,
  decided_face             TEXT,
  decided_variant_kind     TEXT,
  decided_at               TEXT,
  decided_by               TEXT,
  decision_notes           TEXT,
  enqueued_at              TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (image_asset_id)
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status_priority
  ON review_queue(status, priority);

-- ─── Discovery log (cross-runs dedup, layer 1) ───────────────────────────
-- L'orchestrateur D-13 §"Discover" inscrit ici tout listing rencontré
-- pendant un fetch (avant même d'aller le télécharger). Permet de
-- détecter "j'ai déjà vu ce listing récemment, skip" sans avoir à
-- charger source_images en mémoire. Voir docs/sources-refacto/schema.md
-- §"Dédup en 5 couches".
--
-- Une row par (source, source_ref) globalement (pas par run). Re-discovery
-- du même listing = UPDATE last_seen_at + run_id, conserve first_seen_at.
-- query_signature = hash stable de la requête qui a trouvé le listing,
-- utile pour invalider proprement (ex: re-scrape une cohorte ciblée).

CREATE TABLE IF NOT EXISTS discovery_log (
  id              TEXT PRIMARY KEY,
  source          TEXT NOT NULL,
  source_ref      TEXT NOT NULL,
  query_signature TEXT,
  first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
  last_run_id     TEXT REFERENCES source_runs(id) ON DELETE SET NULL,
  -- Statut local d'avancement dans la pipeline en aval (utile pour
  -- l'idempotence : si déjà persisté/téléchargé, on saute des étapes)
  pipeline_state  TEXT NOT NULL DEFAULT 'discovered'
                  CHECK (pipeline_state IN (
                    'discovered',     -- vu, pas encore persisté
                    'persisted',      -- ligne source_images existe
                    'downloaded',     -- fichier raw sur disque
                    'cropped',        -- crops dans image_assets
                    'resolved',       -- au moins 1 crop résolu
                    'rejected'        -- listing inutilisable (au-delà du raw)
                  )),
  UNIQUE (source, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_discovery_log_source_seen
  ON discovery_log(source, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_discovery_log_state
  ON discovery_log(pipeline_state);
CREATE INDEX IF NOT EXISTS idx_discovery_log_query
  ON discovery_log(query_signature);

-- ─── Discovery searches (per-call API debug log) ──────────────────────────
-- 1 row par appel logique adapter.discover() pour un (run_id, target_eurio_id).
-- Permet de distinguer "vraiment 0 résultat" de "scrape pas exécuté / failed /
-- post-filter trop strict". Cf. docs/sources-refacto/listing-debug-view-kickoff.md.
--
-- n_raw_results : ce que l'API source a renvoyé brut (avant nos filtres).
-- n_kept_results : après nos filtres applicatifs (accept_listing, theme tokens).
-- query_filters_json : aspect_filter, theme_tokens, ambiguous, search_limit, etc.

CREATE TABLE IF NOT EXISTS discovery_searches (
  id                  TEXT PRIMARY KEY,
  run_id              TEXT NOT NULL REFERENCES source_runs(id) ON DELETE CASCADE,
  source              TEXT NOT NULL,
  target_eurio_id     TEXT,
  endpoint            TEXT,
  query_q             TEXT,
  query_filters_json  TEXT,
  status              TEXT NOT NULL CHECK (status IN ('success', 'empty', 'failed')),
  http_status         INTEGER,
  -- Funnel ventilé (chunk 0 auto-validation : "visibilité du stream") :
  -- N0 = itemSummaries renvoyés brut par Browse search (sans groups).
  -- N1 = après expansion getItemsByGroup top-K (DEFAULT_GROUP_EXPAND_TOP_K).
  -- N2 = après theme-token drop (si ambigu (country, year)) — alias historique
  --      n_raw_results pour la rétro-compat front.
  -- N3 = après filtres applicatifs accept_listing — alias n_kept_results.
  n_summaries         INTEGER,    -- N0
  n_after_groups      INTEGER,    -- N1
  n_raw_results       INTEGER,    -- N2 (post-theme, alias historique)
  n_kept_results      INTEGER,    -- N3 (post-accept_listing)
  duration_ms         INTEGER,
  error               TEXT,
  created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_discovery_searches_run
  ON discovery_searches(run_id);
CREATE INDEX IF NOT EXISTS idx_discovery_searches_eurio
  ON discovery_searches(target_eurio_id);

-- ─── Discarded listings (audit trail des rejets accept_listing) ───────────
-- 1 row par listing rejeté avant ingestion (year_mismatch, wrong_currency,
-- noise_title, ...). But : auditer si un assouplissement futur récupèrerait
-- des listings utiles. Cf. ebay-postfilter-year-kickoff.md.

CREATE TABLE IF NOT EXISTS discarded_listings (
  id              TEXT PRIMARY KEY,
  run_id          TEXT REFERENCES source_runs(id) ON DELETE CASCADE,
  source          TEXT NOT NULL,
  source_ref      TEXT NOT NULL,
  target_eurio_id TEXT,
  reason          TEXT NOT NULL,
  title           TEXT,
  raw_payload     TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_discarded_listings_run
  ON discarded_listings(run_id);
CREATE INDEX IF NOT EXISTS idx_discarded_listings_reason
  ON discarded_listings(reason);

-- ─── Canonical coin referential (D-20) ────────────────────────────────────
-- Mirror SQLite de ml/datasets/eurio_referential.json. Bootstrappé via
-- `go-task ml:bootstrap-coins` (script ml/scripts/bootstrap_coins_from_referential.py).
-- Table source de vérité pour toutes les vues d'enrichissement (v_ebay_freshness,
-- futures v_*_freshness cross-source). Voir docs/sources-refacto/decisions.md D-20.

CREATE TABLE IF NOT EXISTS coins (
  eurio_id          TEXT PRIMARY KEY,
  country           TEXT NOT NULL,            -- ISO2 ('FR','DE',...,'eu' pour joint)
  country_name      TEXT,
  year              INTEGER NOT NULL,
  face_value        REAL NOT NULL,            -- 0.01 → 2.0
  is_commemorative  INTEGER NOT NULL DEFAULT 0,
  theme             TEXT,
  numista_id        INTEGER,
  raw_payload_json  TEXT,                     -- entrée JSON complète, pour audit
  imported_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_coins_country_year
  ON coins(country, year);
CREATE INDEX IF NOT EXISTS idx_coins_face_value
  ON coins(face_value);
CREATE INDEX IF NOT EXISTS idx_coins_commemorative
  ON coins(is_commemorative) WHERE is_commemorative = 1;
CREATE INDEX IF NOT EXISTS idx_coins_numista
  ON coins(numista_id) WHERE numista_id IS NOT NULL;

-- ─── Coin names i18n (eBay multi-marketplace) ─────────────────────────────
-- Titres Numista localisés (fr/en/de/it/es/nl) bootstrappés une fois pour
-- toutes via `ml/scripts/bootstrap_coin_names_i18n.py`. Consommés par le
-- matcher theme multilingue (`ml/sources/ebay/queries.py` post-I2). Cf.
-- docs/sources-refacto/ebay-multi-marketplace/language-probe.md §"Étape 2bis".

CREATE TABLE IF NOT EXISTS coin_names_i18n (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  lang       TEXT NOT NULL CHECK (lang IN ('fr','en','de','it','es','nl')),
  title      TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'numista',
  confidence TEXT NOT NULL DEFAULT 'canon',  -- 'canon' (scraped) | 'llm' | 'manual'
  model      TEXT,                            -- LLM model id when confidence='llm'
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, lang)
);

CREATE INDEX IF NOT EXISTS idx_coin_names_i18n_lang
  ON coin_names_i18n(lang);

-- ─── Freshness view eBay (D-20) ───────────────────────────────────────────
-- Driver de la freshness queue : pour chaque commémo 2€ non-EU, expose
-- last_enriched_at, n_images, n_crops via JOIN avec source_images. NULLS
-- FIRST au consommateur (SELECT ORDER BY ... NULLS FIRST), pas dans la vue.

CREATE VIEW IF NOT EXISTS v_ebay_freshness AS
SELECT
  c.eurio_id,
  c.country,
  c.year,
  MAX(si.fetched_at)        AS last_enriched_at,
  COUNT(DISTINCT si.id)     AS n_images,
  COUNT(DISTINCT ia.id)     AS n_crops
FROM coins c
LEFT JOIN source_images si
  ON si.target_eurio_id = c.eurio_id AND si.source = 'ebay'
LEFT JOIN image_assets ia
  ON ia.source_image_id = si.id
WHERE c.face_value = 2.0
  AND c.is_commemorative = 1
  AND c.country != 'eu'
GROUP BY c.eurio_id;
