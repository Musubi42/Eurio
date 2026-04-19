-- Migration: coin_confusion_map — visual similarity cartography
-- Date: 2026-04-17
-- Refs:
--   docs/research/ml-scalability-phases/phase-1-cartographie.md
--   docs/research/ml-scalability-phases/README.md
--
-- Context:
--   Phase 1 of the ML scalability plan: before scaling training from 7 to
--   300-500 designs, cartograph which coin designs are visually confusable
--   (pairs with high cosine similarity) and which are isolated. This table
--   stores, per coin and per encoder version, the nearest neighbor, the top-K
--   neighbors with similarities, and a zone classification (green/orange/red).
--
--   Encoder used for Phase 1: DINOv2 ViT-S/14 (generic self-supervised, not
--   our in-house ArcFace — that model is biased on 7 classes). The encoder
--   version is recorded in each row so the table can accumulate historical
--   snapshots (dinov2-vits14 now, eurio-arcface-v2 later for comparison).
--
--   The table is fully rebuildable from scratch (no manual data). The compute
--   pipeline lives in ml/confusion_map.py and is triggered by go-task
--   ml:confusion-map or the ML API endpoint /confusion-map/compute.

BEGIN;

CREATE TABLE IF NOT EXISTS coin_confusion_map (
  id                     bigserial PRIMARY KEY,
  eurio_id               text NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  encoder_version        text NOT NULL,
  nearest_eurio_id       text REFERENCES coins(eurio_id) ON DELETE SET NULL,
  nearest_similarity     real NOT NULL,
  top_k_neighbors        jsonb NOT NULL,
  zone                   text NOT NULL CHECK (zone IN ('green', 'orange', 'red')),
  computed_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE(eurio_id, encoder_version)
);

CREATE INDEX IF NOT EXISTS idx_confusion_zone
  ON coin_confusion_map(zone);

CREATE INDEX IF NOT EXISTS idx_confusion_similarity
  ON coin_confusion_map(nearest_similarity DESC);

CREATE INDEX IF NOT EXISTS idx_confusion_eurio_id
  ON coin_confusion_map(eurio_id);

COMMENT ON TABLE coin_confusion_map IS
  'Per-coin visual confusion cartography. One row per (eurio_id, encoder_version). Nearest neighbor excludes coins sharing the same Numista design id (annual re-issues of the same design are grouped as a single source image).';
COMMENT ON COLUMN coin_confusion_map.encoder_version IS
  'Identifier of the visual encoder used to compute similarities. E.g. dinov2-vits14, eurio-arcface-v2.';
COMMENT ON COLUMN coin_confusion_map.nearest_similarity IS
  'Cosine similarity with the nearest non-self, non-same-design neighbor. Range [0,1].';
COMMENT ON COLUMN coin_confusion_map.top_k_neighbors IS
  'Top-K nearest neighbors as jsonb array of {eurio_id, similarity, obverse_url}. Ordered by similarity descending.';
COMMENT ON COLUMN coin_confusion_map.zone IS
  'Confusion zone: green = isolated (training on Numista + aug is enough), orange = neighbor proximity (enrichment recommended), red = quasi-twin (enrichment mandatory).';


-- RLS: public read, admin write (mirrors coin_embeddings / sets pattern).
ALTER TABLE coin_confusion_map ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS coin_confusion_map_public_read ON coin_confusion_map;
CREATE POLICY coin_confusion_map_public_read ON coin_confusion_map
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS coin_confusion_map_admin_all ON coin_confusion_map;
CREATE POLICY coin_confusion_map_admin_all ON coin_confusion_map
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');

COMMIT;
