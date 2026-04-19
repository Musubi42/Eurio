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
