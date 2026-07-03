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
  finished_at               TEXT,
  -- R3 (Model B) : origine machine (mac/pc/vps) où l'itération a été calculée,
  -- stampée à la création + poussée au canonique ; `summary_json` = snapshot
  -- dénormalisé des métriques (R@1/loss/verdict) pour afficher les chiffres
  -- partout sans pousser training_runs/benchmark_runs. Miroir : migration 0005.
  created_on                TEXT,
  summary_json              TEXT
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
  is_correct          INTEGER NOT NULL,      -- 1 if predicted_top1 == expected (strict eurio_id), else 0
  is_correct_eq       INTEGER NOT NULL DEFAULT 0,  -- 1 if equivalent on the COALESCE(design_group,eurio_id) mesh (server-recomputed at sync, source of truth for §5 R@1)
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
  error_summary   TEXT,
  pid             INTEGER                              -- pid du process qui tient le run (anti-orphan : ne reaper que si pid mort)
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

-- Lien M:N run ↔ source_image (Model B, parité A↔B).
-- `source_images` est une dimension dédupliquée globalement (1 image = 1 contenu,
-- clé naturelle UNIQUE(source, source_ref)) : la MÊME image ré-apparaît dans N runs
-- (re-scrape d'un groupe par la freshness queue). Sa colonne `run_id` est désormais
-- first-seen-immuable (provenance) ; cette table porte la containment PAR-RUN qu'un
-- run ultérieur ne peut plus voler. `export_run` scope source_images via ce lien.
CREATE TABLE IF NOT EXISTS source_image_runs (
  source_image_id TEXT NOT NULL REFERENCES source_images(id) ON DELETE CASCADE,
  run_id          TEXT NOT NULL REFERENCES source_runs(id)   ON DELETE CASCADE,
  first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (source_image_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_source_image_runs_run ON source_image_runs(run_id);

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
  -- Gate dénomination (C7 pilier 2) : verdict 2€ vs junk (probe DINO+bimétal),
  -- miroir de `face`. Écrit si NULL (anti-clobber). NULL = non évalué.
  denom                    TEXT
                           CHECK (denom IS NULL OR denom IN ('2eur','not_2eur')),
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

  -- Harmonisation : origine de l'image. 'collected' = scrapée (défaut
  -- historique), 'synthetic' = augmentée depuis le canonique, 'canonical' =
  -- image de référence. Ajoutée aux DB existantes via Store._ensure_column.
  origin                   TEXT
                           CHECK (origin IS NULL OR origin IN ('canonical','collected','synthetic')),

  -- Chantier crop-quality-overhaul (2026-06-03) : mesure d'inclinaison de la
  -- pièce dans le raw eBay. Calculées par scripts/crop_tilt_backfill_db.py
  -- (ou à la volée dans /crop-bench). Ajoutées aux DB existantes via
  -- Store._ensure_column. NULL = jamais mesuré.
  --   tilt_deg          : angle d'inclinaison (acos(axis_ratio)°), 0 = vertical
  --   axis_ratio        : rapport petit axe / grand axe de l'ellipse (1.0 = cercle parfait)
  --   tilt_trustworthy  : 1 si la mesure est fiable (fit concentrique, arc complet)
  tilt_deg                 REAL,
  axis_ratio               REAL,
  tilt_trustworthy         INTEGER DEFAULT 0,

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
  -- Face detection (C7) : reverse-ness vs obverse-ness. Renseignées seulement
  -- sur anchors_kind='2eur_all' (vitl14, même embedding que la banque revers).
  reverse_sim            REAL,
  face_margin            REAL,            -- reverse_sim - top1_sim
  denom_2eur_score       REAL,            -- C7 pilier 2 : score 2€-ness probe DINO+bimétal
  computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  duration_ms     INTEGER,
  -- Model B (C6b) : run_id du backfill DINO ayant produit la prédiction (sur des
  -- assets préexistants). NULL pour les prédictions du scrape normal (collectées
  -- par asset_id via le run parent de l'asset). export_run scope les prédictions
  -- backfill par run_id (les assets n'appartenant pas au run de backfill).
  run_id          TEXT REFERENCES source_runs(id) ON DELETE SET NULL,
  PRIMARY KEY (asset_id, encoder_version, anchors_kind)
);
CREATE INDEX IF NOT EXISTS idx_dino_pred_run ON image_asset_dino_predictions(run_id)
  WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_dino_pred_asset
  ON image_asset_dino_predictions(asset_id);
CREATE INDEX IF NOT EXISTS idx_dino_pred_top1
  ON image_asset_dino_predictions(top1_eurio_id);
-- idx_dino_pred_top1_country est créé dans Store._bootstrap après que
-- la colonne soit ajoutée via _ensure_column (sinon executescript()
-- pète sur les bases pré-existantes qui n'ont pas encore la colonne).

-- ─── Références Dino multi-exemplaires (improvement-loop B) ────────────────
-- La banque de suggestions `2eur_all` n'est plus 1 ancre canonique/classe : par
-- classe on garde le canonique + jusqu'à K vrais crops validés, choisis pour la
-- DIVERSITÉ d'apparence (farthest-point sampling dans l'espace DINO, plancher de
-- validité) — un crop sombre/tilté/usé matche mieux les photos réelles qu'un
-- énième scan parfait. Cette table trace la sélection (affichage coin-detail +
-- audit + override humain).
--   method : 'canonical'      = l'avers Numista (toujours présent, filet)
--            'fps'            = choisi auto par farthest-point sampling
--            'manual_pin'     = épinglé par un humain (toujours dans la banque)
--            'manual_exclude' = banni par un humain (jamais dans la banque)
-- Les rows 'canonical'/'fps' sont RÉÉCRITES à chaque build d'ancres ; les rows
-- 'manual_*' PERSISTENT (le builder les honore : pin forcé, exclude retiré).
CREATE TABLE IF NOT EXISTS dino_class_references (
  anchors_kind  TEXT NOT NULL DEFAULT '2eur_all',
  class_id      TEXT NOT NULL,            -- design_group ou eurio_id (maille classe)
  eurio_id      TEXT NOT NULL,            -- membre de la classe dont vient le crop
  asset_id      TEXT REFERENCES image_assets(id) ON DELETE CASCADE,  -- NULL = canonique
  method        TEXT NOT NULL
                CHECK (method IN ('canonical','fps','manual_pin','manual_exclude')),
  rank          INTEGER,                  -- ordre de sélection (0 = canonique)
  selected_sim  REAL,                     -- sim au set déjà retenu au moment du pick (FPS)
  built_at      TEXT NOT NULL DEFAULT (datetime('now')),
  -- NB SQLite : une colonne NULLABLE dans une PK n'est PAS dédupliquée (NULL ≠
  -- NULL) → la PK ci-dessous ne garantit l'unicité que pour les rows à asset_id
  -- non-NULL. L'unicité du canonique (asset_id NULL, 1 par classe) est imposée
  -- par l'index partiel `idx_dino_class_refs_canonical` plus bas.
  PRIMARY KEY (anchors_kind, class_id, eurio_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_dino_class_refs_asset
  ON dino_class_references(asset_id) WHERE asset_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dino_class_refs_class
  ON dino_class_references(anchors_kind, class_id);
-- Un seul canonique par classe (la PK ne le garantit pas, asset_id étant NULL).
CREATE UNIQUE INDEX IF NOT EXISTS idx_dino_class_refs_canonical
  ON dino_class_references(anchors_kind, class_id) WHERE asset_id IS NULL;

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
  -- Audit additive (chunk B 2026-05-25). Source de vérité figée pour
  -- chaque décision : version d'algo + snapshot du contexte qui a motivé
  -- l'écriture. Permet de retrouver dans 6 mois pourquoi un item a été
  -- décidé sans dépendre de tables annexes (image_asset_dino_predictions
  -- est REPLACE-able, review_claude_verdicts peut être re-judgé).
  --
  -- Format ``decision_engine_version`` :
  --   'human@v1'                            décision admin
  --   'auto_dino@s{sim_min}-d{spread_min}'  ex: 'auto_dino@s0.55-d0.05'
  --   'claude-sonnet-4-6'                   ack d'un verdict Claude
  --
  -- Format ``decision_metadata_json`` (libre, JSON validé côté code) :
  --   admin     : {"notes": "..."} ou {"reject_reason": "..."}
  --   auto_dino : {"sim": 0.71, "spread": 0.08, "top1": "...", "reason": "..."}
  --   claude    : {"model": "claude-sonnet-4-6", "confidence": 0.92,
  --                "face": "obverse", "raw_content": "...",
  --                "tokens_in": ..., "tokens_out": ..., "cost_usd": ...}
  decision_engine_version  TEXT,
  decision_metadata_json   TEXT NOT NULL DEFAULT '{}',
  enqueued_at              TEXT NOT NULL DEFAULT (datetime('now')),
  -- Lane de tri PERSISTÉE (WS1 2026-06-05). Plus d'heuristique recalculée à
  -- l'affichage : la lane est figée à l'enqueue par la règle centralisée
  -- (foundation/review_lanes.py) à partir du verdict Dino, et chaque carte /
  -- écran de review filtre dessus. `lane_source='human'` = déplacement manuel
  -- STICKY (un recalcul Dino ne ré-route jamais un item épinglé humain).
  -- lane NULL (items legacy avant backfill) est traité comme 'manual'.
  lane                     TEXT
                           CHECK (lane IS NULL OR lane IN ('manual','auto_accept','ccproxy')),
  lane_source              TEXT NOT NULL DEFAULT 'auto'
                           CHECK (lane_source IN ('auto','human')),
  UNIQUE (image_asset_id)
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status_priority
  ON review_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_review_queue_lane_status
  ON review_queue(lane, status);

-- ─── Verdicts Claude (chunk ccproxy) ─────────────────────────────────────
-- Un verdict Claude vision par review_queue item. La pipeline batch
-- ml/api/review_queue_routes.py (run_claude_batch) appelle ccproxy →
-- Sonnet 4.6 et persiste ici. L'humain acquitte ensuite via la page
-- /review/ccproxy (chunk 4), ce qui passe status à 'acked' ET commit la
-- décision finale dans review_queue (decided_by='claude_ack_human').
--
-- Une row par review_id (unique) — ré-exécution = REPLACE pour rafraîchir.
-- Le coût et les tokens sont stockés pour audit ; cf. bench
-- chunk 2 (project_claude_vision_bench).

CREATE TABLE IF NOT EXISTS review_claude_verdicts (
  review_id      TEXT PRIMARY KEY REFERENCES review_queue(id) ON DELETE CASCADE,
  model          TEXT NOT NULL,                    -- 'claude-sonnet-4-6' etc.
  verdict        TEXT NOT NULL CHECK (verdict IN ('match','no_match','uncertain','error')),
  face           TEXT CHECK (face IS NULL OR face IN ('obverse','reverse','unknown')),
  confidence     REAL,                              -- 0..1 si renvoyé par Claude
  raw_content    TEXT NOT NULL DEFAULT '',          -- réponse JSON brute (audit)
  tokens_in      INTEGER NOT NULL DEFAULT 0,
  tokens_out     INTEGER NOT NULL DEFAULT 0,
  cache_read     INTEGER NOT NULL DEFAULT 0,
  cost_usd       REAL NOT NULL DEFAULT 0,
  duration_ms    INTEGER NOT NULL DEFAULT 0,
  -- Cycle de vie côté humain :
  --   pending  → en attente d'acquittement (batch livré, humain pas encore vu)
  --   acked    → humain a validé la suggestion Claude (review_queue est passée à 'done')
  --   rejected → humain a rejeté la suggestion (l'item reste/retourne en queue manuelle)
  status         TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','acked','rejected')),
  computed_at    TEXT NOT NULL DEFAULT (datetime('now')),
  acked_at       TEXT,
  error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_claude_verdicts_status
  ON review_claude_verdicts(status, verdict);

-- ─── Verdicts de consensus (auto-validation redesign, C3) ────────────────
-- Le verdict d'ensemble (review/validation/consensus.py) persisté & versionné
-- par image_asset. Source de vérité unique du routage auto-validation : agrège
-- les avis d'experts (text + dino + crop_quality) en {accept,needs_review,reject}
-- + lane + confiance + règle déclenchée. Cf. docs/work-in-progress/
-- autovalidation-redesign.md §3/§7.
--
-- Une row par (image_asset_id, rule_version) — REPLACE au rerun de la MÊME
-- version (ON CONFLICT sur la PK), une NOUVELLE version coexiste (audit/replay
-- d'une règle révisée hors-ligne sans écraser l'historique). ``signals_json``
-- snapshote les Signals experts qui ont motivé le verdict (audit à froid, comme
-- review_queue.decision_metadata_json). Statut SHADOW jusqu'au câblage live :
-- la table peut être backfillée (scripts/persist_consensus.py) sans toucher la
-- décision de routage actuelle.

CREATE TABLE IF NOT EXISTS consensus_verdicts (
  image_asset_id TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  rule_version   INTEGER NOT NULL,
  outcome        TEXT NOT NULL CHECK (outcome IN ('accept','needs_review','reject')),
  lane           TEXT NOT NULL CHECK (lane IN ('manual','auto_accept','ccproxy')),
  confidence     REAL NOT NULL DEFAULT 0,
  reason         TEXT NOT NULL DEFAULT '',
  rule           TEXT NOT NULL,                 -- branche de décision (audit)
  signals_json   TEXT NOT NULL DEFAULT '[]',    -- snapshot des Signals experts
  computed_at    TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (image_asset_id, rule_version)
);

CREATE INDEX IF NOT EXISTS idx_consensus_verdicts_outcome
  ON consensus_verdicts(rule_version, outcome);

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
  -- URL d'appel Browse exacte (q + params résolus) — débug F3 : rejouer
  -- la requête. NULL si l'appel n'a pas atteint le serveur.
  browse_url          TEXT,
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
  -- Rescue rétroactif (C1 cohort-pipeline) : id de la source_image créée par
  -- POST /sources/discarded/{id}/rescue. NULL = pas encore sauvé.
  -- Sur les DB existantes, ajouté via Store._ensure_column.
  rescued_source_image_id TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  -- C2 cohort-pipeline : flag pré-calculé à l'INSERT pour la récupérabilité.
  -- Taxonomie :
  --   1 (rescue) : reason LIKE 'commemo_in_standard_run:%' ou reason = 'theme_mismatch'
  --                → pièce valide mais dans le mauvais bucket ; réattribution utile.
  --   0 (noise)  : reason IN ('noise_title','below_face','above_extreme','non_eur')
  --                → vrai bruit, pas de valeur pour le training.
  --   NULL       : tout le reste ('year_mismatch','commemo_keyword',
  --                'text_contradict_year','group_contradict_country',
  --                'group_contradict_denomination','text_contradict_country')
  --                → ambigu, évaluation ultérieure.
  -- Sur les DB existantes, colonne + backfill ajoutés via Store._bootstrap.
  -- NOTE : 'marketplace' existe en DB via _ensure_column mais PAS dans ce
  -- CREATE TABLE (géré dynamiquement pour compatibilité DB existantes/fraîches).
  is_rescue_candidate INTEGER,
  UNIQUE (source, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_discarded_listings_run
  ON discarded_listings(run_id);
CREATE INDEX IF NOT EXISTS idx_discarded_listings_reason
  ON discarded_listings(reason);
-- idx_discarded_listings_rescue est créé dans Store._bootstrap après que
-- is_rescue_candidate soit ajoutée via _ensure_column (sinon executescript
-- pète sur les bases pré-existantes qui n'ont pas encore la colonne).
-- Index UNIQUE explicite (en plus de la contrainte dans CREATE TABLE).
-- Sur les DB pré-C0 avec doublons, store.py dédupe d'abord (pre-bootstrap)
-- avant que executescript ne tente de créer cet index.
CREATE UNIQUE INDEX IF NOT EXISTS idx_discarded_listings_source_ref
  ON discarded_listings(source, source_ref);
-- idx_discarded_listings_rescued est créé dans Store._bootstrap après que
-- rescued_source_image_id soit ajoutée via _ensure_column (sinon executescript
-- pète sur les bases pré-existantes qui n'ont pas encore la colonne).

-- ════════════════════════════════════════════════════════════════════════
-- Machine à états explicite des crops (cohort-pipeline rebuild, 2026-06-06)
-- ════════════════════════════════════════════════════════════════════════
-- Modèle d'état ADDITIF : ne touche pas source_images/image_assets/review_queue
-- (le cœur qui marche). Exigence PO : fini les heuristiques temps-réel — chaque
-- transition d'un crop est journalisée (image_state_events, append-only) et
-- l'état courant est matérialisé (image_state_current, 1 ligne/crop) pour des
-- compteurs cockpit = SELECT direct, sans recompute. Alimenté en APPLICATIF via
-- store.emit_state_event aux call-sites du pipeline (chunk C2 — pas de trigger :
-- un trigger ne connaît ni l'acteur ni la raison ni le run_id). Le scoping
-- cockpit se fait par target_eurio_id (clé de découverte stable dès la création
-- du crop), PAS par cohort_id (un eurio_id peut être dans plusieurs cohortes).
-- Design complet : docs/cohort-pipeline/REBUILD-ANALYSIS.md (section DESIGN).
--
-- 9 états canoniques (réconcilient crop_status × resolution_status × rq.status) :
--   detected      crop créé, pas encore matché (pending_match, pas de rq)
--   auto_matched  match phash auto, terminal (resolution_status auto_phash/auto_name)
--   queued        en file de review, ouvert (rq.status='open')
--   in_review     pris en charge (rq.status='in_progress')
--   skipped       reporté par l'humain, reste à traiter (decision_notes='skipped' AND open)
--   resolved      tranché → eurio_id posé (resolution_status='manual' AND rq.status='done')
--   rejected      écarté (resolution_status='rejected')
--   orphaned      crop sans file ni résolution — recrop/run échoué (les ~544 invisibles)
--   superseded    remplacé par un recrop ultérieur

CREATE TABLE IF NOT EXISTS image_state_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,   -- ordre total monotone
  asset_id        TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  from_state      TEXT,                                -- NULL = première transition (∅ → …)
  to_state        TEXT NOT NULL
                  CHECK (to_state IN (
                    'detected','auto_matched','queued','in_review',
                    'skipped','resolved','rejected','orphaned','superseded'
                  )),
  actor           TEXT NOT NULL
                  CHECK (actor IN ('pipeline','human','auto_dino','ccproxy','recrop','system')),
  reason          TEXT,                                -- code court stable (catalogue design)
  eurio_id        TEXT,                                -- eurio_id posé à cette transition (si applicable)
  target_eurio_id TEXT,                                -- clé de découverte (scoping cohorte)
  run_id          TEXT,                                -- source_runs.id OU cohort_jobs.id (pas de FK : 2 cibles)
  detail_json     TEXT,                                -- libre : {v, fields, sim, spread, …} — 'fields' = payload sync rejouable
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  -- Sync multi-machine (local-sync 2026-07) : identité globale + horloge HLC.
  -- NULL = event legacy pré-sync (jamais poussé rétroactivement). Sur les DB
  -- antérieures, colonnes posées par le PRE-bootstrap _ensure_column (les index
  -- partiels ci-dessous sont créés par executescript → colonnes requises avant).
  op_id           TEXT,                                -- uuid4 hex — idempotence push/pull
  machine         TEXT,                                -- machine émettrice ('vps', 'macbook-a1b2', …)
  hlc             TEXT                                 -- '{ts_ms:013d}-{count:04d}-{machine}' : ordre lexico = ordre HLC
);
CREATE INDEX IF NOT EXISTS idx_ise_asset   ON image_state_events(asset_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_ise_target  ON image_state_events(target_eurio_id, to_state);
CREATE INDEX IF NOT EXISTS idx_ise_run     ON image_state_events(run_id);
CREATE INDEX IF NOT EXISTS idx_ise_created ON image_state_events(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ise_op_id ON image_state_events(op_id) WHERE op_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ise_hlc     ON image_state_events(hlc) WHERE hlc IS NOT NULL;

-- État courant matérialisé : 1 ligne par crop, tenue à jour par emit_state_event
-- dans la même transaction que l'INSERT du journal (chunk C2). Source des
-- compteurs cockpit (GROUP BY current_state). Projection garantie cohérente du
-- journal ; reconstructible depuis image_state_events en cas de doute.
CREATE TABLE IF NOT EXISTS image_state_current (
  asset_id        TEXT PRIMARY KEY REFERENCES image_assets(id) ON DELETE CASCADE,
  current_state   TEXT NOT NULL
                  CHECK (current_state IN (
                    'detected','auto_matched','queued','in_review',
                    'skipped','resolved','rejected','orphaned','superseded'
                  )),
  eurio_id        TEXT,                                -- identité résolue (NULL tant que non résolu)
  target_eurio_id TEXT,                                -- clé de découverte (scoping cockpit)
  last_event_id   INTEGER REFERENCES image_state_events(id),
  actor           TEXT,                                -- acteur de la dernière transition
  state_since     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_isc_target_state ON image_state_current(target_eurio_id, current_state);
CREATE INDEX IF NOT EXISTS idx_isc_state        ON image_state_current(current_state);

-- ════════════════════════════════════════════════════════════════════════
-- Sync event-log local ↔ canonique (local-sync, 2026-07)
-- ════════════════════════════════════════════════════════════════════════
-- Doctrine : docs/work-in-progress/local-sync/. Chaque mutation autoritative
-- appende un event estampillé (op_id, machine, hlc) ; un worker debounce
-- pousse/tire les events vers le canonique VPS ; chaque base matérialise en
-- rejouant par ordre HLC (LWW-par-champ). Le log d'audit n'est JAMAIS purgé —
-- seule la file d'envoi (sync_outbox) l'est, avec une marge d'un cycle.

-- File d'envoi locale. Une ligne par op à pousser (event ou tombstone).
-- 'pending' → poussé au prochain cycle ; 'pushed' → purgé au cycle réussi
-- SUIVANT (marge PO d'un sync). Vide en mode hub (VPS : EURIO_SYNC_MODE=hub).
CREATE TABLE IF NOT EXISTS sync_outbox (
  op_id      TEXT PRIMARY KEY,
  kind       TEXT NOT NULL DEFAULT 'event' CHECK (kind IN ('event','tombstone')),
  event_id   INTEGER REFERENCES image_state_events(id) ON DELETE CASCADE,  -- NULL si tombstone
  asset_id   TEXT,                                                          -- dénormalisé (debug/tombstone)
  status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','pushed')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  pushed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_outbox_status ON sync_outbox(status, created_at);

-- Tombstones de suppression : delete_crop CASCADE efface les events de l'asset,
-- donc la suppression voyage dans sa propre table (jamais CASCADE-ée). Terminal :
-- au replay, tout event d'un asset tombstoné est ignoré (delete gagne, v1).
CREATE TABLE IF NOT EXISTS sync_tombstones (
  asset_id     TEXT PRIMARY KEY,
  op_id        TEXT NOT NULL UNIQUE,
  machine      TEXT NOT NULL,
  hlc          TEXT NOT NULL,
  storage_path TEXT,                                   -- pour invalider le cache local au replay
  reason       TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- KV persistant du moteur de sync (survit aux restarts / --reload).
-- Clés : machine_id, hlc_last, pull_cursor_hlc, last_sync_at, last_sync_ok,
--        last_error, last_push_count, last_pull_count.
CREATE TABLE IF NOT EXISTS sync_state (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- Jobs cohorte observables (scrape eBay, recrop-zero). Remplace le dict
-- in-memory _recrop_jobs (perdu au restart FastAPI). Le worker écrit sa
-- progression au fil de l'eau → polling réel + survit aux restarts (corrige B2).
-- target_eurio_id + n_attributed_target → affichage honnête "0 attribué" (B1).
CREATE TABLE IF NOT EXISTS cohort_jobs (
  id                  TEXT PRIMARY KEY,                -- uuid hex
  kind                TEXT NOT NULL
                      CHECK (kind IN ('scrape_ebay','recrop_zero','census_recover')),
  cohort_id           TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,
  eurio_id            TEXT,                            -- NULL = job cohorte entière
  target_eurio_id     TEXT,                            -- pièce ciblée par le scrape (B1)
  run_id              TEXT,                            -- lien source_runs.id / image_assets.run_id
  status              TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running','done','failed','skipped')),
  n_total             INTEGER,                         -- items dans le scope au lancement (barre de progression)
  n_done              INTEGER NOT NULL DEFAULT 0,      -- items traités (mis à jour au fil de l'eau)
  n_produced          INTEGER NOT NULL DEFAULT 0,      -- crops/listings produits
  n_attributed_target INTEGER NOT NULL DEFAULT 0,      -- combien attribués à target_eurio_id (B1)
  tau                 REAL,                            -- seuil census utilisé (diagnostic "0 crop")
  started_at          TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at         TEXT,
  error               TEXT,
  note                TEXT,                            -- ex: "épuisé à τ=0.55 — 0 crop récupérable"
  pid                 INTEGER                          -- PID du subprocess détaché (recrop) → reaper boot précis (os.kill,0)
);
CREATE INDEX IF NOT EXISTS idx_cohort_jobs_cohort  ON cohort_jobs(cohort_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cohort_jobs_running ON cohort_jobs(status) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_cohort_jobs_target  ON cohort_jobs(target_eurio_id);

-- ════════════════════════════════════════════════════════════════════════
-- Jobs génériques — rail `ml/jobs/` (refacto-ml ADR D1)
-- ════════════════════════════════════════════════════════════════════════
-- Table DOMAINE-AGNOSTIQUE pour les jobs longs lancés en subprocess détaché
-- (start_new_session) qui survivent au `--reload` du worker. Généralise le
-- pattern éprouvé de `cohort_jobs` (cf. lab_routes recrop) hors du couplage
-- cohorte : pas de FK, `kind` libre, payload domaine en JSON `params`. Le reaper
-- boot (jobs.reaper.reap_orphans) ne tue QUE les jobs dont le PID est mort.
-- `cohort_jobs` reste séparée tant que ses runners ne sont pas migrés (ADR Q).
CREATE TABLE IF NOT EXISTS jobs (
  id          TEXT PRIMARY KEY,                -- uuid hex
  kind        TEXT NOT NULL,                   -- libre : 'training','scrape','augmentation',…
  status      TEXT NOT NULL DEFAULT 'running'
              CHECK (status IN ('running','done','failed','skipped')),
  pid         INTEGER,                         -- PID du subprocess détaché → reaper boot précis (os.kill,0)
  n_total     INTEGER,                         -- items dans le scope au lancement (barre de progression)
  n_done      INTEGER NOT NULL DEFAULT 0,      -- items traités (mis à jour au fil de l'eau)
  params      TEXT,                            -- JSON payload domaine (cohort_id, eurio_id, run_id, tau…)
  log_path    TEXT,                            -- chemin du log fichier du subprocess (stdout+stderr)
  note        TEXT,
  error       TEXT,
  started_at  TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_kind    ON jobs(kind, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_running ON jobs(status) WHERE status = 'running';

-- ════════════════════════════════════════════════════════════════════════
-- Référentiel canonique — harmonisation des données (docs/data-harmonization/)
-- ════════════════════════════════════════════════════════════════════════
-- `coins` n'est plus un miroir d'un JSON : c'est la table CANONIQUE. Voir
-- docs/data-harmonization/{architecture,schema-design}.md.

-- ─── referential_catalog — provenance brute du scrape référentiel ─────────
-- Remplace coin_catalog.json. 1 ligne = 1 pièce telle que la source
-- référentielle (Numista aujourd'hui, BCE demain) la décrit. Table mince :
-- raw_json est la vérité, les colonnes typées ne servent qu'au QA pré-`coins`.
CREATE TABLE IF NOT EXISTS referential_catalog (
  source              TEXT NOT NULL,          -- 'numista' (demain 'bce', …)
  source_native_id    TEXT NOT NULL,          -- ID natif, TEXT
  country_name        TEXT,
  year                INTEGER,
  face_value          REAL,
  type                TEXT,                   -- 'commemorative' | 'circulation'
  raw_json            TEXT NOT NULL,          -- payload complet (provenance)
  scrape_snapshot_ref TEXT,                   -- fichier sources/ immuable
  scraped_at          TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (source, source_native_id)
);

-- ─── design_groups — groupement de pièces partageant un design ────────────
-- Porté de Supabase (20260418_design_groups.sql). Unité de classe ArcFace.
CREATE TABLE IF NOT EXISTS design_groups (
  id                    TEXT PRIMARY KEY,     -- slug stable
  designation           TEXT NOT NULL,
  designation_i18n_json TEXT,
  description           TEXT,
  shared_obverse_url    TEXT,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── coins — référentiel canonique ────────────────────────────────────────
-- Colonnes nouvelles (harmonisation) ajoutées aux DB existantes via
-- Store._ensure_column ; les index sur ces colonnes sont créés dans
-- Store._bootstrap APRÈS les ALTER (sinon executescript pète sur les DB
-- antérieures). raw_payload_json/imported_at conservés transitoirement
-- (lecteurs : bench_routes, bootstrap_coins) — retirés dans un chunk ultérieur.
CREATE TABLE IF NOT EXISTS coins (
  eurio_id            TEXT PRIMARY KEY,
  country             TEXT NOT NULL,          -- ISO2 ('FR',…,'eu' pour joint)
  country_name        TEXT,
  year                INTEGER NOT NULL,
  face_value          REAL NOT NULL,          -- 0.01 → 2.0
  is_commemorative    INTEGER NOT NULL DEFAULT 0,
  theme               TEXT,
  numista_id          INTEGER,
  -- Ancrage à la source référentielle. NULLABLE tant que toutes les pièces
  -- ne sont pas générées depuis Numista (cf. schema-design.md §Chunk 1b).
  ref_source          TEXT,
  ref_native_id       TEXT,
  currency            TEXT NOT NULL DEFAULT 'EUR',
  collector_only      INTEGER NOT NULL DEFAULT 0,
  design_description  TEXT,
  mintage             INTEGER,
  mintage_source      TEXT,
  design_group_id     TEXT REFERENCES design_groups(id) ON DELETE SET NULL,
  -- Variantes first-class (chantier variantes). Chaque variante (coloured,
  -- hologram, gilded, mule, pattern…) est une pièce à part entière avec son
  -- propre eurio_id (`base-{kind}`) et pointe vers la canonique via
  -- `canonical_eurio_id`. Pas de contrainte FK sur le self-ref (insertion
  -- variante-avant-canonique tolérée ; soft-enforce via v_orphan_eurio_refs).
  variant_kind        TEXT NOT NULL DEFAULT 'classic',  -- classic|coloured|hologram|gilded|mule|mis-strike|pattern|other
  variant_label       TEXT,                             -- libellé humain (NULL si classic)
  canonical_eurio_id  TEXT,                             -- NULL si canonique ; sinon eurio_id de la canonique
  -- Cycle de vie (matérialisé, recalculé sur événement — Chunk 3).
  status              TEXT NOT NULL DEFAULT 'referenced'
                        CHECK (status IN ('referenced','trained')),
  status_computed_at  TEXT,
  needs_review        INTEGER NOT NULL DEFAULT 0,
  review_reason       TEXT,
  last_seen_in_catalog_at TEXT,               -- détection « disparue d'un re-scrape »
  raw_payload_json    TEXT,                   -- transitoire — décomposé en tables filles
  imported_at         TEXT NOT NULL DEFAULT (datetime('now')),  -- = date de création
  updated_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_coins_country_year
  ON coins(country, year);
CREATE INDEX IF NOT EXISTS idx_coins_face_value
  ON coins(face_value);
CREATE INDEX IF NOT EXISTS idx_coins_commemorative
  ON coins(is_commemorative) WHERE is_commemorative = 1;
CREATE INDEX IF NOT EXISTS idx_coins_numista
  ON coins(numista_id) WHERE numista_id IS NOT NULL;
-- Index sur les colonnes nouvelles : créés dans Store._bootstrap.

-- ─── Tables filles du référentiel ─────────────────────────────────────────
-- Pays participants d'une émission commune (1 ligne `coins` country='eu').
CREATE TABLE IF NOT EXISTS coin_national_variants (
  eurio_id     TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  country_iso2 TEXT NOT NULL,
  PRIMARY KEY (eurio_id, country_iso2)
) WITHOUT ROWID;

-- Références externes non-référentielles (wikipedia_url, lmdlp_url, …).
CREATE TABLE IF NOT EXISTS coin_cross_refs (
  eurio_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  ref_type  TEXT NOT NULL,
  ref_value TEXT NOT NULL,
  PRIMARY KEY (eurio_id, ref_type)
);
CREATE INDEX IF NOT EXISTS idx_coin_cross_refs_value
  ON coin_cross_refs(ref_type, ref_value);

-- Observations hétérogènes par source (payload semi-structuré volontaire).
CREATE TABLE IF NOT EXISTS coin_observations (
  id               INTEGER PRIMARY KEY,
  eurio_id         TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source           TEXT NOT NULL,
  observation_type TEXT NOT NULL,
  payload_json     TEXT NOT NULL,
  recorded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (eurio_id, source, observation_type)
);
CREATE INDEX IF NOT EXISTS idx_coin_observations_eurio
  ON coin_observations(eurio_id);

-- Images de référence (Numista obverse/reverse) — distinctes de image_assets.
CREATE TABLE IF NOT EXISTS coin_canonical_images (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source     TEXT NOT NULL,
  role       TEXT NOT NULL CHECK (role IN ('obverse','reverse')),
  url        TEXT,
  local_path TEXT,
  PRIMARY KEY (eurio_id, source, role)
) WITHOUT ROWID;

-- Appartenance d'une pièce à une cohorte (remplace experiment_cohorts.eurio_ids_json).
CREATE TABLE IF NOT EXISTS cohort_members (
  cohort_id TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,
  eurio_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  PRIMARY KEY (cohort_id, eurio_id)
) WITHOUT ROWID;

-- Journal de migration d'identité (rename/split/merge/retire). Exportable en
-- JSON versionné git — cf. docs/data-harmonization/schema-design.md.
CREATE TABLE IF NOT EXISTS eurio_id_migrations (
  id           INTEGER PRIMARY KEY,
  batch_id     TEXT NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('rename','split','merge','retire')),
  old_eurio_id TEXT NOT NULL,
  new_eurio_id TEXT,
  resolution   TEXT NOT NULL CHECK (resolution IN ('deterministic','needs_rematch')),
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','applied')),
  reason       TEXT,
  decided_by   TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eurio_id_migrations_old
  ON eurio_id_migrations(old_eurio_id);
CREATE INDEX IF NOT EXISTS idx_eurio_id_migrations_new
  ON eurio_id_migrations(new_eurio_id);

-- ─── Coin names i18n (eBay multi-marketplace) ─────────────────────────────
-- Titres Numista localisés (fr/en/de/it/es/nl) bootstrappés une fois pour
-- toutes via `ml/scripts/bootstrap_coin_names_i18n.py`. Consommés par le
-- matcher theme multilingue (`ml/sources/ebay/queries.py` post-I2). Cf.
-- docs/sources-refacto/ebay-multi-marketplace/language-probe.md §"Étape 2bis".

-- `source` : registry id (vraie source de la donnée — `numista_api`, `manual`, ...)
-- `method` : méthode de dérivation depuis cette source (NULL = direct/canon ;
--            'llm_v1' = LLM-traduit ; 'acronym_extract' / 'llm' pour aliases).
-- Distinction acquise 2026-05-25 (chunk P.3b) : la colonne `source` mélangeait
-- avant "vraie source" et "méthode" (ex: 'llm_v1' qui est une méthode, pas une
-- source). Cf. docs/coin-richness/ROADMAP-DB.md §3.4. La FK source s'enclenche
-- au recreate P.6.
CREATE TABLE IF NOT EXISTS coin_names_i18n (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  lang       TEXT NOT NULL CHECK (lang IN ('fr','en','de','it','es','nl')),
  title      TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'numista_api',
  method     TEXT,                            -- 'llm_v1' | 'canon' | 'manual' | NULL
  confidence TEXT NOT NULL DEFAULT 'canon',   -- legacy 'canon' (scraped) | 'llm' | 'manual'
  model      TEXT,                            -- LLM model id when method LIKE 'llm%'
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, lang)
);

CREATE INDEX IF NOT EXISTS idx_coin_names_i18n_lang
  ON coin_names_i18n(lang);

-- ─── coin_topics — contexte verbeux multi-source per lang ─────────────────
-- (chantier D, 2026-05-26) — Numista expose `commemorated_topic` (ex: "100
-- years of Independence") qui contient l'info contextuelle absente du
-- `title` court ("2 Euros (Independence)"). BCE expose le `feature`
-- verbeux similaire ("Dessin commémoratif : 100e anniversaire...").
--
-- Cette table héberge ces topics avec leur source-of-truth + langue :
-- 1 row par (eurio_id, source, lang). Permet :
-- - le slug verbeux eurio_id (`commemorated_topic` Numista EN, slugifié)
-- - l'affichage UI multi-source avec badges (numista/bce/...)
-- - le theme-matcher eBay enrichi (tokens "100 years anniversary")
-- - les traductions LLM dérivées des canon EN+FR
CREATE TABLE IF NOT EXISTS coin_topics (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source     TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  lang       TEXT NOT NULL CHECK (lang IN ('fr','en','de','it','es','nl')),
  topic      TEXT NOT NULL,
  method     TEXT,                            -- 'api'|'scrape'|'llm_v1'|'manual'
  model      TEXT,                            -- LLM model id when method LIKE 'llm%'
  confidence TEXT NOT NULL DEFAULT 'canon',   -- 'canon' | 'assisted' | 'uncertain'
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, source, lang)
);

CREATE INDEX IF NOT EXISTS idx_coin_topics_source
  ON coin_topics(source);
CREATE INDEX IF NOT EXISTS idx_coin_topics_lang
  ON coin_topics(lang);

-- ─── coin_descriptions_i18n — titre + description officiels BCE 24 langues ──
-- (chantier BCE i18n, 2026-05-29) — La BCE publie chaque pièce commémorative
-- dans les 24 langues officielles de l'UE (comm_{year}.{lang}.html), avec un
-- titre (Feature) et une description officiels traduits par la BCE elle-même.
--
-- Différences avec les tables i18n existantes :
-- - coin_names_i18n  = titres Numista, 6 langs app, 1 row/(eurio_id,lang).
-- - coin_topics      = topic court multi-source, 6 langs, sans description.
-- - coin_descriptions_i18n = source officielle BCE, **24 langues UE**, et garde
--   TITRE + DESCRIPTION appariés (la BCE les fournit ensemble par langue).
--
-- 1 row par (eurio_id, source, lang). `source` = registry id ('bce_official').
-- Les facts lang-invariants (tirage, date d'émission) ne vivent PAS ici — ils
-- sont scrapés une seule fois (axes dédiés) ; cette table = texte localisé seul.
-- `method` : 'scrape' (canon BCE) | 'llm_v1' | 'manual'. `confidence` aligné
-- sur coin_topics ('canon' | 'assisted' | 'uncertain').
CREATE TABLE IF NOT EXISTS coin_descriptions_i18n (
  eurio_id    TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source      TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  lang        TEXT NOT NULL CHECK (lang IN (
                'bg','cs','da','de','el','en','es','et','fi','fr','ga','hr',
                'hu','it','lt','lv','mt','nl','pl','pt','ro','sk','sl','sv')),
  title       TEXT NOT NULL,
  description TEXT,
  method      TEXT,                            -- 'scrape' | 'llm_v1' | 'manual'
  model       TEXT,                            -- LLM model id when method LIKE 'llm%'
  confidence  TEXT NOT NULL DEFAULT 'canon',   -- 'canon' | 'assisted' | 'uncertain'
  fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, source, lang)
);

CREATE INDEX IF NOT EXISTS idx_coin_descriptions_i18n_lang
  ON coin_descriptions_i18n(lang);

-- ─── Alias de thème (chunk C2a — recall theme-matcher) ────────────────────
-- Modèle `altLabel` de Wikidata : en plus du titre canonique i18n, des
-- surface forms supplémentaires d'une commémo — acronymes (« EMI »),
-- termes de marché / surnoms (« Studentenrevolte », « Iris »). Le
-- theme-matcher poole ces alias avec les tokens i18n.
--
-- `alias` est stocké NORMALISÉ (lowercase, sans accents — cf.
-- theme_tokens.normalize). `source` : 'acronym' (extrait des parenthèses
-- d'un titre i18n), 'llm' (généré par LLM ancré), 'manual'. Matching en
-- limite de mot (un acronyme court ne doit pas matcher en sous-chaîne).

-- `source` : registry id (vraie source). `method` : comment l'alias a été
-- dérivé de cette source ('acronym' = extracted from a title's parenthesized
-- acronym, 'llm' = generated by LLM grounding, 'manual' = curated, NULL =
-- direct alias from the source). Cf. note coin_names_i18n.
CREATE TABLE IF NOT EXISTS coin_aliases (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  lang       TEXT NOT NULL,   -- ISO 639-1, ou 'xx' si language-agnostic
  alias      TEXT NOT NULL,   -- forme normalisée
  source     TEXT NOT NULL DEFAULT 'numista_api',
  method     TEXT,            -- 'acronym' | 'llm' | 'manual' | NULL
  confidence TEXT NOT NULL DEFAULT 'high',
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, lang, alias)
);

CREATE INDEX IF NOT EXISTS idx_coin_aliases_eurio
  ON coin_aliases(eurio_id);

-- ─── Freshness views eBay (D-20 ; maille groupe — chunk 6) ────────────────
-- Une recherche eBay = un groupe de découverte (dénomination, pays,
-- année), pas une pièce : deux commémos-sœurs partagent une requête
-- byte-identique, et chaque listing est attribué à l'une d'elles — ou à
-- aucune (verdict ambigu) — par le theme-match (source_images.target_eurio_id).
--
-- `v_ebay_freshness_groups` est la vue canonique : elle pilote la
-- freshness queue (une recherche couvre tout un groupe). `v_ebay_freshness`
-- en est la PROJECTION à la maille eurio_id (une ligne par pièce) : chaque
-- pièce hérite de la freshness de SON groupe, jamais de ses seuls listings
-- attribués. C'est la cohérence voulue (chunk 6) — sinon une pièce dont le
-- groupe a bien été cherché apparaît « never enriched » dès lors qu'aucun
-- listing ne lui a été attribué (toutes les sœurs ont capté, ou verdict
-- ambigu → target_eurio_id NULL), et la queue la re-cible indéfiniment.
--
-- Vues drop+create (pas `IF NOT EXISTS`) : une vue n'a pas de données,
-- les redéfinir à chaque bootstrap garde leur définition toujours à jour
-- sur les DB existantes. NULLS FIRST est posé au consommateur
-- (ORDER BY … NULLS FIRST), pas dans la vue.

DROP VIEW IF EXISTS v_ebay_freshness;
DROP VIEW IF EXISTS v_ebay_freshness_groups;

CREATE VIEW v_ebay_freshness_groups AS
SELECT
  c.face_value               AS denomination,
  c.country                  AS country,
  c.year                     AS year,
  COUNT(DISTINCT c.eurio_id)  AS n_coins,
  MAX(si.fetched_at)          AS last_enriched_at,
  COUNT(DISTINCT si.id)       AS n_images,
  COUNT(DISTINCT ia.id)       AS n_crops
FROM coins c
LEFT JOIN source_images si
  ON si.target_eurio_id = c.eurio_id AND si.source = 'ebay'
LEFT JOIN image_assets ia
  ON ia.source_image_id = si.id
WHERE c.face_value = 2.0
  AND c.is_commemorative = 1
  AND c.country != 'eu'
  AND c.canonical_eurio_id IS NULL   -- canoniques seules (pas les variantes)
GROUP BY c.face_value, c.country, c.year;

CREATE VIEW v_ebay_freshness AS
SELECT
  c.eurio_id,
  c.country,
  c.year,
  g.last_enriched_at,
  g.n_images,
  g.n_crops
FROM coins c
JOIN v_ebay_freshness_groups g
  ON g.denomination = c.face_value
 AND g.country      = c.country
 AND g.year         = c.year
WHERE c.face_value = 2.0
  AND c.is_commemorative = 1
  AND c.country != 'eu'
  AND c.canonical_eurio_id IS NULL;  -- canoniques seules (pas les variantes)

-- ─── Freshness view eBay — pièces STANDARD (maille pays) ──────────────────
-- Un standard (is_commemorative = 0) n'a PAS de thème par année : sa face
-- nationale est identique sur toute une *ère de design* (carte 1ʳᵉ/2ᵉ,
-- portrait, type), et une ère = une ligne canonique `coins` dont `year` est
-- l'année de *début*. Le grouping commémo `(dénom, pays, année)` est donc
-- inadapté : une seule recherche large « 2 euro {pays} » couvre toutes les
-- ères d'un pays. La maille du groupe standard est `(dénomination, pays)` —
-- PAS l'année. `n_eras` = nombre de *design_groups avers* du pays (Types
-- partageant un avers collapsés via COALESCE(design_group_id, eurio_id) —
-- cf. chantier design-groups-standards), c'est-à-dire le nombre de classes
-- ArcFace réellement visées. Toutes cherchées par la recherche large ;
-- l'attribution à un groupe se fait en aval par appartenance de plage d'années
-- (sources/ebay/standards.py). Un Type sans design_group reste compté pour 1.
--
-- Drop+create (cf. note des vues freshness commémo ci-dessus).
DROP VIEW IF EXISTS v_ebay_standard_groups;

CREATE VIEW v_ebay_standard_groups AS
SELECT
  c.face_value               AS denomination,
  c.country                  AS country,
  COUNT(DISTINCT COALESCE(c.design_group_id, c.eurio_id))  AS n_eras,
  MAX(si.fetched_at)          AS last_enriched_at,
  COUNT(DISTINCT si.id)       AS n_images,
  COUNT(DISTINCT ia.id)       AS n_crops
FROM coins c
LEFT JOIN source_images si
  ON si.target_eurio_id = c.eurio_id AND si.source = 'ebay'
LEFT JOIN image_assets ia
  ON ia.source_image_id = si.id
WHERE c.face_value = 2.0
  AND c.is_commemorative = 0
  AND c.country != 'eu'
  AND c.canonical_eurio_id IS NULL   -- canoniques (ères) seules ; pas les
                                     -- variantes pattern/mule/coloured
GROUP BY c.face_value, c.country;

-- ─── QA : références eurio_id orphelines ──────────────────────────────────
-- Plusieurs colonnes pointent un eurio_id sans contrainte FK (par design :
-- target_eurio_id est une *hypothèse* de match, autorisée à être fausse).
-- Cette vue les OBSERVE — elle ne les contraint pas. Cf. schema-design.md §Q7.
DROP VIEW IF EXISTS v_orphan_eurio_refs;
CREATE VIEW v_orphan_eurio_refs AS
  SELECT 'source_images.target_eurio_id' AS ref, si.target_eurio_id AS eurio_id,
         COUNT(*) AS n
    FROM source_images si
    LEFT JOIN coins c ON c.eurio_id = si.target_eurio_id
   WHERE si.target_eurio_id IS NOT NULL AND c.eurio_id IS NULL
   GROUP BY si.target_eurio_id
  UNION ALL
  SELECT 'image_assets.eurio_id', ia.eurio_id, COUNT(*)
    FROM image_assets ia
    LEFT JOIN coins c ON c.eurio_id = ia.eurio_id
   WHERE ia.eurio_id IS NOT NULL AND c.eurio_id IS NULL
   GROUP BY ia.eurio_id
  UNION ALL
  SELECT 'training_run_classes.class_id', trc.class_id, COUNT(*)
    FROM training_run_classes trc
    LEFT JOIN coins c ON c.eurio_id = trc.class_id
   WHERE trc.class_kind = 'eurio_id' AND c.eurio_id IS NULL
   GROUP BY trc.class_id
  UNION ALL
  SELECT 'coin_market_quotes.eurio_id', cmq.eurio_id, COUNT(*)
    FROM coin_market_quotes cmq
    LEFT JOIN coins c ON c.eurio_id = cmq.eurio_id
   WHERE cmq.eurio_id IS NOT NULL AND c.eurio_id IS NULL
   GROUP BY cmq.eurio_id
  UNION ALL
  -- Variante pointant vers une canonique absente (canonique non découverte).
  SELECT 'coins.canonical_eurio_id', cv.canonical_eurio_id, COUNT(*)
    FROM coins cv
    LEFT JOIN coins c ON c.eurio_id = cv.canonical_eurio_id
   WHERE cv.canonical_eurio_id IS NOT NULL AND c.eurio_id IS NULL
   GROUP BY cv.canonical_eurio_id;

-- ─── Cycle de vie : readiness à l'entraînement (Chunk 3) ──────────────────
-- Base de la « condition d'éligibilité à une cohorte » : nombre d'images
-- d'entraînement par pièce. Le seuil (« assez d'images ») est appliqué par
-- le consommateur, pas figé ici.
DROP VIEW IF EXISTS v_coin_training_readiness;
CREATE VIEW v_coin_training_readiness AS
SELECT
  c.eurio_id,
  c.status,
  c.design_group_id,
  COUNT(ia.id)                                              AS n_images,
  SUM(CASE WHEN ia.training_eligible = 1 THEN 1 ELSE 0 END)  AS n_training_eligible
FROM coins c
LEFT JOIN image_assets ia ON ia.eurio_id = c.eurio_id
GROUP BY c.eurio_id;

-- ════════════════════════════════════════════════════════════════════════
-- Coin richness — doctrine provenance first-class (docs/coin-richness/)
-- ════════════════════════════════════════════════════════════════════════
-- Ajout 2026-05-25 (chunk P.3a). Tables additives uniquement — la
-- recréation des 6 tables source-aware existantes (coin_observations,
-- coin_market_quotes, referential_catalog, coin_canonical_images,
-- coin_aliases, coin_names_i18n) pour leur ajouter la FK source →
-- source_registry est déférée au script wipe P.6 (sous garde-fou
-- interactif), où elle s'enchaîne naturellement avec le wipe des données.
--
-- Cf. ROADMAP-DB.md §3 et §4, chantier-C-mintage.md §"Pattern".

-- ─── source_registry — catalogue des sources de données ──────────────────
-- Toute table source-aware (observations, prices, credits, source_refs)
-- référence ce registry via FK ON DELETE RESTRICT : on ne retire pas une
-- source qui a écrit en DB sans nettoyer ses observations d'abord.
CREATE TABLE IF NOT EXISTS source_registry (
  id           TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  kind         TEXT NOT NULL
               CHECK (kind IN ('official','reference','community','manual','derived')),
  base_url     TEXT,
  notes        TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── coin_source_status — disponibilité de données par (coin × source) ────
-- Chantier disponibilité (2026-05-30). 1 row par (eurio_id, source). `state`
-- = verdict de la dernière tentative connue :
--   'never'          : jamais tenté — en pratique l'ABSENCE de row vaut never,
--                      on n'insère donc pas de rows vides (la lecture défaute).
--   'ok'             : données présentes pour cette source.
--   'empty_upstream' : tenté, mais la source ne publie (pas encore) la donnée
--                      — signal POSITIF uniquement (404 page-année BCE, ou coin
--                      absent des blocs d'une page existante). Ex : commémo
--                      2025/2026 pas encore sur le site BCE.
--   'error'          : tentative échouée (réseau/HTTP/parse/WAF). Toute
--                      incertitude tombe ici, JAMAIS dans empty_upstream.
-- `detail_json` : {axes:{...booléens/compteurs par axe}, error:str|null,
-- partial:bool} — grain fin par source sans lignes par axe. `last_checked_at`
-- NULL = jamais tenté (distingue never d'un verdict réseau). Table générique :
-- vaut pour toute source du registry (BCE/Numista aujourd'hui, eBay/LMDLP/… demain).
CREATE TABLE IF NOT EXISTS coin_source_status (
  eurio_id        TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source          TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  state           TEXT NOT NULL DEFAULT 'never'
                  CHECK (state IN ('never','ok','empty_upstream','error')),
  detail_json     TEXT NOT NULL DEFAULT '{}',
  last_run_id     TEXT REFERENCES source_runs(id) ON DELETE SET NULL,
  last_checked_at TEXT,
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, source)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_coin_source_status_source_state
  ON coin_source_status(source, state);

-- ─── mints — ateliers monétaires normalisés ──────────────────────────────
-- Slug PK stable (`de-berlin-a`, `fr-pessac`, `it-roma-r`, ...). Référencé
-- par coin_mint_releases.mint_id. NULL côté coin_mint_releases =
-- atelier inconnu ou non-décomposé.
CREATE TABLE IF NOT EXISTS mints (
  id            TEXT PRIMARY KEY,
  country       TEXT NOT NULL,
  mark          TEXT,
  city          TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  founded_year  INTEGER,
  notes         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mints_country ON mints(country);

-- ─── coin_variants — DÉPRÉCIÉ (chantier variantes) ───────────────────────
-- ⚠ DÉPRÉCIÉ : les variantes sont désormais des pièces `coins` first-class
-- (colonnes coins.variant_kind / variant_label / canonical_eurio_id). Cette
-- table n'est plus alimentée par le writer ; conservée en lecture le temps de
-- la migration (scripts/migrate_coin_variants_to_coins.py). DROP dans un
-- chunk de nettoyage ultérieur.
CREATE TABLE IF NOT EXISTS coin_variants (
  id              TEXT PRIMARY KEY,
  parent_type_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  finish          TEXT NOT NULL
                  CHECK (finish IN ('classic','coloured','hologram','gilded','pattern','mule','misstrike','other')),
  obverse_url     TEXT,
  reverse_url     TEXT,
  notes           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_coin_variants_parent ON coin_variants(parent_type_id);

-- ─── coin_mint_releases — identity-only (mintage en observations) ────────
-- 1 ligne = 1 émission (Type × année × atelier × issue_type). Pas de
-- `mintage` ni `released_on` dans la table : ces facts vivent dans
-- mint_release_observations avec leur source.
CREATE TABLE IF NOT EXISTS coin_mint_releases (
  id              TEXT PRIMARY KEY,                -- '{parent}/{year}/{mint_id|noMint}/{type}'
  parent_type_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  mint_year       INTEGER NOT NULL,
  mint_id         TEXT REFERENCES mints(id) ON DELETE RESTRICT,
  issue_type      TEXT NOT NULL
                  CHECK (issue_type IN ('CIRC','BU','BE','PROOF','COIN_CARD','OTHER')),
  notes           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (parent_type_id, mint_year, mint_id, issue_type)
);
CREATE INDEX IF NOT EXISTS idx_mr_parent ON coin_mint_releases(parent_type_id);
CREATE INDEX IF NOT EXISTS idx_mr_year   ON coin_mint_releases(parent_type_id, mint_year);

-- ─── coin_source_refs — refs polymorphes vers sources externes ───────────
-- Une row = un lien (target × source × native_id). Polymorphe sur
-- target_kind : pointe vers un coin, un variant ou un mint_release.
CREATE TABLE IF NOT EXISTS coin_source_refs (
  id               INTEGER PRIMARY KEY,
  target_kind      TEXT NOT NULL CHECK (target_kind IN ('coin','variant','mint_release')),
  target_id        TEXT NOT NULL,
  source           TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_native_id TEXT NOT NULL,
  source_url       TEXT,
  notes            TEXT,
  fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (target_kind, target_id, source)
);
CREATE INDEX IF NOT EXISTS idx_coin_source_refs_target
  ON coin_source_refs(target_kind, target_id);
CREATE INDEX IF NOT EXISTS idx_coin_source_refs_native
  ON coin_source_refs(source, source_native_id);

-- ─── mint_release_observations — facts avec source (mintage, released_on, ...) ──
-- Pas de CHECK strict sur fact_type : libre pour absorber les facts
-- découverts pendant la cohorte (mintage, released_on, frequency, notes, ...).
-- Pas de colonne `confidence` : la doctrine la juge flottante ; la confiance
-- se dérive en lecture (registry.kind + agreement count).
CREATE TABLE IF NOT EXISTS mint_release_observations (
  id              INTEGER PRIMARY KEY,
  mint_release_id TEXT NOT NULL REFERENCES coin_mint_releases(id) ON DELETE CASCADE,
  fact_type       TEXT NOT NULL,
  value_json      TEXT NOT NULL,
  source          TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_ref      TEXT,
  observed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  notes           TEXT,
  UNIQUE (mint_release_id, fact_type, source)
);
CREATE INDEX IF NOT EXISTS idx_mro_release ON mint_release_observations(mint_release_id);
CREATE INDEX IF NOT EXISTS idx_mro_fact    ON mint_release_observations(fact_type);
CREATE INDEX IF NOT EXISTS idx_mro_source  ON mint_release_observations(source);

-- ─── mint_release_prices — prix × grade × source × mint_release ──────────
-- Granularité fine pour les sources qui décomposent par atelier (Numista
-- 7 grades, MdP catalogue). Complémentaire de coin_market_quotes qui agrège
-- au niveau Type (eBay, LMDLP).
CREATE TABLE IF NOT EXISTS mint_release_prices (
  id               INTEGER PRIMARY KEY,
  mint_release_id  TEXT NOT NULL REFERENCES coin_mint_releases(id) ON DELETE CASCADE,
  source           TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_ref       TEXT,
  grade_raw        TEXT NOT NULL CHECK (grade_raw IN ('g','vg','f','vf','xf','au','unc')),
  grade_eurio      TEXT CHECK (grade_eurio IN ('UNC','TTB','TB')),
  price            REAL NOT NULL,
  currency         TEXT NOT NULL DEFAULT 'EUR',
  fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (mint_release_id, source, grade_raw, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_mrp_release ON mint_release_prices(mint_release_id);
CREATE INDEX IF NOT EXISTS idx_mrp_source  ON mint_release_prices(source);

-- ─── coin_credits — graveur avers/revers/sculpteur ───────────────────────
-- `source` en PK : deux sources peuvent attribuer le même rôle à des
-- personnes différentes, on garde les deux lignes (provenance first-class).
CREATE TABLE IF NOT EXISTS coin_credits (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('designer','engraver','sculptor')),
  name       TEXT NOT NULL,
  source     TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_ref TEXT,
  position   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (eurio_id, role, name, source)
);
CREATE INDEX IF NOT EXISTS idx_coin_credits_name ON coin_credits(name);

-- ─── coin_edge_variants — tranche A/B (DE 2007-2008 uniquement) ──────────
-- Petite table, source unique (curation manuelle), pas de FK source car
-- toujours `manual` (1-1 mappable au registry).
CREATE TABLE IF NOT EXISTS coin_edge_variants (
  eurio_id TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  variant  TEXT NOT NULL CHECK (variant IN ('A','B')),
  mintage  INTEGER,
  notes    TEXT,
  PRIMARY KEY (eurio_id, variant)
);

-- ─── coin_series — séries fermées (Bundesländer, etc.) ──────────────────
-- Concept éditorial : un Type appartient (au plus) à une série. Une série
-- regroupe des Types qui partagent un theme curaté + une fenêtre temporelle
-- (Bundesländer 2006-2022, etc.). Distinct de design_groups qui lie des
-- pays autour d'un même design (joint-issues).
--
-- Migré depuis Supabase en P.8a (doctrine SQLite-only). minting_end_reason :
-- 'completed' (série terminée), 'merged' (fusionnée), 'abandoned'.
CREATE TABLE IF NOT EXISTS coin_series (
  id                      TEXT PRIMARY KEY,
  country                 TEXT NOT NULL,
  designation             TEXT NOT NULL,
  designation_i18n_json   TEXT,
  description             TEXT,
  minting_started_at      TEXT NOT NULL,
  minting_ended_at        TEXT,
  minting_end_reason      TEXT,
  superseded_by_series_id TEXT REFERENCES coin_series(id) ON DELETE SET NULL,
  supersedes_series_id    TEXT REFERENCES coin_series(id) ON DELETE SET NULL,
  created_at              TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_coin_series_country ON coin_series(country);

-- ─── coin_embeddings — vecteur ArcFace par eurio_id × model_version ─────
-- Stocké comme BLOB float32 raw (numpy.tobytes()). Permet de répondre à la
-- question "ce coin est-il dans le set d'entraînement du modèle vX ?" sans
-- requêter training_run_classes (qui est run-keyed, pas model-version-keyed).
--
-- PK composite : un coin peut avoir plusieurs embeddings (re-trained sur N
-- versions de modèle). En pratique, le frontend lit juste model_version =
-- "le coin existe-t-il" (cf. useCoinLookups.useTrainedEurioIds).
CREATE TABLE IF NOT EXISTS coin_embeddings (
  eurio_id      TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  model_version TEXT NOT NULL,
  embedding     BLOB,
  dim           INTEGER,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, model_version)
);
CREATE INDEX IF NOT EXISTS idx_coin_embeddings_model
  ON coin_embeddings(model_version);

-- ─── sets / set_members — collections éditoriales ───────────────────────
-- Concept produit : une "set" est une collection thématique (ex: "Premiers
-- millésimes", "Capitales européennes") affichée dans l'app comme un défi.
-- Migré depuis Supabase en P.8a. name_i18n JSON contient les libellés par
-- langue ({fr: "...", en: "..."}).
CREATE TABLE IF NOT EXISTS sets (
  id                TEXT PRIMARY KEY,
  name_i18n         TEXT NOT NULL,     -- JSON {lang: title}
  description_i18n  TEXT,              -- JSON
  category          TEXT NOT NULL,     -- ex: 'theme', 'country', 'year'
  kind              TEXT NOT NULL,     -- ex: 'static', 'dynamic'
  param_key         TEXT,              -- pour les sets dynamiques
  criteria          TEXT,              -- JSON (filtres dynamiques)
  display_order     INTEGER NOT NULL DEFAULT 0,
  expected_count    INTEGER,
  icon              TEXT,
  reward            TEXT,              -- JSON
  active            INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sets_active ON sets(active) WHERE active = 1;
CREATE INDEX IF NOT EXISTS idx_sets_category ON sets(category);

CREATE TABLE IF NOT EXISTS set_members (
  set_id   TEXT NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
  eurio_id TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  position INTEGER,
  PRIMARY KEY (set_id, eurio_id)
);
CREATE INDEX IF NOT EXISTS idx_set_members_eurio ON set_members(eurio_id);

-- Énumération par pièce des 2 € commémoratives, source nl.wikipedia
-- « Lijst van herdenkingsmunten van € 2 » (un tableau par année, une ligne
-- par pièce : pays + thème néerlandais). Couche « attendu » du référentiel :
-- donne le compteur ET l'identité (thème) de chaque pièce, matchée à un
-- eurio_id quand on l'a en base (sinon matched_eurio_id NULL = manquante).
-- Wikipédia reste overview/filet (doctrine official-only) : on ne stocke ni
-- n'affiche son image, juste le thème pour l'identité. Les émissions communes
-- (« Europese Unie », 2007/2009/2012/2015/2022) sont dépliées en une ligne par
-- pays émetteur via le design_group eu-* de l'année (match direct exact).
-- cf. referential/scrape_wikipedia_coins.py et memory project_eurlex_source.
CREATE TABLE IF NOT EXISTS wikipedia_nl_coins (
  country          TEXT NOT NULL,            -- ISO2
  year             INTEGER NOT NULL,
  theme            TEXT NOT NULL,            -- thème NL brut (nettoyé des notes)
  theme_slug       TEXT NOT NULL,            -- slugify(strip_2eur(theme))
  source_url       TEXT,                     -- ancre section, ex '#2007'
  matched_eurio_id TEXT REFERENCES coins(eurio_id) ON DELETE SET NULL,
  match_score      REAL,                     -- 1.0 = match direct (commune) ; NULL = fuzzy
  planned          INTEGER NOT NULL DEFAULT 0,
  fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (country, year, theme_slug)
) WITHOUT ROWID;

-- File de review des découvertes Numista ciblées (gap-fill de la matrice de
-- couverture). Le bulk auto (discover_numista_recent) crée les liens sans
-- review ; ce qui reste manquant sur la matrice est le résidu suspect → on
-- propose les candidats Numista ici (phase légère : titre + image + eurio_id
-- proposé) SANS rien écrire dans `coins`. L'éditeur accepte/rejette 1 à 1 ;
-- l'accept déclenche l'ingest complet (refetch_nids). cf. referential/discovery.py.
CREATE TABLE IF NOT EXISTS referential_discovery_queue (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  country           TEXT NOT NULL,            -- ISO2
  year              INTEGER NOT NULL,
  numista_id        INTEGER NOT NULL UNIQUE,
  proposed_eurio_id TEXT,                      -- calculé via eurio_id_from_numista_payload
  numista_title     TEXT,
  image_url         TEXT,                      -- URL Numista (obverse), affichage review only
  theme_wiki        TEXT,                      -- thème(s) wiki manquant(s) de la cellule (indice)
  is_commemorative  INTEGER NOT NULL DEFAULT 1,
  is_variant        INTEGER NOT NULL DEFAULT 0,
  status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'accepted', 'rejected')),
  discovered_at     TEXT NOT NULL DEFAULT (datetime('now')),
  resolved_at       TEXT
);

-- ─── Review collaborative — staging d'arbitrage ────────────────────────────
-- Les décisions prises par des amis reviewers dans le service review dédié
-- (VPS, review.db) sont tirées ici par `go-task ml:review:reconcile` SANS
-- toucher le canonique : elles attendent l'arbitrage humain (Raphaël) qui les
-- promeut (approve → applique le chemin decide() habituel) ou les rejette. Le
-- niveau de confiance entrant est 'peer_review' (cf. trust model). La clé `id`
-- = decisions.id du review.db → INSERT OR IGNORE = réconciliation idempotente.
-- cf. docs/work-in-progress/collaborative-review/ (02-data-model, 05, 07).
CREATE TABLE IF NOT EXISTS peer_review_decisions (
  id                   TEXT PRIMARY KEY,         -- = decisions.id (review.db)
  image_asset_id       TEXT NOT NULL,
  review_item_id       TEXT,                     -- = review_queue.id publié
  reviewer_token       TEXT NOT NULL,
  reviewer_name        TEXT NOT NULL,
  action               TEXT NOT NULL
                         CHECK (action IN ('accept', 'reject', 'skip')),
  decided_eurio_id     TEXT,
  decided_face         TEXT,
  decided_variant_kind TEXT,
  quality_reason       TEXT,
  notes                TEXT,
  decided_at           TEXT NOT NULL,
  imported_at          TEXT NOT NULL DEFAULT (datetime('now')),
  arbitration_status   TEXT NOT NULL DEFAULT 'pending'
                         CHECK (arbitration_status IN
                           ('pending', 'approved', 'rejected', 'superseded')),
  arbitrated_at        TEXT,
  arbitration_notes    TEXT
);
CREATE INDEX IF NOT EXISTS idx_peer_review_pending
  ON peer_review_decisions(arbitration_status)
  WHERE arbitration_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_peer_review_reviewer
  ON peer_review_decisions(reviewer_token);

-- ─── Modèle B : run-batch ingest (chunk C1) ──────────────────────────────────
-- Journal des run-batches appliqués au canonique (serveur = writer unique).
-- Le calcul lourd (scraping/crop/dino) tourne sur réplique read-only puis pousse
-- ses lignes par run ; `ingest_run` UPSERT par clé naturelle et marque ici le run
-- + son `batch_sha`. Re-POST du MÊME contenu (sha identique) = no-op total (couvre
-- `image_state_events`, sans clé naturelle). Cf. docs/work-in-progress/model-b/.
CREATE TABLE IF NOT EXISTS ingested_runs (
  run_id      TEXT PRIMARY KEY,
  batch_sha   TEXT NOT NULL,
  applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
  counts_json TEXT
);

-- ─── Modèle B : auth bearer de l'API (chunk C2) ──────────────────────────────
-- Tokens d'accès à l'eurio-api (writer unique). On stocke le SHA-256 du token,
-- jamais le secret en clair. Auth appliquée seulement si EURIO_API_AUTH_REQUIRED
-- est vrai (le local reste ouvert). Révocation = `revoked_at` non NULL.
CREATE TABLE IF NOT EXISTS api_tokens (
  token_sha  TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  revoked_at TEXT
);

-- ─── Scan du Jeu d'entraînement (improvement-loop P1+P2) ─────────────────────
-- Un scan = une passe Dino (vitl14) sur les crops éligibles d'une cohorte :
--   P1 · intrus : classement en ENSEMBLE FERMÉ contre les classes de la cohorte
--       (rank closed-set, même brique que la review) — désaccord fort entre la
--       classe assignée et le top-1 Dino → « probable intrus », remonté en tête
--       du Jeu d'entraînement.
--   P2 · face : verdict obverse/reverse (banque revers C7) écrit sur
--       image_assets.face quand il est NULL ou 'unknown' (jamais par-dessus un
--       obverse/reverse déjà posé) → vide le bucket « à confirmer ».
-- Exécuté en subprocess détaché (même doctrine que recrop_zero : l'état vit en
-- base, survit au --reload, reaper au boot). Table séparée de cohort_jobs (son
-- CHECK kind est gelé sur les DB existantes) mais mêmes conventions.
CREATE TABLE IF NOT EXISTS cohort_training_scans (
  id               TEXT PRIMARY KEY,                -- uuid hex
  cohort_id        TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,
  status           TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','done','failed')),
  anchors_kind     TEXT,                            -- banque closed-set (2eur_all)
  encoder_version  TEXT,
  intruder_margin  REAL,                            -- seuil de désaccord utilisé
  n_total          INTEGER,                         -- crops dans le scope au lancement
  n_done           INTEGER NOT NULL DEFAULT 0,
  n_intruders      INTEGER NOT NULL DEFAULT 0,      -- suspects levés (P1)
  n_faces_written  INTEGER NOT NULL DEFAULT 0,      -- faces résolues (P2)
  n_skipped        INTEGER NOT NULL DEFAULT 0,      -- crops sans ancre / illisibles
  started_at       TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at      TEXT,
  error            TEXT,
  pid              INTEGER                          -- subprocess détaché (reaper)
);
CREATE INDEX IF NOT EXISTS idx_training_scans_cohort
  ON cohort_training_scans(cohort_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_training_scans_running
  ON cohort_training_scans(status) WHERE status = 'running';

-- Verdict par crop du scan (REPLACE au re-scan via PK (scan_id, asset_id)).
-- `margin` = sim(top-1 classe cohorte) − sim(classe assignée) : > 0 quand Dino
-- préfère une AUTRE classe de la cohorte. `assigned_sim` = max(anchor_sim,
-- consensus_sim) : l'ancre canonique (1 photo studio) est complétée par le
-- consensus intra-classe (centroïde leave-one-out des crops éligibles avers)
-- — tue les faux positifs quand l'ancre matche mal les photos réelles
-- (ex. Kniefall de-2020). `is_intruder` applique le seuil du scan (désaccord
-- fort) — l'UI remonte ces crops en tête, l'humain tranche via la
-- réassignation existante.
CREATE TABLE IF NOT EXISTS cohort_training_scan_results (
  scan_id         TEXT NOT NULL REFERENCES cohort_training_scans(id) ON DELETE CASCADE,
  asset_id        TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  assigned_class  TEXT NOT NULL,                    -- classe (design_group/eurio) au scan
  assigned_sim    REAL,                             -- max(anchor_sim, consensus_sim)
  anchor_sim      REAL,                             -- meilleure ancre canonique de sa classe
  consensus_sim   REAL,                             -- centroïde LOO des camarades éligibles
  top1_class      TEXT,                             -- meilleure classe cohorte selon Dino
  top1_eurio_id   TEXT,                             -- membre gagnant (cible de réassign)
  top1_sim        REAL,
  margin          REAL,
  is_intruder     INTEGER NOT NULL DEFAULT 0,
  intruder_reason TEXT,                             -- 'margin' | 'outlier' | 'margin+outlier'
  face_verdict    TEXT,                             -- verdict P2 (obverse/reverse), NULL si non calculé
  face_written    INTEGER NOT NULL DEFAULT 0,       -- 1 si image_assets.face a été écrit
  -- Phase 2 funnel — suggestion typée dérivée du scan (reject/reassign/exclude),
  -- pour la worklist « À vérifier ». reject = denom≠2€ / hors sujet (sim absolue
  -- basse) / revers ; reassign = une autre classe cohorte le réclame (margin) ;
  -- exclude = outlier intra-classe + qualité basse.
  denom_score       REAL,                           -- probe 2€-ness (denom_probe), NULL si probe absente
  denom_verdict     TEXT CHECK (denom_verdict IS NULL OR denom_verdict IN ('2eur','not_2eur')),
  abs_max_sim       REAL,                           -- max sim à TOUTE la banque (hors sujet si < plancher)
  suggestion        TEXT CHECK (suggestion IS NULL OR suggestion IN ('reject','reassign','exclude')),
  suggestion_reason TEXT,                           -- 'denom' | 'off_topic' | 'reverse' | 'margin' | 'outlier+quality'
  suggestion_applied    INTEGER NOT NULL DEFAULT 0, -- 1 = geste appliqué par l'humain (bulk/one-shot)
  suggestion_applied_at TEXT,
  -- Le PO a tranché « faux positif, garde-le au train » : override humain du
  -- verdict intrus. training-crops lit `is_intruder AND NOT dismissed`, donc le
  -- badge disparaît sans réécrire is_intruder (audit du scan préservé).
  dismissed       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (scan_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_training_scan_results_scan
  ON cohort_training_scan_results(scan_id);
