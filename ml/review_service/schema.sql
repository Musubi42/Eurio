-- review.db — base du service review collaboratif (VPS).
-- Tampon de travail transient : la canonique reste eurio.db. Tout est
-- réconcilié via go-task ml:review:publish / ml:review:reconcile.
-- cf. docs/work-in-progress/collaborative-review/02-data-model.md

-- Amis autorisés à reviewer. Le token est À LA FOIS l'identité et le mot de
-- passe (low-security volontaire — lien transmis en privé). cf. 04-auth.md
CREATE TABLE IF NOT EXISTS reviewers (
  token         TEXT PRIMARY KEY,            -- ex. 'Paolo42'
  display_name  TEXT NOT NULL,               -- ex. 'Paolo'
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at  TEXT
);

-- Items à reviewer, poussés depuis eurio.db (status='open') par publish.
-- Auto-suffisant : aucune jointure vers eurio.db. crop = clé MinIO
-- (enrichment-crops), l'URL présignée est mintée au service-time.
CREATE TABLE IF NOT EXISTS review_items (
  id                TEXT PRIMARY KEY,         -- = review_queue.id (eurio.db)
  image_asset_id    TEXT NOT NULL UNIQUE,
  storage_path      TEXT,                     -- clé MinIO du crop (enrichment-crops)
  source            TEXT,                     -- ebay / numista / ...
  listing_title     TEXT,
  candidates_json   TEXT,                     -- [{eurio_id,label,country,denomination,year,thumb_url}]
  target_eurio_id   TEXT,
  dino_top1_json    TEXT,                     -- {eurio_id,label,score,thumb_url} | null
  priority          INTEGER NOT NULL DEFAULT 100,
  status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'claimed', 'decided', 'skipped')),
  claimed_by        TEXT REFERENCES reviewers(token),
  claimed_at        TEXT,                     -- pour le visibility timeout (TTL)
  published_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_items_claimable
  ON review_items(status, priority, published_at);
CREATE INDEX IF NOT EXISTS idx_items_claimed_by
  ON review_items(claimed_by) WHERE claimed_by IS NOT NULL;

-- Une ligne par décision d'un reviewer (1 reviewer/item en v1).
CREATE TABLE IF NOT EXISTS decisions (
  id                   TEXT PRIMARY KEY,
  review_item_id       TEXT NOT NULL REFERENCES review_items(id),
  reviewer_token       TEXT NOT NULL REFERENCES reviewers(token),
  action               TEXT NOT NULL CHECK (action IN ('accept', 'reject', 'skip')),
  decided_eurio_id     TEXT,
  decided_face         TEXT,
  decided_variant_kind TEXT,
  quality_reason       TEXT,
  notes                TEXT,
  decided_at           TEXT NOT NULL DEFAULT (datetime('now')),
  reconciled_at        TEXT                   -- NULL tant que pas tiré dans eurio.db
);
CREATE INDEX IF NOT EXISTS idx_decisions_unreconciled
  ON decisions(reconciled_at) WHERE reconciled_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_decisions_reviewer
  ON decisions(reviewer_token);

-- Méta clé/valeur : horodatages du dernier publish / reconcile, tamponnés par
-- les endpoints /admin/publish et /admin/decisions/ack quand le Mac les appelle.
-- Alimente le bloc « flux » de la page régie. cf. 10-admin-dashboard.md
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
