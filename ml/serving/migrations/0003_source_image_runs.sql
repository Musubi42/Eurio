-- Model B / parité A↔B : lien M:N run ↔ source_image.
--
-- `source_images` est dédupliquée globalement (1 image = 1 contenu) ; la même
-- image ré-apparaît dans N runs (re-scrape d'un groupe par la freshness queue).
-- Avant ce fix, l'UPSERT écrasait `source_images.run_id` (last-writer-wins) →
-- un run ultérieur volait l'attribution d'un run antérieur, cassant l'idempotence
-- `batch_sha` du run volé. `run_id` devient first-seen-immuable (provenance) et
-- cette table porte la containment par-run (cf. client/runbatch.export_run).
--
-- Idempotent (CREATE IF NOT EXISTS + INSERT OR IGNORE). Appliqué au startup via
-- ``db_migrate.run_migrations()``. Le miroir DDL canonique vit dans
-- ``ml/state/schema.sql`` (DB Mac/réplique).
--
-- Cf. docs/work-in-progress/model-b/ + plan attribution stable source_images.

CREATE TABLE IF NOT EXISTS source_image_runs (
  source_image_id TEXT NOT NULL REFERENCES source_images(id) ON DELETE CASCADE,
  run_id          TEXT NOT NULL REFERENCES source_runs(id)   ON DELETE CASCADE,
  first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (source_image_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_source_image_runs_run ON source_image_runs(run_id);

-- Backfill : reconstruit les liens depuis les deux sources d'attribution
-- existantes. `image_assets` récupère les liens HISTORIQUES perdus par le vol
-- (un asset garde le run_id du run qui l'a créé, même si l'image a été réattribuée).
-- Filtre anti-orphelins : ne lier que les rows dont les cibles FK existent (le
-- canonique traîne ~503 violations FK historiques image_assets→source_runs,
-- dette séparée C8) — sinon ces liens orphelins casseraient au 1er COMMIT FK-ON.
INSERT OR IGNORE INTO source_image_runs (source_image_id, run_id)
  SELECT id, run_id FROM source_images
   WHERE run_id IS NOT NULL
     AND run_id IN (SELECT id FROM source_runs);
INSERT OR IGNORE INTO source_image_runs (source_image_id, run_id)
  SELECT ia.source_image_id, ia.run_id FROM image_assets ia
   WHERE ia.run_id IS NOT NULL
     AND ia.run_id IN (SELECT id FROM source_runs)
     AND ia.source_image_id IN (SELECT id FROM source_images);
