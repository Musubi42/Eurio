-- 0014 — Marquer un crop comme JEU D'ÉVALUATION, donc hors entraînement.
--
-- Chantier `juge-et-banc`, étape 2. Départager ArcFace et DINO exige un jeu
-- d'évaluation que NI L'UN NI L'AUTRE n'a vu. Jusqu'ici le dépôt n'avait aucun
-- moyen de dire « ce crop est de l'éval » : `training_eligible = 0` existe, mais
-- il veut dire « rejeté en review » — le confondre avec « réservé à l'éval »
-- perdrait la distinction le jour où un crop d'éval devrait revenir au train,
-- et ferait disparaître les 300 crops des compteurs de review.
--
-- D'où une colonne à part, TEXTE et pas booléenne : elle nomme le CORPUS
-- (`matrice-encodeurs-2026-08`), ce qui permet d'en avoir plusieurs, de savoir
-- lequel a servi à quelle mesure, et de rendre le hold-out relisable des mois
-- plus tard. `NULL` = pas d'éval, et c'est le défaut de tout le parc existant.
--
-- ⚠️ Le marquage n'est utile que si les DEUX collectes d'entraînement
-- l'honorent — il n'y a pas de point unique en amont :
--   * `ml/training/iteration_augmentations.py::_ebay_training_sources` (ArcFace,
--     et par ricochet le seed du préflight) ;
--   * `ml/training/foundation/anchors.py::_candidate_crops_for_class` (ancres DINO).
-- Les deux portent désormais `eval_corpus IS NULL`, et un test le verrouille.
--
-- ⚠️ Les OCTETS ne bougent pas. La clé S3 d'un crop est immuable et sert de
-- jointure partout : déplacer l'objet dans un préfixe `eval/` casserait chaque
-- ligne qui la référence sans rien apporter. C'est la LIGNE qui porte le rôle.

ALTER TABLE image_assets ADD COLUMN eval_corpus TEXT;

CREATE INDEX IF NOT EXISTS idx_image_assets_eval_corpus
  ON image_assets(eval_corpus) WHERE eval_corpus IS NOT NULL;
