# Phase 3 — Pipeline qualité photos

> Implémentation du `quality_score` + flag `training_eligible`.
> Spec détaillée : voir `quality-pipeline.md`.

## Pourquoi cette phase

Sans filtre, eBay et Catawiki polluent le dataset (lots multi-pièces,
flou, watermarks, captures d'écran). Ce pipeline est le verrou avant
de pouvoir vraiment exploiter les sources bruitées.

## Périmètre

### 3.1 Module `ml/quality/`

- `ml/quality/score.py` — chaîne complète sanity → detection → crop
  → sharpness → face → score final.
- `ml/quality/detector.py` — wrapper sur YOLO11-nano + Hough déjà
  utilisé côté scan, en mode batch CPU acceptable (les images
  passent en backoffice, pas en temps réel).
- `ml/quality/sharpness.py` — Laplacien variance + heuristiques bord.
- `ml/quality/face_classifier.py` — heuristique obverse vs reverse.
- `ml/quality/watermark.py` — OCR léger sur coins, détection
  watermark / capture d'écran.

### 3.2 Worker batch

`ml:quality:score-pending` (commande go-task) :

- Lit `image_assets WHERE quality_score IS NULL` par batch (1000).
- Charge l'image depuis `storage_path`.
- Applique la chaîne, met à jour `quality_score`,
  `training_eligible`, `quality_reason`, `face`.
- Logge les composantes dans `raw_payload.quality`.
- Idempotent : peut tourner après chaque run de fetch ou en cron.

### 3.3 Re-scoring

`ml:quality:rescore -- --source ebay --since 2026-01-01` :

- Re-applique la chaîne sur des images déjà scorées.
- Permet d'ajuster le seuil sans refetch.
- Versionne la chaîne (`quality_pipeline_version` dans
  `raw_payload`) pour tracer.

### 3.4 Intégration côté `prepare_dataset.py`

- Ajouter au resolver une lecture de `image_assets` filtrée par
  `training_eligible=true`.
- Flag `--source-mix` (cf. `quality-pipeline.md`).
- Conserver le comportement legacy (lecture `coin_images` Numista
  canonique) tant que toutes les sources ne sont pas migrées.

### 3.5 Page admin — onglet qualité

(Optionnel V1, mais facile une fois le reste là)

- Sur la page détail source, un encart "Qualité" :
  - histogramme des `quality_score`
  - répartition `quality_reason` pour les rejetés
  - quelques exemples cliquables haut score / bas score / borderline.

### 3.6 Tests

- `tests/quality/test_score_smoke.py` — fixtures images
  (canonical bonne, in-hand bonne, in-hand floue, lot multi-pièces,
  watermarkée, capture d'écran). Vérifier que le score sépare
  correctement.
- `tests/quality/test_rescore_idempotent.py` — re-scoring deux fois
  donne le même résultat.

## Out of scope (phase 3)

- ML supervisé sur le score — heuristiques + CV classique
  suffisent.
- Annotation humaine — pas de UI de review V1.
- Score différencié par usage (ex : "bon pour matching" vs "bon pour
  display") — un score global suffit.

## Validation

- Après run de la chaîne sur le dataset eBay phase 1 : on s'attend
  à 30-60% `training_eligible=true` selon l'agressivité du seuil
  (à calibrer empiriquement sur un échantillon de 100 images
  taggées à la main).
- R@1 live strict d'une itération lab incluant ces images doit
  s'améliorer vs. baseline canonical-only. Si pas d'amélioration,
  c'est que le filtre ne suffit pas et il faut creuser.
