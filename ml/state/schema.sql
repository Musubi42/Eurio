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

-- Additive migrations for existing tables — SQLite has no `ADD COLUMN IF NOT
-- EXISTS`, so Store._bootstrap runs these via a PRAGMA-guarded Python helper
-- (see `state/store.py::_ensure_column`). Keeping them here as reference only.
--
-- ALTER TABLE training_runs    ADD COLUMN aug_recipe_id TEXT
--   REFERENCES augmentation_recipes(id) ON DELETE SET NULL;
-- ALTER TABLE training_staging ADD COLUMN aug_recipe_id TEXT
--   REFERENCES augmentation_recipes(id) ON DELETE SET NULL;
