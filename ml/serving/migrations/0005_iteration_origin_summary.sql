-- R3 (Model B) : itérations canoniques (sync Mac ↔ PC).
--
-- `created_on` = origine machine (mac/pc/vps) où l'itération a été calculée,
-- stampée à la création puis poussée au canonique — dit où vivent les artefacts
-- lourds (tflite/checkpoints) tant qu'ils ne sont pas migrés vers MinIO.
--
-- `summary_json` = snapshot dénormalisé des métriques (R@1, loss, verdict),
-- calculé côté compute (déjà dérivé par `_iteration_with_run_metrics`) et poussé
-- tel quel. Permet d'afficher les chiffres d'une itération partout SANS pousser
-- les tables lourdes training_runs / benchmark_runs (MVP R3, cf.
-- docs/work-in-progress/model-b/R3-iterations-canonical.md).
--
-- Idempotent (ADD COLUMN sur table sans la colonne ; db_migrate ne rejoue jamais
-- une migration appliquée). Miroir DDL canonique : ml/state/schema.sql.

ALTER TABLE experiment_iterations ADD COLUMN created_on TEXT;
ALTER TABLE experiment_iterations ADD COLUMN summary_json TEXT;
