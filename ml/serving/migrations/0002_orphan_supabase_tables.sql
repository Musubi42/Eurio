-- data-layer-unification Phase 1 : rapatriement des 2 tables Supabase
-- orphelines vers eurio.db.
--
-- - coin_confusion_map : cartographie visuelle (DINOv2 v0.1). Lecture seule
--   côté frontend (vue Confusion). Écriture par pipeline ML (Phase 6+).
-- - sets_audit : log append-only des mutations sets. Lecture seule côté
--   frontend (vue Audit). Écriture future par endpoints sets.
--
-- Idempotent. Appliqué via ``db_migrate.run_migrations()`` au startup.
-- Le rapatriement de la donnée se fait par
-- ``ml/serving/migrate_orphan_supabase.py`` (one-shot, hors migration SQL).
--
-- Cf. docs/work-in-progress/data-layer-unification/IMPLEMENTATION.md §1.

-- ─── coin_confusion_map ────────────────────────────────────────────────────
-- Transposition du schéma Postgres (supabase/migrations/20260417_*.sql) :
-- - bigserial → INTEGER PRIMARY KEY AUTOINCREMENT
-- - jsonb → TEXT (JSON-stringifié)
-- - timestamptz DEFAULT now() → TEXT DEFAULT datetime('now')
-- - FK ON DELETE conservée (SQLite supporte si PRAGMA foreign_keys = ON)

CREATE TABLE IF NOT EXISTS coin_confusion_map (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  eurio_id           TEXT NOT NULL,
  encoder_version    TEXT NOT NULL,
  nearest_eurio_id   TEXT,
  nearest_similarity REAL NOT NULL,
  top_k_neighbors    TEXT NOT NULL,   -- JSON array
  zone               TEXT NOT NULL CHECK (zone IN ('green','orange','red')),
  computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(eurio_id, encoder_version),
  FOREIGN KEY (eurio_id) REFERENCES coins(eurio_id) ON DELETE CASCADE,
  FOREIGN KEY (nearest_eurio_id) REFERENCES coins(eurio_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_confusion_zone
  ON coin_confusion_map(zone);
CREATE INDEX IF NOT EXISTS idx_confusion_similarity
  ON coin_confusion_map(nearest_similarity DESC);
CREATE INDEX IF NOT EXISTS idx_confusion_eurio_id
  ON coin_confusion_map(eurio_id);


-- ─── sets_audit ────────────────────────────────────────────────────────────
-- Append-only audit log des mutations de sets éditoriaux.

CREATE TABLE IF NOT EXISTS sets_audit (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  set_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN (
    'create','update','delete','activate','deactivate','publish'
  )),
  before TEXT,                          -- JSON (état avant) ou NULL
  after  TEXT,                          -- JSON (état après) ou NULL
  actor  TEXT NOT NULL,                 -- email ou 'bootstrap-script' ou user_id
  at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sets_audit_set
  ON sets_audit(set_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_sets_audit_actor
  ON sets_audit(actor, at DESC);
