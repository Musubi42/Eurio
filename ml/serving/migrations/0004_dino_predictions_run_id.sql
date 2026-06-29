-- Model B (C6b) : run_id sur image_asset_dino_predictions.
--
-- Le backfill DINO produit des prédictions sur des assets PRÉEXISTANTS (anciens
-- runs) ; la table n'avait pas de run_id, donc un « dino-backfill run » ne pouvait
-- capter aucune prédiction via export_run (scope par asset_id du run). On ajoute
-- run_id (NULL pour les prédictions du scrape normal, collectées par asset_id) :
-- export_run collecte les prédictions par asset_id OU run_id (cf. client/runbatch).
--
-- Idempotent (ADD COLUMN sur table sans la colonne ; SQLite n'a pas IF NOT EXISTS
-- sur ADD COLUMN, mais db_migrate ne rejoue jamais une migration déjà appliquée).
-- Miroir DDL canonique : ml/state/schema.sql.

ALTER TABLE image_asset_dino_predictions ADD COLUMN run_id TEXT
  REFERENCES source_runs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_dino_pred_run ON image_asset_dino_predictions(run_id)
  WHERE run_id IS NOT NULL;
